import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Proposal, AuditEvent } from "@/lib/api";
import { StatCard } from "@/components/shared/StatCard";
import { ActivityFeed, type ActivityItem } from "@/components/shared/ActivityFeed";
import {
  DependencyGraph,
  type GraphNode,
  type GraphLink,
} from "@/components/graph/DependencyGraph";
import { formatDate } from "@/lib/utils";

// Demo graph data — replaced by real API once service endpoints exist
const DEMO_NODES: GraphNode[] = [
  { id: "user-svc", label: "user-service", group: "Platform", assetCount: 8, hasBreakingProposal: false },
  { id: "auth-svc", label: "auth-service", group: "Platform", assetCount: 4, hasBreakingProposal: false },
  { id: "order-svc", label: "order-service", group: "Commerce", assetCount: 12, hasBreakingProposal: true },
  { id: "payment-svc", label: "payment-service", group: "Commerce", assetCount: 6, hasBreakingProposal: false },
  { id: "inventory-svc", label: "inventory-service", group: "Commerce", assetCount: 5, hasBreakingProposal: false },
  { id: "notif-svc", label: "notification-service", group: "Platform", assetCount: 3, hasBreakingProposal: false },
  { id: "analytics-svc", label: "analytics-service", group: "Data", assetCount: 15, hasBreakingProposal: false },
  { id: "search-svc", label: "search-service", group: "Platform", assetCount: 4, hasBreakingProposal: false },
  { id: "catalog-svc", label: "catalog-service", group: "Commerce", assetCount: 9, hasBreakingProposal: false },
  { id: "shipping-svc", label: "shipping-service", group: "Logistics", assetCount: 7, hasBreakingProposal: false },
];

const DEMO_LINKS: GraphLink[] = [
  { source: "order-svc", target: "user-svc", type: "CONSUMES" },
  { source: "order-svc", target: "payment-svc", type: "CONSUMES" },
  { source: "order-svc", target: "inventory-svc", type: "CONSUMES" },
  { source: "order-svc", target: "notif-svc", type: "CONSUMES" },
  { source: "payment-svc", target: "user-svc", type: "CONSUMES" },
  { source: "payment-svc", target: "notif-svc", type: "CONSUMES" },
  { source: "auth-svc", target: "user-svc", type: "CONSUMES" },
  { source: "analytics-svc", target: "order-svc", type: "REFERENCES", confidence: 0.85 },
  { source: "analytics-svc", target: "user-svc", type: "REFERENCES", confidence: 0.92 },
  { source: "analytics-svc", target: "payment-svc", type: "REFERENCES", confidence: 0.78 },
  { source: "search-svc", target: "catalog-svc", type: "CONSUMES" },
  { source: "order-svc", target: "catalog-svc", type: "CONSUMES" },
  { source: "catalog-svc", target: "inventory-svc", type: "TRANSFORMS" },
  { source: "shipping-svc", target: "order-svc", type: "CONSUMES" },
  { source: "shipping-svc", target: "notif-svc", type: "CONSUMES" },
];

function auditEventToActivity(event: AuditEvent): ActivityItem {
  const actionMap: Record<string, { label: string; severity: "info" | "warning" | "danger" }> = {
    CONTRACT_PUBLISHED: { label: "Published contract", severity: "info" },
    CONTRACT_DEPRECATED: { label: "Deprecated contract", severity: "warning" },
    PROPOSAL_CREATED: { label: "Created proposal", severity: "warning" },
    PROPOSAL_APPROVED: { label: "Approved proposal", severity: "info" },
    PROPOSAL_REJECTED: { label: "Rejected proposal", severity: "danger" },
    FORCE_PUBLISH: { label: "Force-published", severity: "danger" },
  };
  const mapped = actionMap[event.action] ?? { label: event.action, severity: "info" as const };

  return {
    id: event.id,
    action: mapped.label,
    entity: String(event.payload?.["asset_fqn"] ?? event.entity_id),
    entityType: event.entity_type,
    actor: event.actor_id ?? "system",
    actorType: event.actor_type as "human" | "agent",
    timestamp: event.created_at,
    severity: mapped.severity,
  };
}

export function Dashboard() {
  const [selectedNode, setSelectedNode] = useState<string | null>(null);

  const statsQuery = useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: () => api.getStats(),
  });

  const proposalsQuery = useQuery({
    queryKey: ["pending-proposals"],
    queryFn: () => api.listProposals({ status: "pending", limit: 5 }),
  });

  const auditQuery = useQuery({
    queryKey: ["recent-audit"],
    queryFn: () => api.listAuditEvents({ limit: 10 }),
  });

  const stats = statsQuery.data;
  const proposals = proposalsQuery.data?.results ?? [];
  const activity = (auditQuery.data?.results ?? []).map(auditEventToActivity);

  return (
    <div className="space-y-6">
      {/* Stats row */}
      <div className="stagger-children grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Services"
          value={stats?.services ?? "\u2014"}
          accent
          href="/services"
        />
        <StatCard
          label="Assets"
          value={stats?.assets ?? "\u2014"}
          href="/assets"
        />
        <StatCard
          label="Contracts"
          value={stats?.contracts ?? "\u2014"}
          href="/assets"
        />
        <StatCard
          label="Pending Proposals"
          value={stats?.pending_proposals ?? "\u2014"}
          alert={(stats?.pending_proposals ?? 0) > 0}
          href="/proposals"
        />
      </div>

      {/* Graph + sidebar */}
      <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
        {/* Dependency graph — 2/3 width */}
        <div className="xl:col-span-2">
          <div className="overflow-hidden rounded-xl border border-border bg-surface-1">
            <div className="flex items-center justify-between border-b border-border px-5 py-3">
              <h2 className="font-display text-sm font-semibold tracking-wide text-text-primary">
                Service Dependencies
              </h2>
              <span className="font-mono text-2xs text-text-muted">
                {DEMO_NODES.length} services &middot; {DEMO_LINKS.length} edges
              </span>
            </div>
            <DependencyGraph
              nodes={DEMO_NODES}
              links={DEMO_LINKS}
              onNodeClick={(node) => setSelectedNode(node.id)}
              className="h-[460px] bg-grid"
            />
          </div>
        </div>

        {/* Sidebar panels — 1/3 width */}
        <div className="space-y-4">
          {/* Pending proposals */}
          <div className="rounded-xl border border-border bg-surface-1">
            <div className="border-b border-border px-5 py-3">
              <h2 className="font-display text-sm font-semibold tracking-wide text-text-primary">
                Pending Proposals
              </h2>
            </div>
            <div className="px-4 py-2">
              {proposals.length === 0 ? (
                <p className="py-6 text-center text-sm text-text-muted">
                  No pending proposals
                </p>
              ) : (
                <div className="divide-y divide-border/50">
                  {proposals.map((p) => (
                    <ProposalRow key={p.id} proposal={p} />
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Recent activity */}
          <div className="rounded-xl border border-border bg-surface-1">
            <div className="border-b border-border px-5 py-3">
              <h2 className="font-display text-sm font-semibold tracking-wide text-text-primary">
                Recent Activity
              </h2>
            </div>
            <div className="px-4 py-2">
              <ActivityFeed items={activity} />
            </div>
          </div>
        </div>
      </div>

      {/* Selected node detail panel */}
      {selectedNode && (
        <div className="animate-fade-in-up rounded-xl border border-accent/20 bg-surface-1 p-5 shadow-glow-sm">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="font-mono text-sm font-semibold text-accent">
                {DEMO_NODES.find((n) => n.id === selectedNode)?.label}
              </h3>
              <p className="mt-0.5 text-xs text-text-muted">
                {DEMO_NODES.find((n) => n.id === selectedNode)?.group} &middot;{" "}
                {DEMO_NODES.find((n) => n.id === selectedNode)?.assetCount} assets
              </p>
            </div>
            <button
              onClick={() => setSelectedNode(null)}
              className="rounded-md px-2 py-1 text-xs text-text-muted hover:bg-surface-2 hover:text-text-secondary"
            >
              Close
            </button>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-3 text-xs">
            <div>
              <p className="font-medium text-text-secondary">Depends on</p>
              <ul className="mt-1 space-y-0.5 text-text-muted">
                {DEMO_LINKS.filter(
                  (l) =>
                    (typeof l.source === "string" ? l.source : l.source.id) ===
                    selectedNode,
                ).map((l, i) => (
                  <li key={i} className="font-mono">
                    {typeof l.target === "string" ? l.target : l.target.id}
                  </li>
                ))}
              </ul>
            </div>
            <div>
              <p className="font-medium text-text-secondary">Depended on by</p>
              <ul className="mt-1 space-y-0.5 text-text-muted">
                {DEMO_LINKS.filter(
                  (l) =>
                    (typeof l.target === "string" ? l.target : l.target.id) ===
                    selectedNode,
                ).map((l, i) => (
                  <li key={i} className="font-mono">
                    {typeof l.source === "string" ? l.source : l.source.id}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ProposalRow({ proposal }: { proposal: Proposal }) {
  const ackRatio =
    proposal.total_consumers > 0
      ? proposal.acknowledgment_count / proposal.total_consumers
      : 0;

  return (
    <div className="flex items-center justify-between py-2.5">
      <div className="min-w-0">
        <p className="truncate font-mono text-xs font-medium text-text-primary">
          {proposal.asset_fqn ?? proposal.asset_id}
        </p>
        <p className="mt-0.5 text-2xs text-text-muted">
          {proposal.breaking_changes_count} breaking change
          {proposal.breaking_changes_count !== 1 ? "s" : ""}
          <span className="mx-1">&middot;</span>
          {formatDate(proposal.proposed_at)}
        </p>
      </div>
      <div className="ml-3 shrink-0">
        {proposal.total_consumers > 0 ? (
          <div className="flex items-center gap-1.5">
            <div className="h-1.5 w-12 overflow-hidden rounded-full bg-surface-3">
              <div
                className="h-full rounded-full transition-all"
                style={{
                  width: `${ackRatio * 100}%`,
                  background:
                    ackRatio >= 1
                      ? "var(--success)"
                      : ackRatio > 0
                        ? "var(--warning)"
                        : "var(--danger)",
                }}
              />
            </div>
            <span className="font-mono text-2xs text-text-muted">
              {proposal.acknowledgment_count}/{proposal.total_consumers}
            </span>
          </div>
        ) : (
          <span className="text-2xs text-text-muted">no consumers</span>
        )}
      </div>
    </div>
  );
}
