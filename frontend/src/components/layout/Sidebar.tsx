import { NavLink } from "react-router-dom";
import { cn } from "@/lib/utils";

const NAV = [
  { to: "/", label: "Overview", icon: GraphIcon, end: true },
  { to: "/services", label: "Services", icon: ServiceIcon },
  { to: "/assets", label: "Assets", icon: AssetIcon },
  { to: "/proposals", label: "Proposals", icon: ProposalIcon },
  { to: "/teams", label: "Teams", icon: TeamIcon },
  { to: "/audit", label: "Audit", icon: AuditIcon },
] as const;

export function Sidebar() {
  return (
    <aside className="flex w-56 flex-col border-r border-line bg-bg-raised">
      {/* Mark */}
      <div className="flex items-center gap-2.5 px-5 py-5">
        <svg width="18" height="18" viewBox="0 0 16 16" fill="none">
          <rect x="1" y="1" width="6" height="6" rx="1.5" fill="var(--accent)" opacity="0.9" />
          <rect x="9" y="1" width="6" height="6" rx="1.5" fill="var(--accent)" opacity="0.4" />
          <rect x="1" y="9" width="6" height="6" rx="1.5" fill="var(--accent)" opacity="0.4" />
          <rect x="9" y="9" width="6" height="6" rx="1.5" fill="var(--accent)" opacity="0.15" />
        </svg>
        <span className="text-sm font-semibold tracking-tight text-t1">tessera</span>
      </div>

      {/* Nav */}
      <nav className="flex flex-1 flex-col gap-0.5 px-3 pt-1">
        {NAV.map(({ to, label, icon: Icon, ...rest }) => (
          <NavLink
            key={to}
            to={to}
            end={"end" in rest}
            className={({ isActive }) =>
              cn(
                "flex items-center gap-3 rounded-md px-3 py-2 text-[13px] font-medium transition-colors",
                isActive
                  ? "bg-accent-dim text-accent"
                  : "text-t3 hover:bg-bg-hover hover:text-t2",
              )
            }
          >
            <Icon className="h-4 w-4 shrink-0" />
            {label}
          </NavLink>
        ))}
      </nav>

      <div className="border-t border-line px-5 py-3">
        <p className="font-mono text-[10px] text-t3">v0.1.0</p>
      </div>
    </aside>
  );
}

function GraphIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <circle cx="4" cy="4" r="2" /><circle cx="12" cy="4" r="2" /><circle cx="8" cy="12" r="2" />
      <line x1="5.5" y1="5.5" x2="7" y2="10.5" /><line x1="10.5" y1="5.5" x2="9" y2="10.5" />
    </svg>
  );
}

function ServiceIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <rect x="2" y="2" width="12" height="4" rx="1" /><rect x="2" y="10" width="12" height="4" rx="1" />
      <line x1="5" y1="6" x2="5" y2="10" /><line x1="11" y1="6" x2="11" y2="10" />
    </svg>
  );
}

function AssetIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M4 2h8l2 3v9a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1V5l2-3z" /><path d="M6 8h4M6 11h2" />
    </svg>
  );
}

function ProposalIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M8 2v12M4 6l4-4 4 4" />
    </svg>
  );
}

function TeamIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <circle cx="8" cy="5" r="2.5" /><path d="M3 14c0-2.8 2.2-5 5-5s5 2.2 5 5" />
    </svg>
  );
}

function AuditIcon({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round">
      <path d="M3 3v10M7 5h6M7 8h4M7 11h5" />
    </svg>
  );
}
