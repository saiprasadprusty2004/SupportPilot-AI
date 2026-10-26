# Acme Studio product handbook

## Team invitations

Workspace owners can invite teammates from Settings → Members. Check that the invite email matches the teammate's sign-in address. Ask the teammate to check their spam folder. Invitations expire after 48 hours; create a new invitation if needed. Only owners can manage workspace membership. If invitations are still not delivered, share the invitation link directly with the intended teammate.

## Password resets

Team members can ask their workspace owner to create a password reset link. Reset links remain valid for 30 minutes and can be used once. Resetting a password signs the user out of all existing sessions. Never ask a customer to share their password.

## Project exports

Open a project and choose Export in the upper-right toolbar. Select PDF for presentations or CSV for tabular data. The export includes the currently selected view. Large exports can take up to two minutes. If an export fails, ask the customer for the project ID and escalate to engineering.

## API rate limits

Integrations receive HTTP 429 when their request quota is exhausted. Honor the Retry-After header, use exponential backoff, and avoid repeated immediate retries. If throttling continues beyond the documented reset time, escalate to support engineering with the integration ID, timestamp, and request ID. Never include API keys or access tokens in an escalation.
