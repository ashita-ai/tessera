import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";

const NAV_ITEMS = [
  { to: "/", label: "Dashboard", icon: GridIcon },
  { to: "/services", label: "Services", icon: ServiceIcon },
  { to: "/assets", label: "Assets", icon: AssetIcon },
  { to: "/proposals", label: "Proposals", icon: ProposalIcon },
  { to: "/teams", label: "Teams", icon: TeamIcon },
  { to: "/audit", label: "Audit Log", icon: AuditIcon },
] as const;

export function Sidebar() {
  return (
    <aside className="flex w-56 flex-col border-r border-border bg-surface-1">
      {/* Logo */}
      <div className="flex h-14 items-center gap-2.5 border-b border-border px-5">
        <div className="flex h-7 w-7 items-center justify-center rounded-md bg-accent/20">
          <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
            <rect x="1" y="1" width="5" height="5" rx="1" fill="var(--accent)" />
            <rect x="8" y="1" width="5" height="5" rx="1" fill="var(--accent)" opacity="0.6" />
            <rect x="1" y="8" width="5" height="5" rx="1" fill="var(--accent)" opacity="0.6" />
            <rect x="8" y="8" width="5" height="5" rx="1" fill="var(--accent)" opacity="0.3" />
          </svg>
        </div>
        <span className="font-display text-lg font-bold tracking-tight text-text-primary">
          Tessera
        </span>
      </div>

      {/* Navigation */}
      <nav className="flex-1 space-y-0.5 px-3 py-4">
        {NAV_ITEMS.map(({ to, label, icon: Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === "/"}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-all duration-150",
                isActive
                  ? "bg-accent/10 text-accent shadow-glow-sm"
                  : "text-text-secondary hover:bg-surface-2 hover:text-text-primary",
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>

      {/* Footer */}
      <div className="border-t border-border px-5 py-3">
        <p className="font-mono text-2xs text-text-muted">v0.1.0</p>
      </div>
    </aside>
  );
}

/* Inline SVG icons — small, purposeful, no dependency */

function GridIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <rect x="2" y="2" width="5" height="5" rx="1" />
      <rect x="9" y="2" width="5" height="5" rx="1" />
      <rect x="2" y="9" width="5" height="5" rx="1" />
      <rect x="9" y="9" width="5" height="5" rx="1" />
    </svg>
  );
}

function ServiceIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="8" cy="4" r="2.5" />
      <circle cx="4" cy="12" r="2.5" />
      <circle cx="12" cy="12" r="2.5" />
      <line x1="8" y1="6.5" x2="5" y2="9.5" />
      <line x1="8" y1="6.5" x2="11" y2="9.5" />
    </svg>
  );
}

function AssetIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M3 3h10v10H3z" rx="1" />
      <path d="M6 6h4" />
      <path d="M6 8.5h4" />
      <path d="M6 11h2" />
    </svg>
  );
}

function ProposalIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M8 2v12M2 8h12" />
      <circle cx="8" cy="8" r="6" />
    </svg>
  );
}

function TeamIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <circle cx="6" cy="5" r="2.5" />
      <circle cx="11" cy="6" r="2" />
      <path d="M1.5 14c0-2.5 2-4.5 4.5-4.5s4.5 2 4.5 4.5" />
      <path d="M10 14c0-1.8 1-3 2-3s2 1.2 2 3" />
    </svg>
  );
}

function AuditIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5">
      <path d="M4 2v12" />
      <circle cx="4" cy="4" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="4" cy="8" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="4" cy="12" r="1.5" fill="currentColor" stroke="none" />
      <path d="M7 4h6M7 8h4M7 12h5" />
    </svg>
  );
}
