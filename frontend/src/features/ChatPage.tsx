import { useEffect, useState } from "react";

import { useQuery } from "@tanstack/react-query";

import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  Inbox,
  LoaderCircle,
  ShieldCheck,
  Sparkles,
  Zap,
} from "lucide-react";
import { Avatar, Citations } from "../components/ui";
import { useWorkspace } from "../lib/workspace";
import { api } from "../lib/api";

import type { Citation, Run } from "../lib/types";

import { Heading, useError } from "./shared";
export default function ChatPage() {
  const data = useWorkspace();
  const [prompt, setPrompt] = useState("");
  const [history, setHistory] = useState<
    { role: string; content: string; citations?: Citation[] }[]
  >([]);
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const report = useError();
  const runQ = useQuery({
    queryKey: ["chat-run", active],
    queryFn: () => api<Run>("/runs/" + active),
    enabled: !!active && !data.preview,
    refetchInterval: (query) =>
      [
        "completed",
        "failed",
        "awaiting_approval",
        "rejected",
        "needs_attention",
      ].includes(query.state.data?.status || "")
        ? false
        : 2000,
  });
  useEffect(() => {
    const run = runQ.data;
    if (
      run &&
      ["completed", "failed", "awaiting_approval", "needs_attention"].includes(
        run.status,
      )
    ) {
      setHistory((h) => [
        ...h,
        {
          role: "agent",
          content:
            run.result ||
            run.error ||
            "Your draft is ready. Open Approvals to review the proposed action.",
          citations: run.citations,
        },
      ]);
      setActive(null);
      setBusy(false);
    }
  }, [runQ.data]);
  async function submit(value = prompt) {
    if (!value.trim() || busy) return;
    setPrompt("");
    setHistory((h) => [...h, { role: "user", content: value }]);
    setBusy(true);
    try {
      const run = await data.startRun(value);
      if (data.preview) {
        setHistory((h) => [...h, { role: "agent", content: run.result || "" }]);
        setBusy(false);
      } else setActive(run.id);
    } catch (e) {
      report(e);
      setBusy(false);
    }
  }
  return (
    <div className="chat-page page-enter">
      <Heading
        eyebrow="YOUR THOUGHTFUL AI TEAMMATE"
        title="A little help goes a long way"
        subtitle="Ask a question, find an answer, or put your pilot to work."
      />
      <div className="chat-workspace">
        {!history.length ? (
          <div className="chat-welcome">
            <div className="chat-orb">
              <Sparkles size={35} strokeWidth={1.3} />
            </div>
            <span className="eyebrow">CONNECTED TO YOUR WORKSPACE</span>
            <h2>What can I take off your plate?</h2>
            <p>I’ll bring the knowledge. You bring the final say.</p>
            <div className="suggestion-grid">
              {[
                {
                  icon: BookOpen,
                  title: "Find a product answer",
                  text: "What does our documentation say about team invitations?",
                },
                {
                  icon: Inbox,
                  title: "Summarize my support queue",
                  text: "Summarize the support tasks I should focus on today.",
                },
                {
                  icon: ShieldCheck,
                  title: "Review our refund policy",
                  text: "Explain our refund policy and cite the original documentation.",
                },
                {
                  icon: Zap,
                  title: "Make a helpful response",
                  text: "Find our getting started steps so I can help a new customer.",
                },
              ].map((s) => (
                <button key={s.title} onClick={() => void submit(s.text)}>
                  <s.icon size={19} />
                  <strong>{s.title}</strong>
                  <span>
                    {s.text}
                    <ArrowUpRight size={14} />
                  </span>
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="chat-history">
            {history.map((message, i) => (
              <div className={`chat-message chat-${message.role}`} key={i}>
                <span
                  className={
                    message.role === "agent" ? "agent-icon" : "user-chat-icon"
                  }
                >
                  {message.role === "agent" ? (
                    <Sparkles size={18} />
                  ) : (
                    <Avatar name={data.session.user.name} size="small" />
                  )}
                </span>
                <div>
                  <strong>
                    {message.role === "agent"
                      ? "SupportPilot"
                      : data.session.user.name}
                    <small>
                      {message.role === "agent" ? "YOUR AI TEAMMATE" : ""}
                    </small>
                  </strong>
                  <p>{message.content}</p>
                  <Citations
                    citations={message.citations || []}
                    preview={data.preview}
                  />
                </div>
              </div>
            ))}
            {busy && (
              <div className="agent-thinking">
                <Sparkles size={16} className="pulse" />
                Your pilot is connecting the dots…
              </div>
            )}
          </div>
        )}
        <div className="chat-composer-wrap">
          <form
            className="chat-composer"
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <textarea
              aria-label="Message your agent"
              placeholder="Ask your pilot anything about your workspace…"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void submit();
                }
              }}
              rows={2}
              maxLength={8000}
            />
            <div>
              <span>
                <ShieldCheck size={12} />
                You approve. Your pilot acts.
              </span>
              <button
                type="submit"
                aria-label="Send message"
                disabled={!prompt.trim() || busy}
              >
                {busy ? (
                  <LoaderCircle size={17} className="spin" />
                ) : (
                  <ArrowRight size={18} />
                )}
              </button>
            </div>
          </form>
          <small>
            Grounded in your documents. Important actions always need your
            approval.
          </small>
        </div>
      </div>
    </div>
  );
}
