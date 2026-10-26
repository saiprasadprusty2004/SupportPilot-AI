import { useState } from "react";

import {
  Check,
  CheckCheck,
  CheckCircle2,
  GitBranch,
  LoaderCircle,
  Plus,
  Settings2,
  ShieldCheck,
  Trash2,
} from "lucide-react";
import { Avatar, Badge, Button, Modal, ProviderIcon } from "../components/ui";
import { useWorkspace } from "../lib/workspace";
import { api, post } from "../lib/api";

import { Heading, useError } from "./shared";
export default function ConnectionsPage() {
  const data = useWorkspace();
  const [busy, setBusy] = useState("");
  const [consent, setConsent] = useState<string | null>(null);
  const [label, setLabel] = useState("INBOX");
  const report = useError();
  async function connect(provider: string) {
    if (data.preview) {
      data.notify(
        "Preview only. Live OAuth starts from the connected application.",
      );
      return;
    }
    setBusy(provider);
    try {
      const response = await post<{ redirect_url: string }>(
        "/connections/connect",
        { provider },
      );
      window.location.assign(response.redirect_url);
    } catch (e) {
      report(e);
    } finally {
      setBusy("");
    }
  }
  return (
    <div className="page-enter">
      <Heading
        eyebrow="BETTER TOGETHER"
        title="Your tools, one thoughtful pilot"
        subtitle="Connect your own accounts. Keep your credentials private. Make work flow."
      />
      <div className="info-strip">
        <ShieldCheck size={18} />
        <span>
          Your accounts belong to you. Tokens are managed securely by Composio
          and never shared with the model.
        </span>
      </div>
      <div className="integration-grid">
        {[
          {
            provider: "gmail",
            name: "Gmail",
            type: "CUSTOMER CONVERSATIONS",
            description:
              "Read incoming support tickets and prepare thoughtful, approved replies.",
            scopes: ["Read support messages", "Send approved replies"],
          },
          {
            provider: "slack",
            name: "Slack",
            type: "TEAM COLLABORATION",
            description:
              "Bring the right people into the conversation with approved escalations.",
            scopes: ["Discover channels", "Post approved messages"],
          },
          {
            provider: "googledrive",
            name: "Google Drive",
            type: "SHARED KNOWLEDGE",
            description:
              "Turn selected product documents into answers your customers can trust.",
            scopes: ["Read selected documents", "Import shared snapshots"],
          },
        ].map((item) => {
          const connection = data.connections.find(
            (c) => c.provider === item.provider,
          );
          return (
            <article className="panel integration-card" key={item.provider}>
              <div className="integration-card-top">
                <span className="integration-logo">
                  <ProviderIcon provider={item.provider} size={34} />
                </span>
                {connection?.status === "active" ? (
                  <Badge status="active">Connected</Badge>
                ) : (
                  <Badge status="disconnected">Not connected</Badge>
                )}
              </div>
              <span className="eyebrow">{item.type}</span>
              <h2>{item.name}</h2>
              <p>{item.description}</p>
              <ul>
                {item.scopes.map((s) => (
                  <li key={s}>
                    <CheckCircle2 size={13} />
                    {s}
                  </li>
                ))}
              </ul>
              {connection && (
                <div className="connected-account">
                  <Avatar
                    name={connection.account_email || item.name}
                    size="small"
                  />
                  <span>
                    {connection.account_email || "Your connected account"}
                  </span>
                </div>
              )}
              <div className="integration-card-actions">
                {connection?.status === "active" ? (
                  <>
                    <Button
                      variant="secondary"
                      onClick={() => {
                        setConsent(connection.id);
                        setLabel(connection.label || "INBOX");
                      }}
                    >
                      <Settings2 size={14} />
                      Manage connection
                    </Button>
                    <button
                      className="icon-button danger-text"
                      aria-label={"Disconnect " + item.name}
                      onClick={async () => {
                        if (data.preview) {
                          data.notify(
                            "Preview: sample connection remains active",
                          );
                          return;
                        }
                        try {
                          await api("/connections/" + connection.id, {
                            method: "DELETE",
                          });
                          data.refresh();
                          data.notify("Account disconnected");
                        } catch (e) {
                          report(e);
                        }
                      }}
                    >
                      <Trash2 size={15} />
                    </button>
                  </>
                ) : (
                  <Button
                    disabled={busy === item.provider}
                    onClick={() => void connect(item.provider)}
                  >
                    {busy === item.provider ? (
                      <LoaderCircle size={14} className="spin" />
                    ) : (
                      <Plus size={14} />
                    )}
                    Connect {item.name}
                  </Button>
                )}
              </div>
            </article>
          );
        })}
      </div>
      <div className="connection-principles">
        <div>
          <ShieldCheck size={23} />
          <h3>Your credentials stay private</h3>
          <p>Every connection is isolated to your user and workspace.</p>
        </div>
        <div>
          <CheckCheck size={23} />
          <h3>Only the access you need</h3>
          <p>Limited permissions for a carefully defined set of tools.</p>
        </div>
        <div>
          <GitBranch size={23} />
          <h3>Nothing slips past you</h3>
          <p>Outbound actions need owner approval before execution.</p>
        </div>
      </div>
      <Modal
        open={!!consent}
        onOpenChange={(open) => !open && setConsent(null)}
        title="You’re in control"
        description="Enabling automation lets your pilot act through your connection after a workspace owner approves the exact action."
      >
        <label>
          Gmail support label ID
          <input
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="INBOX or Label_123"
          />
        </label>
        <p className="consent-note">
          Initial Gmail activation starts with new messages. Historical backfill
          is a separate action. Disconnecting pauses future tool calls.
        </p>
        <div className="modal-footer">
          <Button variant="secondary" onClick={() => setConsent(null)}>
            Cancel
          </Button>
          <Button
            onClick={async () => {
              if (!consent) return;
              if (data.preview) {
                data.notify("Preview: automation consent recorded locally");
                setConsent(null);
                return;
              }
              try {
                await api("/connections/" + consent, {
                  method: "PATCH",
                  body: JSON.stringify({
                    automation_enabled: true,
                    approval_policy_accepted: true,
                    label,
                  }),
                });
                data.refresh();
                setConsent(null);
                data.notify("Automation enabled with mandatory owner approval");
              } catch (e) {
                report(e);
              }
            }}
          >
            Accept policy & enable
            <Check size={14} />
          </Button>
        </div>
      </Modal>
    </div>
  );
}
