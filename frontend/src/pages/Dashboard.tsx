import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import type { Proposal, AuditEvent } from "@/lib/api";
import { StatCard } from "@/components/shared/StatCard";
import { ActivityFeed, type ActivityItem } from "@/components/shared/ActivityFeed";
import { DependencyGraph } from "@/components/graph/DependencyGraph";
import { GraphSkeleton } from "@/components/shared/Skeleton";
import { formatDate } from "@/lib/utils";

function toActivity(e: AuditEvent): ActivityItem {
  const map: Record<string, { label: string; severity: "info" | "warning" | "danger" }> = {
    CONTRACT_PUBLISHED: { label: "Published", severity: "info" },
    CONTRACT_DEPRECATED: { label: "Deprecated", severity: "warning" },
    PROPOSAL_CREATED: { label: "Proposal", severity: "warning" },
    PROPOSAL_APPROVED: { label: "Approved", severity: "info" },
    PROPOSAL_REJECTED: { label: "Rejected", severity: "danger" },
    FORCE_PUBLISH: { label: "Force-published", severity: "danger" },
  };
  const m = map[e.action] ?? { label: e.action, severity: "info" as const };
  return {
    id: e.id,
    action: m.label,
    entity: String(e.payload?.["asset_fqn"] ?? e.entity_id),
    entityType: e.entity_type,
    actor: e.actor_id ?? "system",
    actorType: e.actor_type as "human" | "agent",
    timestamp: e.occurred_at,
    severity: m.severity,
  };
}

export function Dashboard() {
  const navigate = useNavigate();
  const stats = useQuery({ queryKey: ["stats"], queryFn: () => api.getStats() });
  const proposals = useQuery({ queryKey: ["proposals-pending"], queryFn: () => api.listProposals({ status: "pending", limit: 5 }) });
  const audit = useQuery({ queryKey: ["audit-recent"], queryFn: () => api.listAuditEvents({ limit: 8 }), retry: false });
  const graph = useQuery({ queryKey: ["graph"], queryFn: () => api.getGraphData(), retry: false });

  const s = stats.data;
  const pending = proposals.data?.results ?? [];
  const activity = (audit.data?.results ?? []).map(toActivity);

  return (
    <div className="animate-enter space-y-5">
      {/* Stats */}
      <div className="stagger grid grid-cols-3 gap-3">
        <StatCard label="Assets" value={s?.assets ?? "\u2014"} href="/assets" />
        <StatCard label="Contracts" value={s?.contracts ?? "\u2014"} />
        <StatCard label="Proposals" value={s?.pending_proposals ?? "\u2014"} alert={(s?.pending_proposals ?? 0) > 0} href="/proposals" />
      </div>

      {/* Main content */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[1fr_280px]">
        {/* Dependency graph */}
        <div className="overflow-hidden rounded-lg border border-line bg-bg-raised">
          <div className="flex items-center justify-between border-b border-line px-4 py-2">
            <span className="text-[13px] font-medium text-t2">Dependency graph</span>
          </div>
          <div className="h-[520px]">
            {graph.isLoading ? (
              <GraphSkeleton />
            ) : !graph.data || graph.data.nodes.length === 0 ? (
              <div className="flex h-full flex-col items-center justify-center px-6">
                <svg width="48" height="48" viewBox="0 0 48 48" fill="none" className="mb-4 text-t3">
                  <circle cx="14" cy="14" r="5" stroke="currentColor" strokeWidth="1.5" opacity="0.4" />
                  <circle cx="34" cy="14" r="5" stroke="currentColor" strokeWidth="1.5" opacity="0.4" />
                  <circle cx="24" cy="36" r="5" stroke="currentColor" strokeWidth="1.5" opacity="0.4" />
                  <line x1="18" y1="17" x2="21" y2="32" stroke="currentColor" strokeWidth="1" opacity="0.2" />
                  <line x1="30" y1="17" x2="27" y2="32" stroke="currentColor" strokeWidth="1" opacity="0.2" />
                  <line x1="19" y1="14" x2="29" y2="14" stroke="currentColor" strokeWidth="1" opacity="0.2" />
                </svg>
                <p className="text-[13px] text-t2">No dependencies discovered</p>
                <p className="mt-1 max-w-xs text-center text-[11px] text-t3">
                  Register services and their API specs to see the dependency graph.
                  Dependencies are discovered automatically from OTEL traces.
                </p>
              </div>
            ) : (
              <DependencyGraph
                graphData={graph.data}
                onNodeClick={(nodeId) => navigate(`/assets/${nodeId}`)}
              />
            )}
          </div>
        </div>

        {/* Right column */}
        <div className="space-y-4">
          {/* Pending proposals */}
          <div className="rounded-lg border border-line bg-bg-raised">
            <p className="border-b border-line px-4 py-2 text-[13px] font-medium text-t2">Pending</p>
            <div className="px-3 py-1">
              {pending.length === 0 ? (
                <p className="py-4 text-center text-[11px] text-t3">All clear</p>
              ) : (
                pending.map((p) => <MiniProposal key={p.id} proposal={p} />)
              )}
            </div>
          </div>

          {/* Activity */}
          <div className="rounded-lg border border-line bg-bg-raised">
            <p className="border-b border-line px-4 py-2 text-[13px] font-medium text-t2">Activity</p>
            <div className="px-3 py-1">
              <ActivityFeed items={activity} />
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

function MiniProposal({ proposal }: { proposal: Proposal }) {
  const ratio = proposal.total_consumers > 0 ? proposal.acknowledgment_count / proposal.total_consumers : 0;
  return (
    <div className="flex items-center justify-between py-2">
      <div className="min-w-0">
        <p className="truncate font-mono text-[11px] text-t1">{proposal.asset_fqn ?? proposal.asset_id}</p>
        <p className="text-[10px] text-t3">
          {proposal.breaking_changes_count} breaking &middot; {formatDate(proposal.proposed_at)}
        </p>
      </div>
      {proposal.total_consumers > 0 && (
        <div className="ml-2 flex shrink-0 items-center gap-1.5">
          <div className="h-1 w-8 overflow-hidden rounded-full bg-bg-hover">
            <div className="h-full rounded-full" style={{
              width: `${ratio * 100}%`,
              background: ratio >= 1 ? "var(--green)" : ratio > 0 ? "var(--amber)" : "var(--red)",
            }} />
          </div>
          <span className="font-mono text-[10px] text-t3">{proposal.acknowledgment_count}/{proposal.total_consumers}</span>
        </div>
      )}
    </div>
  );
}
