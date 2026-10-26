import {
  ArrowUpRight,
  Check,
  ChevronDown,
  Command,
  ExternalLink,
  LoaderCircle,
  Mail,
  MessageSquare,
  X,
} from "lucide-react";
import * as Dialog from "@radix-ui/react-dialog";
import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { Citation } from "../lib/types";
import { sourceUrl } from "../lib/api";

export function Logo({ small = false }: { small?: boolean }) {
  return (
    <div className={`brand ${small ? "brand-small" : ""}`}>
      <span className="brand-mark">
        <svg viewBox="0 0 24 24" fill="none">
          <path d="m4 12 16-8-7 16-2-7-7-1Z" fill="currentColor" />
          <path
            d="m11 13 9-9"
            stroke="var(--brand-mark-bg)"
            strokeWidth="1.5"
          />
        </svg>
      </span>
      {!small && (
        <span>
          support<span className="brand-light">pilot</span>
          <span className="brand-dot">.</span>
        </span>
      )}
    </div>
  );
}
export function Button({
  children,
  variant = "primary",
  className = "",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
}) {
  return (
    <button className={`button button-${variant} ${className}`} {...props}>
      {children}
    </button>
  );
}
export function Badge({
  status,
  children,
}: {
  status: string;
  children?: ReactNode;
}) {
  const good = [
    "active",
    "ready",
    "completed",
    "resolved",
    "executed",
  ].includes(status);
  const bad = [
    "failed",
    "dead_letter",
    "rejected",
    "expired",
    "uncertain",
    "needs_attention",
  ].includes(status);
  const warm = [
    "pending",
    "awaiting_approval",
    "waiting_quota",
    "retrying",
  ].includes(status);
  return (
    <span
      className={`badge ${good ? "badge-good" : bad ? "badge-bad" : warm ? "badge-warm" : "badge-neutral"}`}
    >
      <span
        className={status === "running" ? "status-dot pulse" : "status-dot"}
      />
      {children || status.replaceAll("_", " ")}
    </span>
  );
}
export function ProviderIcon({
  provider,
  size = 20,
}: {
  provider: string;
  size?: number;
}) {
  if (provider === "gmail")
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" aria-label="Gmail">
        <path d="M3 6v13h4V9l5 4 5-4v10h4V6l-3 1-6 4-6-4Z" fill="#4285f4" />
        <path d="m3 6 9 7 9-7-2-3-7 5-7-5Z" fill="#ea4335" />
        <path d="M17 9v10h4V6Z" fill="#34a853" />
        <path d="M3 6v13h4V9Z" fill="#c5221f" />
        <path d="m17 5 2-2 2 3-4 3Z" fill="#fbbc04" />
      </svg>
    );
  if (provider === "googledrive")
    return (
      <svg
        width={size}
        height={size}
        viewBox="0 0 24 24"
        aria-label="Google Drive"
      >
        <path d="m9 2 6 0 9 16-6 0Z" fill="#fbbc04" />
        <path d="M9 2 0 18l3 5 9-16Z" fill="#34a853" />
        <path d="M3 23h18l3-5H6Z" fill="#4285f4" />
      </svg>
    );
  if (provider === "slack")
    return (
      <svg width={size} height={size} viewBox="0 0 24 24" aria-label="Slack">
        <g strokeWidth="4" strokeLinecap="round">
          <path d="M9 3v9M3 9h2" stroke="#36c5f0" />
          <path d="M21 9h-9M15 3v2" stroke="#2eb67d" />
          <path d="M15 21v-9M21 15h-2" stroke="#ecb22e" />
          <path d="M3 15h9M9 21v-2" stroke="#e01e5a" />
        </g>
      </svg>
    );
  return (
    <span className="stripe-icon" style={{ width: size, height: size }}>
      s
    </span>
  );
}
export function Avatar({
  name,
  size = "normal",
}: {
  name: string;
  size?: "small" | "normal";
}) {
  const hue = [...name].reduce((sum, c) => sum + c.charCodeAt(0), 0) % 360;
  const display = name
    .split("@")[0]
    .replaceAll(".", " ")
    .split(" ")
    .slice(0, 2)
    .map((s) => s[0])
    .join("")
    .toUpperCase();
  return (
    <span
      className={`avatar ${size === "small" ? "avatar-small" : ""}`}
      style={{ "--avatar-hue": hue } as React.CSSProperties}
    >
      {display}
    </span>
  );
}
export function SectionHeading({
  title,
  eyebrow,
  children,
}: {
  title: string;
  eyebrow?: string;
  children?: ReactNode;
}) {
  return (
    <div className="section-heading">
      <div>
        {eyebrow && <span className="eyebrow">{eyebrow}</span>}
        <h2>{title}</h2>
      </div>
      <div className="section-actions">{children}</div>
    </div>
  );
}
export function Modal({
  open,
  onOpenChange,
  title,
  description,
  children,
  wide = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children: ReactNode;
  wide?: boolean;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="modal-overlay" />
        <Dialog.Content className={`modal ${wide ? "modal-wide" : ""}`}>
          <div className="modal-heading">
            <div>
              <Dialog.Title>{title}</Dialog.Title>
              <Dialog.Description>
                {description || "Review the details below."}
              </Dialog.Description>
            </div>
            <Dialog.Close className="icon-button" aria-label="Close dialog">
              <X size={18} />
            </Dialog.Close>
          </div>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
export function Citations({
  citations,
  preview = false,
}: {
  citations: Citation[];
  preview?: boolean;
}) {
  if (!citations.length) return null;
  return (
    <div className="citations">
      <span className="field-label">GROUNDED IN YOUR KNOWLEDGE</span>
      {citations.map((c) => (
        <a
          key={c.chunk_id}
          href={preview ? undefined : sourceUrl(c.document_id, c.version)}
          target={preview ? undefined : "_blank"}
          rel="noreferrer"
          className="citation"
        >
          <span className="citation-number">{c.page}</span>
          <span>
            <strong>{c.name}</strong>
            <small>
              Page {c.page} · Version {c.version}
            </small>
          </span>
          <ExternalLink size={14} />
        </a>
      ))}
    </div>
  );
}
export function Empty({
  icon,
  title,
  description,
  children,
}: {
  icon?: ReactNode;
  title: string;
  description: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-icon">{icon || <MessageSquare size={24} />}</div>
      <h3>{title}</h3>
      <p>{description}</p>
      {children}
    </div>
  );
}
export function Loading() {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={22} />
      <span>Bringing your workspace together…</span>
    </div>
  );
}
export function Time({ at }: { at: number }) {
  const mins = Math.max(1, Math.floor((Date.now() / 1000 - at) / 60));
  return (
    <time
      dateTime={new Date(at * 1000).toISOString()}
      title={new Date(at * 1000).toLocaleString()}
    >
      {mins < 60
        ? `${mins}m ago`
        : mins < 1440
          ? `${Math.floor(mins / 60)}h ago`
          : `${Math.floor(mins / 1440)}d ago`}
    </time>
  );
}
export { ArrowUpRight, Check, ChevronDown, Command, Mail };
