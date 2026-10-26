import base64
import json
import re
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr, parsedate_to_datetime
from urllib.parse import quote, urlparse

import httpx

from app.config import settings
from app.models import Connection
from app.security import decrypt, redact

SCOPES = {
    "gmail": ["https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.send"],
    "slack": ["channels:read", "groups:read", "chat:write"],
    "googledrive": ["https://www.googleapis.com/auth/drive.readonly"],
}


class ProviderError(Exception):
    def __init__(self, message, *, transient=False, uncertain=False, retry_after=0, quota=False):
        super().__init__(message)
        self.transient = transient
        self.uncertain = uncertain
        self.retry_after = retry_after
        self.quota = quota


def response_error(response, write=False):
    if response.is_success:
        return
    code = response.status_code
    retry = response.headers.get("retry-after", "0")
    try:
        retry_seconds = (
            int(retry)
            if retry.isdigit()
            else max(0, int((parsedate_to_datetime(retry) - datetime.now(timezone.utc)).total_seconds()))
        )
    except (ValueError, TypeError, OverflowError):
        retry_seconds = 0
    raise ProviderError(
        f"Provider returned HTTP {code}",
        transient=code == 429 or code >= 500,
        uncertain=write and code >= 500,
        retry_after=retry_seconds,
        quota=code == 429,
    )


class Composio:
    base = "https://backend.composio.dev/api/v3.1"

    def request(self, method, path, **kwargs):
        if not settings().composio_api_key:
            raise ProviderError("Composio is not configured")
        try:
            with httpx.Client(timeout=httpx.Timeout(45, connect=10)) as client:
                response = client.request(
                    method, self.base + path, headers={"x-api-key": settings().composio_api_key}, **kwargs
                )
                response_error(response)
                return response.json()
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderError(
                "Composio transport failure", transient=True, uncertain=method != "GET"
            ) from exc

    def connect(self, user_id, provider, callback):
        auth_config = getattr(settings(), f"composio_{provider}_auth_config")
        if not auth_config:
            raise ProviderError(f"Set COMPOSIO_{provider.upper()}_AUTH_CONFIG with least-privilege scopes")
        return self.request(
            "POST",
            "/connected_accounts/link",
            json={"user_id": user_id, "auth_config_id": auth_config, "callback_url": callback},
        )

    def complete(self, user_id, session_uri):
        return self.request(
            "POST", "/connected_accounts/complete_auth", json={"user_id": user_id, "session_uri": session_uri}
        )

    def account(self, connection: Connection):
        result = self.request("GET", "/connected_accounts/" + quote(connection.account_id, safe=""))
        expected = f"{connection.workspace_id}:{connection.user_id}"
        actual = result.get("user_id") or result.get("entity_id")
        if actual != expected or result.get("status", "").upper() != "ACTIVE":
            raise ProviderError("Connection expired or identity mismatch; reconnect your account")
        toolkit = result.get("toolkit", {}).get("slug")
        config_id = result.get("auth_config", {}).get("id") or result.get("auth_config_id")
        if toolkit != connection.provider or config_id != getattr(
            settings(), f"composio_{connection.provider}_auth_config"
        ):
            raise ProviderError("Connection toolkit or configured least-privilege auth config does not match")
        return result

    def proxy(self, connection, endpoint, method="GET", body=None, params=None):
        # Internal-only API. Callers below select fixed provider endpoints; never exposed to the LLM or HTTP API.
        write = method != "GET"
        try:
            result = self.request(
                "POST",
                "/tools/execute/proxy",
                json={
                    "connected_account_id": connection.account_id,
                    "user_id": f"{connection.workspace_id}:{connection.user_id}",
                    "endpoint": endpoint,
                    "method": method,
                    "body": body,
                    "parameters": [
                        {"name": k, "value": str(v), "in": "query"} for k, v in (params or {}).items()
                    ],
                },
            )
        except ProviderError as exc:
            exc.uncertain = write and (exc.uncertain or exc.transient and not exc.quota)
            raise
        code = int(result.get("status", 500))
        if code >= 400:
            raise ProviderError(
                f"Provider rejected request ({code})",
                transient=code == 429 or code >= 500,
                uncertain=write and code >= 500,
                quota=code == 429,
                retry_after=60,
            )
        data = result.get("data", {})
        if isinstance(data, dict) and data.get("ok") is False:
            raise ProviderError(f"Provider rejected action: {redact(data.get('error', 'unknown'))}")
        if result.get("binary_data"):
            return result
        return data

    def gmail_profile(self, connection):
        return self.proxy(connection, "https://gmail.googleapis.com/gmail/v1/users/me/profile")

    def display_identity(self, connection):
        if connection.provider == "gmail":
            label = self.gmail_profile(connection).get("emailAddress")
        elif connection.provider == "slack":
            result = self.proxy(connection, "https://slack.com/api/auth.test")
            label = (
                f"{result.get('team', '')} / {result.get('user', '')}"
                if result.get("team_id") and result.get("user_id")
                else None
            )
        else:
            label = None
        if not label:
            raise ProviderError("Unable to verify the acting account's display identity")
        return label[:254]

    def gmail_messages(self, connection, after=None):
        params = {"labelIds": connection.label, "maxResults": 100}
        if after:
            params["q"] = f"after:{int(after)}"
        messages, cursor = [], None
        # Bounded catch-up; cursor is advanced only after all returned pages are processed.
        for _ in range(20):
            if cursor:
                params["pageToken"] = cursor
            data = self.proxy(
                connection, "https://gmail.googleapis.com/gmail/v1/users/me/messages", params=params
            )
            messages.extend(data.get("messages", []))
            cursor = data.get("nextPageToken")
            if not cursor:
                return messages
        raise ProviderError("Mailbox catch-up exceeds 2,000 messages; narrow the configured support label")

    def gmail_message(self, connection, message_id):
        return self.proxy(
            connection,
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/" + quote(message_id, safe=""),
            params={"format": "full"},
        )

    def gmail_thread_version(self, connection, thread_id):
        result = self.proxy(
            connection,
            "https://gmail.googleapis.com/gmail/v1/users/me/threads/" + quote(thread_id, safe=""),
            params={"format": "minimal"},
        )
        return [m["id"] for m in result.get("messages", []) if "SENT" not in m.get("labelIds", [])]

    def send_reply(self, connection, args, action_id, in_reply_to=None):
        # Resolve original RFC metadata; a Gmail thread ID alone does not preserve threading.
        if not in_reply_to:
            thread = self.proxy(
                connection,
                "https://gmail.googleapis.com/gmail/v1/users/me/threads/" + quote(args["thread_id"], safe=""),
                params={"format": "metadata", "metadataHeaders": "Message-ID"},
            )
            inbound = [m for m in thread.get("messages", []) if "SENT" not in m.get("labelIds", [])]
            headers = gmail_headers(inbound[-1].get("payload", {})) if inbound else {}
            in_reply_to = headers.get("message-id", "")
        if not re.fullmatch(r"<[^<>\s]+@[^<>\s]+>", in_reply_to):
            raise ProviderError("Original message has no valid Message-ID; review this ticket manually")
        message = EmailMessage()
        message["To"] = args["to"]
        message["Subject"] = args["subject"]
        message["Message-ID"] = f"<{action_id}@supportpilot.local>"
        message["In-Reply-To"] = in_reply_to
        message["References"] = in_reply_to
        message.set_content(args["body"])
        return self.proxy(
            connection,
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            "POST",
            {"raw": base64.urlsafe_b64encode(message.as_bytes()).decode(), "threadId": args["thread_id"]},
        )

    def slack_channels(self, connection):
        channels, cursor = [], ""
        for _ in range(10):
            result = self.proxy(
                connection,
                "https://slack.com/api/conversations.list",
                params={"types": "public_channel,private_channel", "limit": 200, "cursor": cursor},
            )
            channels.extend(result.get("channels", []))
            cursor = result.get("response_metadata", {}).get("next_cursor", "")
            if not cursor:
                return channels
        raise ProviderError("Channel discovery exceeds 2,000 channels; configure a channel ID directly")

    def slack_send(self, connection, args, action_id):
        return self.proxy(
            connection,
            "https://slack.com/api/chat.postMessage",
            "POST",
            {
                "channel": args["channel"],
                "text": args["text"],
                "client_msg_id": action_id,
                "unfurl_links": False,
                "unfurl_media": False,
            },
        )

    def drive_files(self, connection, query=""):
        params = {
            "pageSize": 50,
            "fields": "files(id,name,mimeType,modifiedTime,size)",
            "q": "trashed = false",
        }
        if query:
            escaped = query.replace("\\", "\\\\").replace("'", "\\'")
            params["q"] += f" and name contains '{escaped}'"
        return self.proxy(connection, "https://www.googleapis.com/drive/v3/files", params=params).get(
            "files", []
        )

    def drive_download(self, connection, file_id):
        url = "https://www.googleapis.com/drive/v3/files/" + quote(file_id, safe="")
        meta = self.proxy(connection, url, params={"fields": "id,name,mimeType,size,webViewLink"})
        if int(meta.get("size", 0)) > 25 * 1024 * 1024:
            raise ProviderError("File exceeds the 25 MB limit")
        native = meta["mimeType"] == "application/vnd.google-apps.document"
        result = self.proxy(
            connection,
            url + ("/export" if native else ""),
            params={"mimeType": "text/plain"} if native else {"alt": "media"},
        )
        if isinstance(result, str):
            data = result.encode()
        elif "binary_data" in result:
            signed = result["binary_data"]["url"]
            parsed = urlparse(signed)
            host = parsed.hostname or ""
            if parsed.scheme != "https" or not any(
                host == h or host.endswith("." + h)
                for h in ("amazonaws.com", "storage.googleapis.com", "composio.dev")
            ):
                raise ProviderError("Unexpected file delivery host")
            with httpx.stream("GET", signed, timeout=45, follow_redirects=False) as response:
                response_error(response)
                parts, size = [], 0
                for part in response.iter_bytes():
                    size += len(part)
                    if size > 25 * 1024 * 1024:
                        raise ProviderError("File exceeds the 25 MB limit")
                    parts.append(part)
                data = b"".join(parts)
        else:
            raise ProviderError("Unsupported Drive download response")
        if native:
            meta["name"] += ".txt"
            meta["mimeType"] = "text/plain"
        if not data or len(data) > 25 * 1024 * 1024:
            raise ProviderError("File is empty or exceeds the 25 MB limit")
        return meta, data


class Stripe:
    def __init__(self, workspace):
        if not workspace.stripe_key_ciphertext:
            raise ProviderError("Configure a workspace Stripe test key first")
        self.key = decrypt(workspace.stripe_key_ciphertext)
        if not self.key.startswith(("sk_test_", "rk_test_")):
            raise ProviderError("Live Stripe keys are forbidden")

    def request(self, method, path, data=None, key=None):
        try:
            headers = {"Authorization": "Bearer " + self.key, "Stripe-Version": "2025-02-24.acacia"}
            if key:
                headers["Idempotency-Key"] = key
            response = httpx.request(
                method, "https://api.stripe.com/v1/" + path, headers=headers, data=data, timeout=30
            )
            response_error(response, write=method == "POST")
            result = response.json()
            if result.get("livemode"):
                raise ProviderError("Live Stripe resources are forbidden")
            return result
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            # Stripe retries are safe using the same persisted idempotency key.
            raise ProviderError("Stripe transport failure", transient=True) from exc

    def payment(self, payment_id):
        payment = self.request("GET", "payment_intents/" + quote(payment_id, safe=""))
        charge_id = payment.get("latest_charge")
        if not charge_id or payment.get("status") != "succeeded":
            raise ProviderError("Payment has no refundable successful charge")
        charge = self.request("GET", "charges/" + quote(charge_id, safe=""))
        payment["remaining"] = charge["amount"] - charge.get("amount_refunded", 0)
        return payment

    def refund(self, args, idempotency_key):
        payment = self.payment(args["payment_id"])
        if args["currency"] != payment["currency"] or args["amount"] > payment["remaining"]:
            raise ProviderError("Refund currency or remaining amount changed")
        return self.request(
            "POST",
            "refunds",
            data={
                "payment_intent": args["payment_id"],
                "amount": args["amount"],
                "reason": args["reason"],
                "metadata[supportpilot_action]": idempotency_key,
            },
            key=idempotency_key,
        )

    def find_refund(self, payment_id, idempotency_key):
        result = self.request("GET", "refunds?payment_intent=" + quote(payment_id, safe="") + "&limit=100")
        for refund in result.get("data", []):
            if refund.get("metadata", {}).get("supportpilot_action") == idempotency_key:
                if refund.get("livemode"):
                    raise ProviderError("Live Stripe resources are forbidden")
                return refund
        return None


def gmail_body(payload):
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"] + "===").decode(errors="replace")[:30000]
    return "\n".join(filter(None, (gmail_body(part) for part in payload.get("parts", []))))[:30000]


def gmail_headers(payload):
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    headers["sender_email"] = parseaddr(headers.get("from", ""))[1]
    return headers


class Groq:
    def complete(self, messages, tools):
        if not settings().groq_api_key:
            raise ProviderError("Set GROQ_API_KEY to run the live agent")
        from redis import Redis
        from redis.exceptions import RedisError
        import time

        # Atomic shared budget; conservative output reservation avoids free-tier burst storms.
        estimate = sum(len(json.dumps(m)) // 3 + 1 for m in messages) + len(json.dumps(tools)) // 3 + 1000
        if estimate > settings().groq_tokens_per_minute:
            raise ProviderError(
                "Context exceeds configured token budget; narrow the task or retrieved context"
            )
        script = """
        local r = tonumber(redis.call('GET', KEYS[1]) or '0')
        local t = tonumber(redis.call('GET', KEYS[2]) or '0')
        if r >= tonumber(ARGV[1]) or t + tonumber(ARGV[3]) > tonumber(ARGV[2]) then return 0 end
        redis.call('INCR', KEYS[1]); redis.call('EXPIRE', KEYS[1], 70)
        redis.call('INCRBY', KEYS[2], ARGV[3]); redis.call('EXPIRE', KEYS[2], 70)
        return 1
        """
        try:
            redis = Redis.from_url(settings().redis_url, socket_timeout=3)
            minute = int(time.time() // 60)
            allowed = redis.eval(
                script,
                2,
                f"groq:req:{minute}",
                f"groq:tokens:{minute}",
                settings().groq_requests_per_minute,
                settings().groq_tokens_per_minute,
                estimate,
            )
        except RedisError as exc:
            raise ProviderError("Provider budget service unavailable", transient=True) from exc
        if not allowed:
            raise ProviderError("Shared provider quota is temporarily exhausted", quota=True, retry_after=60)
        try:
            response = httpx.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": "Bearer " + settings().groq_api_key},
                json={
                    "model": settings().groq_model,
                    "messages": messages,
                    "tools": tools,
                    "tool_choice": "auto",
                    "max_completion_tokens": 1000,
                    "temperature": 0.2,
                },
                timeout=60,
            )
            response_error(response)
            return response.json()["choices"][0]["message"]
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderError("Model transport failure", transient=True) from exc
