import { CheckCircle, Info, SpinnerGap, Warning } from "@phosphor-icons/react";

export function StatusPill({ children, tone = "neutral" }) {
  return <span className={`status-pill status-pill--${tone}`}>{children}</span>;
}

export function SectionHeader({ eyebrow, title, description, action }) {
  return (
    <header className="section-header">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h1>{title}</h1>
        {description && <p className="section-description">{description}</p>}
      </div>
      {action}
    </header>
  );
}

export function LoadingPanel({ label = "Loading authorized case data…" }) {
  return <div className="state-panel"><SpinnerGap className="spin" size={24} /><strong>{label}</strong></div>;
}

export function EmptyPanel({ title, detail, action }) {
  return <div className="state-panel state-panel--empty"><Info size={24} /><strong>{title}</strong><p>{detail}</p>{action}</div>;
}

export function ErrorPanel({ error, onRetry }) {
  return <div className="state-panel state-panel--error" role="alert"><Warning size={24} /><strong>Unable to load this view</strong><p>{error?.message || String(error)}</p>{onRetry && <button className="button button--dark" onClick={onRetry}>Retry</button>}</div>;
}

export function LiveBadge({ children = "Live case data" }) {
  return <StatusPill tone="safe"><CheckCircle size={13} /> {children}</StatusPill>;
}

export function formatDate(value, withTime = true) {
  if (!value) return "Not available";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("en-IN", {
    day: "2-digit",
    month: "short",
    year: "numeric",
    ...(withTime ? { hour: "2-digit", minute: "2-digit" } : {}),
  }).format(date);
}

export function formatBytes(value = 0) {
  if (value < 1024) return `${value} B`;
  if (value < 1024 ** 2) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 ** 2).toFixed(1)} MB`;
}

export function shortId(value = "") {
  return value.length > 12 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value;
}

export function statusTone(status = "") {
  if (["completed", "confirmed", "corrected", "registered", "reviewed", "analytics_completed"].includes(status)) return "safe";
  if (["failed", "dispatch_failed", "integrity_mismatch", "rejected"].includes(status)) return "danger";
  if (["running", "processing", "started", "projected"].includes(status)) return "blue";
  return "yellow";
}

export function can(user, permission) {
  return Boolean(user?.permissions?.includes(permission));
}
