import { motion, useReducedMotion } from "motion/react";
import { useState } from "react";

import {
  ArrowUpRight,
  Check,
  CheckCheck,
  Clock3,
  ShieldCheck,
  X,
} from "lucide-react";
import {
  Badge,
  Button,
  Citations,
  Empty,
  Modal,
  ProviderIcon,
  Time,
} from "../components/ui";
import { useWorkspace } from "../lib/workspace";

import type { Action } from "../lib/types";
import { post } from "../lib/api";

import { Heading, LoadMore, useError } from "./shared";
export default function ApprovalsPage() {
  const reducedMotion = useReducedMotion();
  const data = useWorkspace();
  const [selected, setSelected] = useState<Action | null>(null);
  const [edited, setEdited] = useState<Record<string, string | number>>({});
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState("pending");
  const [reconciliation, setReconciliation] = useState<Action | null>(null);
  const [outcome, setOutcome] = useState("confirmed_sent");
  const [evidence, setEvidence] = useState("");
  const [providerReference, setProviderReference] = useState("");
  const report = useError();
  const visible = data.actions.filter(
    (a) => filter === "all" || a.status === filter,
  );
  async function decide(
    action: Action,
    decision: "approve" | "reject" | "edit",
  ) {
    setBusy(true);
    try {
      await data.decide(
        action,
        decision,
        decision === "edit" ? edited : undefined,
      );
      setSelected(null);
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page-enter">
      <Heading
        eyebrow="YOU HAVE THE FINAL SAY"
        title="Ready for your go-ahead"
        subtitle="Thoughtful actions, carefully prepared. Review the details before anything leaves your workspace."
      />
      <div className="info-strip">
        <ShieldCheck size={18} />
        <span>
          Every action is checked again after approval. Changed details always
          come back to you.
        </span>
      </div>
      <div className="list-toolbar">
        <div className="tabs">
          {["pending", "approved", "rejected", "all"].map((f) => (
            <button
              className={filter === f ? "selected" : ""}
              onClick={() => setFilter(f)}
              key={f}
            >
              {f === "pending" ? "Needs review" : f}
            </button>
          ))}
        </div>
        <span className="muted">{visible.length} actions</span>
      </div>
      <div className="approval-full-list">
        {visible.map((action) => (
          <motion.article
            initial={{
              opacity: reducedMotion ? 1 : 0,
              y: reducedMotion ? 0 : 5,
            }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.18 }}
            className="panel approval-full"
            key={action.id}
            data-testid={`approval-${action.id}`}
          >
            <div className="approval-full-top">
              <span className="provider-tile">
                <ProviderIcon
                  provider={
                    action.kind === "gmail_reply"
                      ? "gmail"
                      : action.kind === "slack_escalation"
                        ? "slack"
                        : "stripe"
                  }
                  size={25}
                />
              </span>
              <div>
                <h3>
                  {action.kind === "gmail_reply"
                    ? "Send a customer reply"
                    : action.kind === "slack_escalation"
                      ? "Keep your team in the loop"
                      : "Issue a test-mode refund"}
                </h3>
                <span>
                  {String(
                    action.arguments.to ||
                      action.arguments.channel ||
                      action.arguments.payment_id,
                  )}
                </span>
              </div>
              <Badge status={action.status} />
            </div>
            <p className="approval-rationale">{action.rationale}</p>
            <p className="help-text">
              Acting account:{" "}
              {action.acting_account_label ||
                (data.preview
                  ? "Illustrative workspace account"
                  : "Legacy action — fresh review required")}
            </p>
            <div className="approval-content-preview">
              {String(
                action.arguments.body ||
                  action.arguments.text ||
                  `${Number(action.arguments.amount) / 100} ${String(action.arguments.currency).toUpperCase()} · Stripe test mode`,
              )}
            </div>
            <Citations citations={action.citations} preview={data.preview} />
            <div className="approval-full-footer">
              <span>
                <Clock3 size={13} />
                <Time at={action.created_at} />
                <span>· Version {action.version}</span>
              </span>
              {action.status === "uncertain" && (
                <Button
                  variant="secondary"
                  onClick={() => {
                    setReconciliation(action);
                    setEvidence("");
                  }}
                >
                  Review provider outcome
                  <ShieldCheck size={14} />
                </Button>
              )}
              {action.status === "pending" &&
                action.expires_at < Date.now() / 1000 && (
                  <Button
                    variant="secondary"
                    onClick={async () => {
                      try {
                        if (data.preview) {
                          data.notify("Preview: fresh approval requested");
                          return;
                        }
                        await post("/approvals/" + action.id + "/renew", {});
                        data.refresh();
                        data.notify("Fresh version prepared for review");
                      } catch (error) {
                        report(error);
                      }
                    }}
                  >
                    Renew expired draft
                  </Button>
                )}
              {action.status === "pending" &&
                action.expires_at >= Date.now() / 1000 && (
                  <div>
                    <Button
                      variant="ghost"
                      disabled={busy || data.role !== "owner"}
                      onClick={() => void decide(action, "reject")}
                    >
                      <X size={14} />
                      Reject
                    </Button>
                    <Button
                      variant="secondary"
                      onClick={() => {
                        setSelected(action);
                        setEdited({ ...action.arguments });
                      }}
                    >
                      Review & edit
                      <ArrowUpRight size={14} />
                    </Button>
                    <Button
                      disabled={busy || data.role !== "owner"}
                      onClick={() => void decide(action, "approve")}
                    >
                      <Check size={15} />
                      Approve
                    </Button>
                  </div>
                )}
            </div>
          </motion.article>
        ))}
        {!visible.length && (
          <Empty
            icon={<CheckCheck size={27} />}
            title="You’re all caught up"
            description="Your pilot will bring proposed replies, escalations, and refunds here for review."
          />
        )}
      </div>
      <LoadMore collection="approvals" />
      <Modal
        open={!!reconciliation}
        onOpenChange={(open) => !open && setReconciliation(null)}
        title="Verify before another takeoff"
        description="Inspect the actual provider first. Record what happened; an uncertain send must never be retried blindly."
      >
        <div className="form-grid">
          <label>
            Verified provider outcome
            <select
              value={outcome}
              onChange={(e) => setOutcome(e.target.value)}
            >
              <option value="confirmed_sent">
                Provider completed the action
              </option>
              <option value="confirmed_not_sent">
                Provider did not perform the action
              </option>
            </select>
          </label>
          <label>
            Provider reference
            <input
              value={providerReference}
              onChange={(e) => setProviderReference(e.target.value)}
              placeholder="Message ID, timestamp, or refund ID"
            />
          </label>
          <label>
            Reconciliation evidence
            <textarea
              rows={4}
              value={evidence}
              onChange={(e) => setEvidence(e.target.value)}
              placeholder="Describe what you inspected and how you verified the outcome."
            />
          </label>
        </div>
        <div className="modal-footer">
          <Button variant="secondary" onClick={() => setReconciliation(null)}>
            Cancel
          </Button>
          <Button
            disabled={
              evidence.trim().length < 10 || busy || data.role !== "owner"
            }
            onClick={async () => {
              if (!reconciliation) return;
              setBusy(true);
              try {
                if (!data.preview)
                  await post("/approvals/" + reconciliation.id + "/reconcile", {
                    outcome,
                    evidence,
                    provider_reference: providerReference,
                  });
                data.refresh();
                data.notify(
                  "Provider outcome recorded. Unsent actions require fresh approval.",
                );
                setReconciliation(null);
              } catch (error) {
                report(error);
              } finally {
                setBusy(false);
              }
            }}
          >
            Record verified outcome
            <Check size={14} />
          </Button>
        </div>
      </Modal>
      <Modal
        open={!!selected}
        onOpenChange={(open) => !open && setSelected(null)}
        title="Make it sound like you"
        description="Edits create a new version. Save, then approve the revised action."
        wide
      >
        {selected && (
          <>
            <div className="form-grid">
              {Object.entries(edited).map(([key, value]) => (
                <label key={key}>
                  {key.replaceAll("_", " ")}
                  {["body", "text"].includes(key) ? (
                    <textarea
                      aria-label={key}
                      rows={10}
                      value={String(value)}
                      onChange={(e) =>
                        setEdited((previous) => ({
                          ...previous,
                          [key]: e.target.value,
                        }))
                      }
                    />
                  ) : (
                    <input
                      value={value}
                      type={typeof value === "number" ? "number" : "text"}
                      readOnly={[
                        "thread_id",
                        "to",
                        "payment_id",
                        "channel",
                        "currency",
                      ].includes(key)}
                      onChange={(e) =>
                        setEdited((previous) => ({
                          ...previous,
                          [key]:
                            typeof value === "number"
                              ? Number(e.target.value)
                              : e.target.value,
                        }))
                      }
                    />
                  )}
                </label>
              ))}
            </div>
            <div className="modal-footer">
              <Button variant="secondary" onClick={() => setSelected(null)}>
                Cancel
              </Button>
              <Button
                disabled={busy || data.role !== "owner"}
                onClick={() => void decide(selected, "edit")}
              >
                Save revised draft
                <Check size={14} />
              </Button>
            </div>
          </>
        )}
      </Modal>
    </div>
  );
}
