import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { Check, Copy, ShieldCheck, UserPlus } from "lucide-react";
import { Badge, Button, Modal, SectionHeading } from "../components/ui";
import { useWorkspace } from "../lib/workspace";
import { api, post } from "../lib/api";

import { Heading, useError } from "./shared";
export default function SettingsPage() {
  const data = useWorkspace();
  const [workspaceName, setWorkspaceName] = useState(
    data.session.workspaces[0]?.name || "",
  );
  const [channel, setChannel] = useState("");
  const [stripe, setStripe] = useState("");
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteLink, setInviteLink] = useState("");
  const [busy, setBusy] = useState(false);
  const [inviteRole, setInviteRole] = useState("agent");
  const [resetLink, setResetLink] = useState("");
  const [removing, setRemoving] = useState<{ id: string; name: string } | null>(
    null,
  );
  const isOwner = data.role === "owner";
  const membersQuery = useQuery({
    queryKey: ["members"],
    queryFn: () =>
      api<{
        items: {
          id: string;
          user_id: string;
          name: string;
          email: string;
          role: string;
        }[];
      }>("/members"),
    enabled: !data.preview,
  });
  const workspaceQuery = useQuery({
    queryKey: ["workspace-settings"],
    queryFn: () => api<{ name: string; slack_channel: string }>("/workspace"),
    enabled: !data.preview,
  });
  useEffect(() => {
    if (workspaceQuery.data) {
      setWorkspaceName(workspaceQuery.data.name);
      setChannel(workspaceQuery.data.slack_channel);
    }
  }, [workspaceQuery.data]);
  const report = useError();
  async function save() {
    if (data.preview) {
      data.notify("Preview: workspace preferences saved");
      return;
    }
    setBusy(true);
    try {
      await api("/workspace", {
        method: "PATCH",
        body: JSON.stringify({ name: workspaceName, slack_channel: channel }),
      });
      data.refresh();
      data.notify("Workspace settings saved");
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page-enter settings-page">
      <Heading
        eyebrow="MAKE IT YOURS"
        title="A workspace that fits"
        subtitle="The little details that keep your team, your tools, and your pilot in sync."
      />
      <div className="settings-grid">
        <section className="panel settings-card">
          <SectionHeading title="Workspace details" />
          <label>
            Workspace name
            <input
              value={workspaceName}
              onChange={(e) => setWorkspaceName(e.target.value)}
            />
          </label>
          <label>
            Approved Slack escalation channel ID
            <input
              placeholder="C0123456789"
              value={channel}
              onChange={(e) => setChannel(e.target.value)}
            />
          </label>
          <p className="help-text">
            Your pilot can only propose escalations to this channel. Posting
            still requires owner approval.
          </p>
          <Button onClick={() => void save()} disabled={busy || !isOwner}>
            Save changes
            <Check size={14} />
          </Button>
        </section>
        <section className="panel settings-card">
          <SectionHeading title="A little more personal" />
          {!data.preview && (
            <a
              className="button button-secondary"
              href="/api/v1/auth/google/start?link=true"
            >
              Link your Google sign-in
            </a>
          )}
          <div className="preference-row">
            <div>
              <strong>3D agent graphics</strong>
              <p>Show the interactive constellation on supported devices.</p>
            </div>
            <button
              className={`toggle ${data.graphics ? "on" : ""}`}
              role="switch"
              aria-checked={data.graphics}
              aria-label="3D agent graphics"
              onClick={() => data.setGraphics(!data.graphics)}
            >
              <span />
            </button>
          </div>
          <div className="settings-note">
            <ShieldCheck size={17} />
            <p>
              Reduced-motion preferences are always respected. Graphics
              automatically simplify on smaller screens.
            </p>
          </div>
        </section>
        <section className="panel settings-card">
          <SectionHeading title="Bring your team along" />
          {!isOwner && (
            <p className="help-text">
              Ask a workspace owner to invite or manage teammates.
            </p>
          )}
          <label>
            Invite by email
            <input
              type="email"
              placeholder="teammate@company.com"
              value={inviteEmail}
              onChange={(e) => setInviteEmail(e.target.value)}
            />
          </label>
          <label>
            Invitation role
            <select
              value={inviteRole}
              onChange={(e) => setInviteRole(e.target.value)}
              disabled={!isOwner}
            >
              <option value="agent">Agent — prepare drafts</option>
              <option value="owner">Owner — approve and manage</option>
            </select>
          </label>
          <Button
            variant="secondary"
            disabled={!inviteEmail || !isOwner}
            onClick={async () => {
              if (data.preview) {
                setInviteLink(
                  "https://supportpilot.example/invite?token=preview-only",
                );
                return;
              }
              try {
                const result = await post<{ url: string }>("/members/invites", {
                  email: inviteEmail,
                  role: inviteRole,
                });
                setInviteLink(result.url);
              } catch (e) {
                report(e);
              }
            }}
          >
            <UserPlus size={14} />
            Create invite link
          </Button>
          {inviteLink && (
            <div className="copy-field">
              <input readOnly value={inviteLink} />
              <button
                className="icon-button"
                aria-label="Copy invitation"
                onClick={() => {
                  void navigator.clipboard.writeText(inviteLink);
                  data.notify("Invite link copied");
                }}
              >
                <Copy size={15} />
              </button>
            </div>
          )}
          <p className="help-text">
            Share the link directly. Invitations expire after 48 hours.
          </p>
        </section>
        <section className="panel settings-card">
          <SectionHeading title="Refunds, safely rehearsed">
            <Badge status="pending">Test mode only</Badge>
          </SectionHeading>
          <label>
            Workspace Stripe test key
            <input
              type="password"
              placeholder="sk_test_…"
              autoComplete="off"
              value={stripe}
              onChange={(e) => setStripe(e.target.value)}
            />
          </label>
          <p className="help-text">
            Stored encrypted. Live keys and live payments are rejected. Refunds
            always require approval.
          </p>
          <Button
            variant="secondary"
            disabled={
              !isOwner ||
              (!stripe.startsWith("sk_test_") && !stripe.startsWith("rk_test_"))
            }
            onClick={async () => {
              if (data.preview) {
                setStripe("");
                data.notify("Preview: no credentials were stored");
                return;
              }
              try {
                await post("/workspace/stripe-key", { key: stripe });
                setStripe("");
                data.notify("Stripe test key stored securely");
              } catch (e) {
                report(e);
              }
            }}
          >
            <ShieldCheck size={14} />
            Save test key
          </Button>
        </section>
        <section className="panel settings-card members-card">
          <SectionHeading title="Your team" />
          {data.preview && (
            <p className="help-text">
              Alex Morgan · Workspace owner · Illustrative preview
            </p>
          )}
          {membersQuery.data?.items.map((member) => (
            <div className="member-row" key={member.id}>
              <div>
                <strong>{member.name}</strong>
                <small>
                  {member.email} · {member.role}
                </small>
              </div>
              {isOwner && (
                <div className="member-controls">
                  <Button
                    variant="secondary"
                    onClick={async () => {
                      try {
                        const result = await post<{ url: string }>(
                          `/members/${member.id}/reset-link`,
                          {},
                        );
                        setResetLink(result.url);
                      } catch (e) {
                        report(e);
                      }
                    }}
                  >
                    Create reset link
                  </Button>
                  {member.user_id !== data.session.user.id && (
                    <Button variant="ghost" onClick={() => setRemoving(member)}>
                      Remove
                    </Button>
                  )}
                </div>
              )}
            </div>
          ))}
          {resetLink && (
            <div className="copy-field">
              <input
                aria-label="Password reset link"
                readOnly
                value={resetLink}
              />
              <button
                className="icon-button"
                aria-label="Copy password reset link"
                onClick={() => {
                  void navigator.clipboard.writeText(resetLink);
                  data.notify("Reset link copied");
                }}
              >
                <Copy size={15} />
              </button>
            </div>
          )}
          <p className="help-text">
            Reset links expire after 30 minutes. Share them directly with the
            intended teammate.
          </p>
        </section>
      </div>
      <Modal
        open={!!removing}
        onOpenChange={(open) => {
          if (!open) setRemoving(null);
        }}
        title="Remove workspace access"
        description={`Remove ${removing?.name || "this teammate"} from this workspace? Their connected automation will be disabled.`}
      >
        <Button
          variant="danger"
          disabled={busy}
          onClick={async () => {
            if (!removing) return;
            setBusy(true);
            try {
              await api(`/members/${removing.id}`, { method: "DELETE" });
              setRemoving(null);
              await membersQuery.refetch();
              data.notify("Workspace access removed");
            } catch (e) {
              report(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          Remove member
        </Button>
      </Modal>
    </div>
  );
}
