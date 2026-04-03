import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatDate, cn } from "@/lib/utils";

const ACTION_COLOR: Record<string, string> = {
  CONTRACT_PUBLISHED: "text-accent",
  CONTRACT_DEPRECATED: "text-amber",
  PROPOSAL_CREATED: "text-amber",
  PROPOSAL_APPROVED: "text-green",
  PROPOSAL_REJECTED: "text-red",
  FORCE_PUBLISH: "text-red",
  REGISTRATION_CREATED: "text-accent",
  TEAM_CREATED: "text-accent",
  USER_CREATED: "text-accent",
};

function dotColor(action: string): string {
  if (action.includes("REJECT") || action === "FORCE_PUBLISH") return "bg-red";
  if (action.includes("DEPRECATED") || action.includes("PROPOSAL")) return "bg-amber";
  return "bg-accent";
}

export function AuditLog() {
  const [actionFilter, setActionFilter] = useState("");

  const auditQuery = useQuery({
    queryKey: ["audit", actionFilter],
    queryFn: () =>
      api.listAuditEvents({
        limit: 100,
        ...(actionFilter ? { action: actionFilter } : {}),
      }),
  });

  const events = auditQuery.data?.results ?? [];

  return (
    <div className="animate-enter space-y-5">
      <h1 className="text-sm font-medium text-t2">Audit log</h1>

      <select
        value={actionFilter}
        onChange={(e) => setActionFilter(e.target.value)}
        className="rounded-md border border-line bg-bg-raised px-3 py-1.5 text-xs text-t2 focus:border-accent/40 focus:outline-none"
      >
        <option value="">All actions</option>
        <option value="CONTRACT_PUBLISHED">Contract Published</option>
        <option value="CONTRACT_DEPRECATED">Contract Deprecated</option>
        <option value="PROPOSAL_CREATED">Proposal Created</option>
        <option value="PROPOSAL_APPROVED">Proposal Approved</option>
        <option value="PROPOSAL_REJECTED">Proposal Rejected</option>
        <option value="FORCE_PUBLISH">Force Publish</option>
      </select>

      <div className="overflow-hidden rounded-lg border border-line bg-bg-raised">
        <div className="divide-y divide-line/40">
          {events.map((event) => (
            <div
              key={event.id}
              className="flex items-start gap-3 px-4 py-2.5 transition-colors hover:bg-bg-hover"
            >
              <div className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", dotColor(event.action))} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className={cn("font-mono text-[11px] font-medium", ACTION_COLOR[event.action] ?? "text-t2")}>
                    {event.action}
                  </span>
                  <span className="text-[10px] text-t3">{event.entity_type}</span>
                </div>
                <p className="mt-0.5 text-[10px] text-t3">
                  {event.actor_id ?? "system"}
                  {event.actor_type === "agent" && (
                    <span className="ml-1 rounded-sm bg-accent-dim px-1 py-px font-mono text-[9px] text-accent">bot</span>
                  )}
                  {" \u00b7 "}
                  {formatDate(event.created_at)}
                </p>
              </div>
            </div>
          ))}
        </div>

        {auditQuery.isLoading && (
          <div className="py-12 text-center text-[11px] text-t3">Loading...</div>
        )}
        {!auditQuery.isLoading && events.length === 0 && (
          <div className="py-12 text-center text-[11px] text-t3">No audit events</div>
        )}
      </div>
    </div>
  );
}
