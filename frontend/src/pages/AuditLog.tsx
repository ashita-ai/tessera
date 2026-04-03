import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatDate, cn } from "@/lib/utils";

const ACTION_COLORS: Record<string, string> = {
  CONTRACT_PUBLISHED: "text-accent",
  CONTRACT_DEPRECATED: "text-warning",
  PROPOSAL_CREATED: "text-warning",
  PROPOSAL_APPROVED: "text-success",
  PROPOSAL_REJECTED: "text-danger",
  FORCE_PUBLISH: "text-danger",
  REGISTRATION_CREATED: "text-accent",
  TEAM_CREATED: "text-accent",
  USER_CREATED: "text-accent",
};

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
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-xl font-bold text-text-primary">
          Audit Log
        </h1>
        <p className="mt-1 text-sm text-text-secondary">
          Immutable record of every action taken in Tessera
        </p>
      </div>

      <div className="flex gap-3">
        <select
          value={actionFilter}
          onChange={(e) => setActionFilter(e.target.value)}
          className="rounded-lg border border-border bg-surface-1 px-3 py-2 text-sm text-text-secondary focus:border-accent focus:outline-none"
        >
          <option value="">All actions</option>
          <option value="CONTRACT_PUBLISHED">Contract Published</option>
          <option value="CONTRACT_DEPRECATED">Contract Deprecated</option>
          <option value="PROPOSAL_CREATED">Proposal Created</option>
          <option value="PROPOSAL_APPROVED">Proposal Approved</option>
          <option value="PROPOSAL_REJECTED">Proposal Rejected</option>
          <option value="FORCE_PUBLISH">Force Publish</option>
        </select>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-surface-1">
        <div className="divide-y divide-border/50">
          {events.map((event) => (
            <div
              key={event.id}
              className="flex items-start gap-4 px-5 py-3 transition-colors hover:bg-surface-2"
            >
              <div className="mt-0.5 shrink-0">
                <div
                  className={cn(
                    "h-2 w-2 rounded-full",
                    event.action.includes("REJECT") || event.action === "FORCE_PUBLISH"
                      ? "bg-danger"
                      : event.action.includes("DEPRECATED") || event.action.includes("PROPOSAL")
                        ? "bg-warning"
                        : "bg-accent",
                  )}
                />
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span
                    className={cn(
                      "font-mono text-xs font-medium",
                      ACTION_COLORS[event.action] ?? "text-text-secondary",
                    )}
                  >
                    {event.action}
                  </span>
                  <span className="text-2xs text-text-muted">
                    on {event.entity_type}
                  </span>
                </div>
                <p className="mt-0.5 text-xs text-text-muted">
                  {event.actor_id ?? "system"}
                  {event.actor_type === "agent" && (
                    <span className="ml-1 rounded-sm bg-accent/10 px-1 py-px text-2xs text-accent">
                      agent
                    </span>
                  )}
                  <span className="mx-1">&middot;</span>
                  {formatDate(event.created_at)}
                </p>
              </div>
              <button className="shrink-0 rounded-md px-2 py-1 text-2xs text-text-muted hover:bg-surface-3 hover:text-text-secondary">
                details
              </button>
            </div>
          ))}
        </div>
        {auditQuery.isLoading && (
          <div className="py-12 text-center text-sm text-text-muted">Loading...</div>
        )}
        {!auditQuery.isLoading && events.length === 0 && (
          <div className="py-12 text-center text-sm text-text-muted">
            No audit events found
          </div>
        )}
      </div>
    </div>
  );
}
