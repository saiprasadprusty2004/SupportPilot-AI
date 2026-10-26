import { useEffect, useRef, useState } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";

import {
  ArrowLeft,
  Check,
  ChevronRight,
  Clock3,
  GitBranch,
  LoaderCircle,
  RefreshCw,
} from "lucide-react";
import {
  Badge,
  Button,
  Citations,
  Empty,
  SectionHeading,
  Time,
} from "../components/ui";
import { useWorkspace } from "../lib/workspace";
import { api, eventUrl, post } from "../lib/api";
import { previewEvents } from "../lib/fixtures";
import type { Event, Page, Run } from "../lib/types";

import { Heading, LoadMore } from "./shared";
export default function RunsPage() {
  const data = useWorkspace();
  const { runId } = useParams();
  const navigate = useNavigate();
  const [filter, setFilter] = useState("all");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [streamEvents, setStreamEvents] = useState<Event[]>([]);
  const runQ = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api<Run>("/runs/" + runId),
    enabled: !!runId && !data.preview,
    refetchInterval: 5000,
  });
  const eventsQ = useQuery({
    queryKey: ["events", runId],
    queryFn: () => api<Page<Event>>("/runs/" + runId + "/events"),
    enabled: !!runId && !data.preview,
  });
  const jobsQ = useQuery({
    queryKey: ["run-jobs", runId],
    queryFn: () =>
      api<{
        items: {
          id: string;
          kind: string;
          status: string;
          history: {
            id: string;
            number: number;
            status: string;
            error: string | null;
          }[];
        }[];
      }>(`/runs/${runId}/jobs`),
    enabled: !!runId && !data.preview,
    refetchInterval: 5000,
  });
  const selected = data.preview
    ? data.runs.find((r) => r.id === runId)
    : runQ.data;
  useEffect(() => {
    setStreamEvents([]);
    if (!runId || data.preview) return;
    const source = new EventSource(eventUrl(runId), { withCredentials: true });
    let timer: ReturnType<typeof setTimeout> | undefined;
    let batch: Event[] = [];
    const handle = (event: MessageEvent) => {
      batch.push(JSON.parse(event.data) as Event);
      if (!timer)
        timer = setTimeout(() => {
          const additions = batch;
          batch = [];
          timer = undefined;
          setStreamEvents((previous) => {
            const unique = new Map(
              [...previous, ...additions].map((e) => [e.sequence, e]),
            );
            return [...unique.values()].sort((a, b) => a.sequence - b.sequence);
          });
        }, 120);
    };
    source.addEventListener("trace", handle);
    return () => {
      source.close();
      if (timer) clearTimeout(timer);
    };
  }, [runId, data.preview]);
  const events = data.preview
    ? previewEvents
    : [
        ...new Map(
          [...(eventsQ.data?.items || []), ...streamEvents].map((e) => [
            e.sequence,
            e,
          ]),
        ).values(),
      ].sort((a, b) => a.sequence - b.sequence);
  const traceScroll = useRef<HTMLDivElement>(null);
  const traceRows = useVirtualizer({
    count: events.length,
    getScrollElement: () => traceScroll.current,
    estimateSize: () => 103,
    overscan: 6,
    enabled: !!runId,
    getItemKey: (index) => events[index].sequence,
  });
  if (runId)
    return (
      <div className="page-enter">
        <button
          className="text-button muted back-link"
          onClick={() => navigate((data.preview ? "/preview" : "") + "/runs")}
        >
          <ArrowLeft size={14} />
          All activity
        </button>
        <Heading
          eyebrow="EVERY STEP, IN THE OPEN"
          title="The story behind the answer"
          subtitle={selected?.prompt || "Loading your execution…"}
        >
          {selected && <Badge status={selected.status} />}
        </Heading>
        {!data.preview && !!jobsQ.data?.items.length && (
          <section className="panel delivery-attempts">
            <SectionHeading title="Delivery attempts" />
            {jobsQ.data.items.map((job) => (
              <details key={job.id}>
                <summary>
                  {job.kind} · {job.history.length} recorded attempts ·{" "}
                  {job.status}
                </summary>
                {job.history.map((attempt) => (
                  <p key={attempt.id}>
                    Attempt {attempt.number} · {attempt.status}
                    {attempt.error ? ` — ${attempt.error}` : ""}
                  </p>
                ))}
              </details>
            ))}
          </section>
        )}
        <div className="run-detail-grid">
          <section className="panel trace-panel">
            <SectionHeading title="Execution timeline">
              <span className="subtle-count">{events.length} events</span>
            </SectionHeading>
            <div className="timeline-viewport" ref={traceScroll}>
              <div
                className="timeline"
                style={{
                  height: traceRows.getTotalSize(),
                  position: "relative",
                  padding: 0,
                }}
              >
                {traceRows.getVirtualItems().map((row) => {
                  const event = events[row.index];
                  return (
                    <div
                      className={`timeline-item ${event.status === "failed" ? "timeline-failed" : ""}`}
                      key={event.sequence}
                      ref={traceRows.measureElement}
                      data-index={row.index}
                      style={{
                        position: "absolute",
                        top: 0,
                        left: 24,
                        right: 24,
                        transform: `translateY(${row.start}px)`,
                      }}
                    >
                      <span className="timeline-node">
                        {event.status === "completed" ? (
                          <Check size={13} />
                        ) : event.status === "running" ? (
                          <LoaderCircle className="spin" size={13} />
                        ) : (
                          <Clock3 size={13} />
                        )}
                      </span>
                      <button
                        className="timeline-content"
                        onClick={() =>
                          setExpanded(expanded === event.id ? null : event.id)
                        }
                      >
                        <div>
                          <strong>{event.node.replaceAll("_", " ")}</strong>
                          <Badge status={event.status} />
                          <span>
                            {event.duration_ms != null
                              ? event.duration_ms + " ms"
                              : ""}
                          </span>
                          <ChevronRight
                            size={14}
                            className={expanded === event.id ? "rotated" : ""}
                          />
                        </div>
                        <small>
                          <Time at={event.created_at} />
                        </small>
                        {expanded === event.id && (
                          <pre>{JSON.stringify(event.data, null, 2)}</pre>
                        )}
                      </button>
                    </div>
                  );
                })}
              </div>
            </div>
          </section>
          <aside>
            <section className="panel run-summary">
              <SectionHeading title="Run summary" />
              {selected && (
                <>
                  <label>Status</label>
                  <Badge status={selected.status} />
                  <label>Current step</label>
                  <strong className="capitalize">
                    {selected.current_node}
                  </strong>
                  <label>Result</label>
                  <p>
                    {selected.result ||
                      "Your pilot is working through the task. You can follow every step in the timeline."}
                  </p>
                  {selected.error && (
                    <div className="field-error">{selected.error}</div>
                  )}
                  <Citations
                    citations={selected.citations}
                    preview={data.preview}
                  />
                  {["failed", "waiting_quota"].includes(selected.status) && (
                    <Button
                      variant="secondary"
                      onClick={async () => {
                        if (data.preview) {
                          data.notify("Preview: recovery requested");
                          return;
                        }
                        try {
                          await post("/runs/" + selected.id + "/retry", {});
                          data.refresh();
                          data.notify("Recovery queued");
                        } catch (e) {
                          data.notify((e as Error).message, "error");
                        }
                      }}
                    >
                      <RefreshCw size={14} />
                      Retry recoverable work
                    </Button>
                  )}
                </>
              )}
            </section>
          </aside>
        </div>
      </div>
    );
  const visible = data.runs.filter(
    (r) => filter === "all" || r.status === filter,
  );
  return (
    <div className="page-enter">
      <Heading
        eyebrow="A CLEAR VIEW OF EVERYTHING"
        title="Good work leaves a trail"
        subtitle="Follow every task, inspect every step, and pick up right where you left off."
      />
      <div className="list-toolbar">
        <div className="tabs">
          {["all", "running", "awaiting_approval", "completed", "failed"].map(
            (f) => (
              <button
                key={f}
                className={filter === f ? "selected" : ""}
                onClick={() => setFilter(f)}
              >
                {f === "all"
                  ? "All activity"
                  : f === "awaiting_approval"
                    ? "Needs review"
                    : f}
              </button>
            ),
          )}
        </div>
        <Button variant="ghost" onClick={data.refresh}>
          <RefreshCw size={14} />
          Refresh
        </Button>
      </div>
      <div className="panel run-list">
        {visible.map((run) => (
          <button
            key={run.id}
            className="run-list-row"
            onClick={() =>
              navigate((data.preview ? "/preview" : "") + "/runs/" + run.id)
            }
          >
            <span
              className={`workflow-icon ${run.status === "awaiting_approval" ? "violet" : ""}`}
            >
              <GitBranch size={20} />
            </span>
            <div>
              <strong>{run.prompt}</strong>
              <small>
                <span className="capitalize">{run.current_node}</span>
                <span>·</span>
                <Time at={run.created_at} />
              </small>
            </div>
            <Badge status={run.status} />
            <ChevronRight size={16} />
          </button>
        ))}
        {!visible.length && (
          <Empty
            icon={<GitBranch size={25} />}
            title="Your next task starts a story"
            description="Create a task in Agent Chat or prepare a reply from your inbox."
          />
        )}
      </div>
      <LoadMore collection="runs" />
    </div>
  );
}
