import { useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Inbox, LoaderCircle, RefreshCw, Search, Sparkles } from "lucide-react";
import {
  Avatar,
  Badge,
  Button,
  Empty,
  Modal,
  ProviderIcon,
  Time,
} from "../components/ui";
import { useWorkspace } from "../lib/workspace";
import { api, post } from "../lib/api";

import { Heading, LoadMore, useError } from "./shared";
export default function InboxPage() {
  const data = useWorkspace();
  const [params, setParams] = useSearchParams();
  const [term, setTerm] = useState("");
  const [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState(false);
  const [paymentOpen, setPaymentOpen] = useState(false);
  const [paymentId, setPaymentId] = useState("");
  const report = useError();
  const navigate = useNavigate();
  const visible = data.tickets.filter(
    (t) =>
      (filter === "all" || t.status === filter) &&
      (t.subject + t.sender).toLowerCase().includes(term.toLowerCase()),
  );
  const selected =
    data.tickets.find((t) => t.id === params.get("ticket")) || visible[0];
  const detail = useQuery({
    queryKey: ["ticket", selected?.id],
    queryFn: () =>
      api<{
        messages: {
          id: string;
          sender: string;
          body: string;
          created_at: number;
        }[];
      }>("/tickets/" + selected!.id),
    enabled: !!selected && !data.preview,
  });
  const messages =
    data.preview && selected
      ? [
          {
            id: "sample",
            sender: selected.sender,
            body:
              selected.preview +
              "\n\nThanks so much for your help!\n" +
              selected.sender.split("@")[0].split(".")[0],
            created_at: selected.created_at,
          },
        ]
      : detail.data?.messages || [];
  const parent = useRef<HTMLDivElement>(null);
  const virtual = useVirtualizer({
    count: visible.length,
    getScrollElement: () => parent.current,
    estimateSize: () => 122,
    overscan: 5,
  });
  async function draft(kind: "reply" | "escalate" | "refund" = "reply") {
    if (!selected) return;
    setBusy(true);
    try {
      const run = await data.startRun(
        kind === "reply"
          ? "Read this support ticket, search product documentation, and prepare a helpful reply."
          : kind === "escalate"
            ? "Escalate this ticket to the approved Slack support channel with a concise summary."
            : "Inspect the explicitly linked Stripe test payment and propose a refund of the remaining refundable amount. Do not execute before approval.",
        selected.id,
      );
      navigate((data.preview ? "/preview" : "") + "/runs/" + run.id);
    } catch (e) {
      report(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="page-enter">
      <Heading
        eyebrow="THE START OF A GREAT CONVERSATION"
        title="Your inbox, a little lighter"
        subtitle="Every customer deserves a thoughtful answer. Your pilot is here to help."
      >
        <Button
          variant="secondary"
          onClick={() => {
            data.refresh();
            data.notify("Inbox refreshed");
          }}
        >
          <RefreshCw size={15} />
          Refresh inbox
        </Button>
      </Heading>
      <div className="inbox-layout panel">
        <div className="inbox-list">
          <div className="inbox-list-toolbar">
            <div className="search-field">
              <Search size={15} />
              <input
                aria-label="Search inbox"
                placeholder="Search conversations"
                value={term}
                onChange={(e) => setTerm(e.target.value)}
              />
            </div>
            <div className="tabs">
              {["all", "open", "resolved"].map((f) => (
                <button
                  key={f}
                  className={filter === f ? "selected" : ""}
                  onClick={() => setFilter(f)}
                >
                  {f === "all" ? "All tickets" : f}
                </button>
              ))}
            </div>
          </div>
          <div className="inbox-scroll" ref={parent}>
            <div
              style={{ height: virtual.getTotalSize(), position: "relative" }}
            >
              {virtual.getVirtualItems().map((item) => {
                const ticket = visible[item.index];
                return (
                  <button
                    key={ticket.id}
                    className={`inbox-ticket ${selected?.id === ticket.id ? "selected" : ""}`}
                    style={{
                      position: "absolute",
                      top: 0,
                      left: 0,
                      width: "100%",
                      height: item.size,
                      transform: `translateY(${item.start}px)`,
                    }}
                    onClick={() => setParams({ ticket: ticket.id })}
                  >
                    <div>
                      <Avatar name={ticket.sender} size="small" />
                      <strong>
                        {ticket.sender.split("@")[0].replaceAll(".", " ")}
                      </strong>
                      <Time at={ticket.created_at} />
                    </div>
                    <h3>{ticket.subject}</h3>
                    <p>{ticket.preview}</p>
                    <Badge status={ticket.status} />
                  </button>
                );
              })}
            </div>
            {!visible.length && (
              <Empty
                icon={<Inbox size={24} />}
                title="A clean slate"
                description="Tickets appear here when your connected Gmail label receives a message."
              />
            )}
          </div>
        </div>
        <div className="conversation">
          {selected ? (
            <>
              <div className="conversation-header">
                <div>
                  <h2>{selected.subject}</h2>
                  <span>
                    <ProviderIcon provider="gmail" size={13} />
                    {selected.sender}
                  </span>
                </div>
                <Badge status={selected.status} />
              </div>
              <div className="conversation-messages">
                {messages.map((message) => (
                  <article className="message" key={message.id}>
                    <div className="message-heading">
                      <Avatar name={message.sender} />
                      <span>
                        <strong>
                          {message.sender.split("@")[0].replaceAll(".", " ")}
                        </strong>
                        <small>{message.sender}</small>
                      </span>
                      <Time at={message.created_at} />
                    </div>
                    <p>{message.body}</p>
                  </article>
                ))}
              </div>
              <div className="draft-assistant">
                <span className="agent-icon">
                  <Sparkles size={19} />
                </span>
                <div>
                  <strong>A little help from your pilot?</strong>
                  <p>Get a draft grounded in your product documentation.</p>
                </div>
                <Button onClick={() => void draft()} disabled={busy}>
                  {busy ? (
                    <LoaderCircle size={14} className="spin" />
                  ) : (
                    <Sparkles size={14} />
                  )}
                  Prepare reply
                </Button>
              </div>
              <div className="ticket-actions">
                <Button
                  variant="secondary"
                  disabled={busy}
                  onClick={() => void draft("escalate")}
                >
                  Propose Slack escalation
                </Button>
                <Button
                  variant="secondary"
                  disabled={busy || !selected.payment_id}
                  onClick={() => void draft("refund")}
                >
                  Propose test refund
                </Button>
                {data.role === "owner" && (
                  <Button
                    variant="ghost"
                    onClick={() => {
                      setPaymentId(selected.payment_id || "");
                      setPaymentOpen(true);
                    }}
                  >
                    {selected.payment_id
                      ? "Change linked payment"
                      : "Link test payment"}
                  </Button>
                )}
                <p className="help-text">
                  {selected.payment_id
                    ? `Linked payment: ${selected.payment_id}. `
                    : "An owner must link a payment before a refund. "}
                  Every outbound action needs owner approval.
                </p>
              </div>
            </>
          ) : (
            <Empty
              title="Your conversations live here"
              description="Connect Gmail and enable support-label sync to get started."
            />
          )}
        </div>
      </div>
      <LoadMore collection="tickets" />
      <Modal
        open={paymentOpen}
        onOpenChange={setPaymentOpen}
        title="Link a Stripe test payment"
        description="Confirm this payment belongs to the selected customer ticket. The server verifies test mode and refundability using your workspace key."
      >
        <label>
          Payment intent ID
          <input
            value={paymentId}
            onChange={(e) => setPaymentId(e.target.value)}
            placeholder="pi_…"
          />
        </label>
        <Button
          disabled={busy || !/^pi_[A-Za-z0-9_]+$/.test(paymentId)}
          onClick={async () => {
            if (!selected) return;
            setBusy(true);
            try {
              if (!data.preview)
                await post(`/tickets/${selected.id}/payment`, {
                  payment_id: paymentId,
                });
              data.refresh();
              setPaymentOpen(false);
              data.notify(
                data.preview
                  ? "Preview: payment link simulated"
                  : "Test payment linked",
              );
            } catch (e) {
              report(e);
            } finally {
              setBusy(false);
            }
          }}
        >
          Confirm payment link
        </Button>
      </Modal>
    </div>
  );
}
