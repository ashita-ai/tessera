import { cn } from "@/lib/utils";

interface Props {
  label: string;
  value: number | string;
  accent?: boolean;
  alert?: boolean;
  href?: string;
}

export function StatCard({ label, value, accent, alert, href }: Props) {
  const Tag = href ? "a" : "div";
  return (
    <Tag
      {...(href ? { href } : {})}
      className={cn(
        "group relative flex flex-col gap-1 overflow-hidden rounded-xl border border-border bg-surface-1 px-5 py-4 transition-all duration-200",
        href && "cursor-pointer hover:border-border-strong hover:bg-surface-2",
        alert && "border-danger/30 hover:border-danger/50",
      )}
    >
      {/* Subtle corner glow */}
      {accent && (
        <div className="pointer-events-none absolute -right-6 -top-6 h-16 w-16 rounded-full bg-accent/10 blur-xl" />
      )}
      {alert && (
        <div className="pointer-events-none absolute -right-6 -top-6 h-16 w-16 rounded-full bg-danger/10 blur-xl" />
      )}

      <span
        className={cn(
          "font-display text-2xl font-bold tabular-nums tracking-tight",
          alert ? "text-danger" : accent ? "text-accent" : "text-text-primary",
        )}
      >
        {value}
      </span>
      <span className="text-xs font-medium uppercase tracking-wider text-text-muted">
        {label}
      </span>
    </Tag>
  );
}
