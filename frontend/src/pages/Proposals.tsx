import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Proposal } from "@/lib/api";
import { formatDate, cn } from "@/lib/utils";

const STATUS_STYLES: Record<string, { bg: string; text: string }> = {
  pending: { bg: "bg-warning/10", text: "text-warning" },
  approved: { bg: "bg-success/10", text: "text-success" },
  rejected: { bg: "bg-danger/10", text: "text-danger" },
  expired: { bg: "bg-slate-500/10", text: "text-slate-400" },
  withdrawn: { bg: "bg-slate-500/10", text: "text-slate-400" },
};

export function Proposals() {
  const proposalsQuery = useQuery({
    queryKey: ["proposals"],
    queryFn: () => api.listProposals({ limit: 50 }),
  });

  const proposals = proposalsQuery.data?.results ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-xl font-bold text-text-primary">
          Proposals
        </h1>
        <p className="mt-1 text-sm text-text-secondary">
          Breaking change proposals awaiting consumer acknowledgment
        </p>
      </div>

      <div className="space-y-3">
        {proposalsQuery.isLoading ? (
          <div className="py-12 text-center text-sm text-text-muted">Loading...</div>
        ) : proposals.length === 0 ? (
          <div className="rounded-xl border border-border bg-surface-1 p-8 text-center text-sm text-text-muted">
            No proposals found
          </div>
        ) : (
          proposals.map((p) => <ProposalCard key={p.id} proposal={p} />)
        )}
      </div>
    </div>
  );
}

function ProposalCard({ proposal }: { proposal: Proposal }) {
  const style = STATUS_STYLES[proposal.status] ?? STATUS_STYLES.pending;
  const ackRatio =
    proposal.total_consumers > 0
      ? proposal.acknowledgment_count / proposal.total_consumers
      : 0;

  return (
    <div className="rounded-xl border border-border bg-surface-1 p-5 transition-all hover:border-border-strong">
      <div className="flex items-start justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-3">
            <h3 className="truncate font-mono text-sm font-semibold text-text-primary">
              {proposal.asset_fqn ?? proposal.asset_id}
            </h3>
            <span
              className={cn(
                "shrink-0 rounded-full px-2 py-0.5 text-2xs font-medium",
                style.bg,
                style.text,
              )}
            >
              {proposal.status}
            </span>
          </div>
          <p className="mt-1 text-xs text-text-muted">
            {proposal.breaking_changes_count} breaking change
            {proposal.breaking_changes_count !== 1 ? "s" : ""}
            <span className="mx-1.5">&middot;</span>
            proposed version{" "}
            <span className="font-mono text-text-secondary">
              {proposal.proposed_version}
            </span>
            <span className="mx-1.5">&middot;</span>
            {formatDate(proposal.proposed_at)}
          </p>
        </div>

        {/* Ack progress */}
        {proposal.total_consumers > 0 && (
          <div className="ml-4 shrink-0 text-right">
            <div className="flex items-center gap-2">
              <div className="h-2 w-20 overflow-hidden rounded-full bg-surface-3">
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
              <span className="font-mono text-xs text-text-muted">
                {proposal.acknowledgment_count}/{proposal.total_consumers}
              </span>
            </div>
            <p className="mt-0.5 text-2xs text-text-muted">acknowledged</p>
          </div>
        )}
      </div>

      {/* Action buttons for pending proposals */}
      {proposal.status === "pending" && (
        <div className="mt-4 flex gap-2 border-t border-border/50 pt-3">
          <button className="rounded-lg bg-success/10 px-3 py-1.5 text-xs font-medium text-success transition-colors hover:bg-success/20">
            Approve
          </button>
          <button className="rounded-lg bg-warning/10 px-3 py-1.5 text-xs font-medium text-warning transition-colors hover:bg-warning/20">
            Migrating
          </button>
          <button className="rounded-lg bg-danger/10 px-3 py-1.5 text-xs font-medium text-danger transition-colors hover:bg-danger/20">
            Block
          </button>
        </div>
      )}
    </div>
  );
}
