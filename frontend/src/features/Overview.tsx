import {
  ArrowDown,
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  CheckCheck,
  ChevronRight,
  Clock3,
  Ellipsis,
  Inbox,
  Mail,
  Plus,
  ShieldCheck,
  Sparkles,
  Workflow,
  Zap,
} from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "../lib/api";
import Constellation from "../components/Constellation";
import {
  Avatar,
  Badge,
  Button,
  ProviderIcon,
  SectionHeading,
  Time,
} from "../components/ui";
import { useWorkspace } from "../lib/workspace";

export default function Overview() {
  const data = useWorkspace();
  const dashboard = useQuery({
    queryKey: ["dashboard"],
    queryFn: () =>
      api<{
        tickets: number;
        resolved_tickets: number;
        pending_approvals: number;
      }>("/dashboard"),
    enabled: !data.preview,
    refetchInterval: 5000,
  });
  const navigate = useNavigate();
  const base = data.preview ? "/preview" : "";
  const pending = data.actions.filter((a) => a.status === "pending");
  const active = data.runs.filter((r) =>
    ["running", "queued", "retrying"].includes(r.status),
  );
  const finished = data.runs.filter((r) => r.status === "completed");
  const count = data.preview
    ? { tickets: 128, resolved: 94, saved: "12.4", approval: pending.length }
    : {
        tickets: dashboard.data?.tickets ?? data.tickets.length,
        resolved: dashboard.data?.resolved_tickets ?? finished.length,
        saved: ((dashboard.data?.resolved_tickets ?? 0) / 12).toFixed(1),
        approval: dashboard.data?.pending_approvals ?? pending.length,
      };
  return (
    <div className="overview">
      <div className="page-heading">
        <div>
          <div className="welcome-line">
            <span className="greeting-dot" /> YOUR WORKSPACE, AT A GLANCE
          </div>
          <h1>
            A little less busywork.
            <br className="mobile-break" /> A lot more impact
            <span className="mint">.</span>
          </h1>
          <p>
            Good to see you, {data.session.user.name.split(" ")[0]}. Here’s what
            your pilot is working on.
          </p>
        </div>
        <Button onClick={() => navigate(base + "/chat")}>
          <Plus size={16} />
          New task<span className="keycap">N</span>
        </Button>
      </div>
      <section className="hero-panel">
        <div className="hero-copy">
          <div className="hero-eyebrow">
            <span className="status-dot" /> YOUR AI TEAMMATE IS READY
          </div>
          <h2>
            Your support,
            <br />
            on autopilot<span>.</span>
          </h2>
          <p>
            From the first question to the final reply.
            <br />
            Connected tools. Trusted answers. You in control.
          </p>
          <div className="hero-buttons">
            <Button onClick={() => navigate(base + "/chat")}>
              <Sparkles size={15} />
              Ask your agent
              <ArrowUpRight size={15} />
            </Button>
            <button
              className="text-button"
              onClick={() => navigate(base + "/runs")}
            >
              View activity
              <ArrowRight size={14} />
            </button>
          </div>
          <div className="hero-footnote">
            <ShieldCheck size={13} />
            <span>Every important action starts with your approval.</span>
          </div>
        </div>
        <Constellation
          graphics={data.graphics}
          connections={data.connections}
          active={active.length > 0}
        />
        <div className="hero-grid" />
      </section>
      <div className="stats-grid">
        <Stat
          icon={<Inbox size={17} />}
          label="Tickets received"
          value={String(count.tickets)}
          change={data.preview ? "+18.5%" : "This workspace"}
          trend="up"
          note={data.preview ? "vs. last week" : "Synced tickets"}
          path={() => navigate(base + "/inbox")}
          points="0,32 12,27 25,30 37,14 48,19 59,12 72,17 84,5 100,8"
        />
        <Stat
          icon={<CheckCheck size={17} />}
          label="Resolved by your pilot"
          value={String(count.resolved)}
          change={data.preview ? "73.4%" : "Completed"}
          trend="up"
          note="with your approval"
          path={() => navigate(base + "/runs")}
          points="0,32 12,32 25,24 37,27 48,16 59,18 72,8 84,12 100,3"
        />
        <Stat
          icon={<Clock3 size={17} />}
          label="Time given back"
          value={count.saved}
          suffix="hrs"
          change={data.preview ? "+3.2 hrs" : "Estimate"}
          trend="up"
          note="estimated time saved"
          path={() => navigate(base + "/runs")}
          points="0,34 12,26 25,30 37,21 48,25 59,14 72,18 84,9 100,5"
        />
        <Stat
          icon={<ShieldCheck size={17} />}
          label="Needs your approval"
          value={String(count.approval).padStart(2, "0")}
          change="You're in control"
          trend="neutral"
          note="ready when you are"
          path={() => navigate(base + "/approvals")}
          points="0,20 12,20 25,12 37,12 48,26 59,26 72,16 84,16 100,16"
        />
      </div>
      <div className="dashboard-columns">
        <section className="panel workflows-panel">
          <SectionHeading title="Your pilot in motion">
            <span className="subtle-count">{active.length} active</span>
            <button
              className="text-button muted"
              onClick={() => navigate(base + "/runs")}
            >
              All activity
              <ArrowUpRight size={14} />
            </button>
          </SectionHeading>
          <div className="workflow-list">
            {data.runs.slice(0, 3).map((run, i) => (
              <button
                className="workflow-row"
                key={run.id}
                onClick={() => navigate(base + "/runs/" + run.id)}
              >
                <span
                  className={`workflow-icon ${i === 1 ? "violet" : i === 2 ? "blue" : ""}`}
                >
                  {i === 1 ? (
                    <ShieldCheck size={19} />
                  ) : i === 2 ? (
                    <CheckCheck size={19} />
                  ) : (
                    <Workflow size={19} />
                  )}
                </span>
                <div className="workflow-info">
                  <strong>{run.prompt}</strong>
                  <div>
                    <ProviderIcon provider="gmail" size={12} />
                    <span>Gmail</span>
                    <span className="separator-dot">·</span>
                    <span>
                      {run.status === "running"
                        ? "Searching your knowledge base"
                        : run.status === "awaiting_approval"
                          ? "Draft ready for your review"
                          : "Reply approved and sent"}
                    </span>
                  </div>
                </div>
                <div className="workflow-meta">
                  <Badge status={run.status}>
                    {run.status === "awaiting_approval"
                      ? "Needs review"
                      : run.status === "running"
                        ? "In progress"
                        : undefined}
                  </Badge>
                  <Time at={run.created_at} />
                </div>
                <ChevronRight size={15} className="muted" />
              </button>
            ))}
            {!data.runs.length && (
              <div className="compact-empty">
                Your first task starts a new chapter.{" "}
                <button
                  className="text-button"
                  onClick={() => navigate(base + "/chat")}
                >
                  Create a task
                  <ArrowRight size={14} />
                </button>
              </div>
            )}
          </div>
          <div className="panel-footer">
            <span className="small-live-dot" />
            <span>Every step logged. Every action accountable.</span>
            <ShieldCheck size={13} />
          </div>
        </section>
        <section className="panel connections-panel">
          <SectionHeading title="Connected & ready">
            <button
              className="icon-button"
              onClick={() => navigate(base + "/connections")}
              aria-label="Manage connections"
            >
              <Ellipsis size={18} />
            </button>
          </SectionHeading>
          <div className="connection-mini-list">
            {["gmail", "slack", "googledrive"].map((p) => {
              const connection = data.connections.find((c) => c.provider === p);
              return (
                <button
                  className="connection-mini"
                  key={p}
                  onClick={() => navigate(base + "/connections")}
                >
                  <span className="provider-tile">
                    <ProviderIcon provider={p} size={22} />
                  </span>
                  <span className="connection-mini-info">
                    <strong>
                      {p === "googledrive"
                        ? "Google Drive"
                        : p === "gmail"
                          ? "Gmail"
                          : "Slack"}
                    </strong>
                    <small>
                      {p === "gmail"
                        ? "Your support inbox"
                        : p === "slack"
                          ? "Keep your team in the loop"
                          : "Your source of truth"}
                    </small>
                  </span>
                  <span
                    className={`connection-state ${connection?.status === "active" ? "" : "off"}`}
                  >
                    <span className="status-dot" />
                    {connection?.status === "active" ? "Connected" : "Connect"}
                  </span>
                </button>
              );
            })}
          </div>
          <div className="knowledge-strip">
            <span className="knowledge-icon">
              <BookOpen size={16} />
            </span>
            <span>
              <strong>{data.documents.length} documents</strong> in your
              knowledge base
            </span>
            <button
              className="icon-button"
              aria-label="Open knowledge base"
              onClick={() => navigate(base + "/knowledge")}
            >
              <ArrowRight size={15} />
            </button>
          </div>
        </section>
      </div>
      <section className="approvals-overview">
        <SectionHeading title="A quick look before takeoff">
          <span className="subtle-count">{pending.length} pending</span>
          <button
            className="text-button muted"
            onClick={() => navigate(base + "/approvals")}
          >
            Review all
            <ArrowUpRight size={14} />
          </button>
        </SectionHeading>
        <div className="approval-cards">
          {pending.slice(0, 2).map((action) => (
            <button
              className="approval-card"
              key={action.id}
              onClick={() => navigate(base + "/approvals")}
            >
              <span
                className={`approval-card-icon ${action.kind === "stripe_refund" ? "violet" : ""}`}
              >
                {action.kind === "stripe_refund" ? (
                  <ProviderIcon provider="stripe" size={22} />
                ) : (
                  <Mail size={21} />
                )}
              </span>
              <div>
                <div className="approval-card-top">
                  <strong>
                    {action.kind === "stripe_refund"
                      ? "A refund, ready for your go-ahead"
                      : "A thoughtful reply, ready to send"}
                  </strong>
                  <span className="review-dot" />
                </div>
                <p>
                  {action.kind === "stripe_refund"
                    ? `$${(Number(action.arguments.amount) / 100).toFixed(2)} test refund · Customer request`
                    : `To ${action.arguments.to}`}
                </p>
                <div className="approval-card-bottom">
                  <span>
                    <ShieldCheck size={12} /> Human approval required
                  </span>
                  <span>
                    Review
                    <ArrowUpRight size={13} />
                  </span>
                </div>
              </div>
            </button>
          ))}
          {!pending.length && (
            <div className="all-clear">
              <CheckCheck size={22} />
              <span>
                You’re all caught up. Your pilot will bring the next decision
                here.
              </span>
            </div>
          )}
        </div>
      </section>
      <section className="recent-tickets panel">
        <SectionHeading title="Fresh from your inbox">
          <button
            className="text-button muted"
            onClick={() => navigate(base + "/inbox")}
          >
            Open inbox
            <ArrowUpRight size={14} />
          </button>
        </SectionHeading>
        <div className="ticket-table">
          <div className="ticket-table-head">
            <span>CUSTOMER</span>
            <span>SUBJECT</span>
            <span>STATUS</span>
            <span>
              RECEIVED
              <ArrowDown size={11} />
            </span>
          </div>
          {data.tickets.slice(0, 3).map((ticket) => (
            <button
              className="ticket-table-row"
              key={ticket.id}
              onClick={() => navigate(base + "/inbox?ticket=" + ticket.id)}
            >
              <span className="customer-cell">
                <Avatar name={ticket.sender} size="small" />
                <span>
                  <strong>
                    {ticket.sender.split("@")[0].replaceAll(".", " ")}
                  </strong>
                  <small>{ticket.sender}</small>
                </span>
              </span>
              <span className="ticket-subject">{ticket.subject}</span>
              <span>
                <Badge status={ticket.status} />
              </span>
              <Time at={ticket.created_at} />
            </button>
          ))}
        </div>
      </section>
      <footer className="workspace-footer">
        <span>
          <LogoMark /> Thoughtful support. Powered by you.
        </span>
        <span>
          <span className="small-live-dot" />
          {data.preview ? "All systems operational" : "Workspace connected"}
          <span className="footer-divider" />
          SupportPilot v0.1
        </span>
      </footer>
    </div>
  );
}
function LogoMark() {
  return <Zap size={12} />;
}
function Stat({
  icon,
  label,
  value,
  suffix,
  change,
  trend,
  note,
  points,
  path,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  suffix?: string;
  change: string;
  trend: string;
  note: string;
  points: string;
  path: () => void;
}) {
  const { preview } = useWorkspace();
  return (
    <button
      className={`stat-card ${trend === "neutral" ? "stat-warm" : ""}`}
      onClick={path}
    >
      <div className="stat-top">
        <span>{label}</span>
        <span className="stat-icon">{icon}</span>
      </div>
      <div className="stat-middle">
        <span className="stat-value">
          {value}
          <small>{suffix}</small>
        </span>
        {preview && (
          <svg viewBox="0 0 100 44" className="sparkline" aria-hidden="true">
            <defs>
              <linearGradient id={"fill-" + value} x1="0" y1="0" x2="0" y2="1">
                <stop stopColor="currentColor" stopOpacity=".14" />
                <stop offset="1" stopColor="currentColor" stopOpacity="0" />
              </linearGradient>
            </defs>
            <polygon
              points={`0,44 ${points} 100,44`}
              fill={`url(#fill-${value})`}
            />
            <polyline
              points={points}
              fill="none"
              stroke="currentColor"
              strokeWidth="1.7"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        )}
      </div>
      <div className="stat-bottom">
        <span>
          {trend !== "neutral" && <ArrowUpRight size={12} />} {change}
        </span>
        <span>{note}</span>
      </div>
    </button>
  );
}
