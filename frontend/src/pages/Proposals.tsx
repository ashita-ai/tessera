import React from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Proposal } from "@/lib/api";
import { formatDate, cn } from "@/lib/utils";

const STATUS_DOT: Record<string, string> = {
  pending: "bg-amber",
  approved: "bg-green",
  rejected: "bg-red",
  expired: "bg-t3",
  withdrawn: "bg-t3",
};

export function Proposals() {
  const proposalsQuery = useQuery({
    queryKey: ["proposals"],
    queryFn: () => api.listProposals({ limit: 50 }),
  });

  const proposals = proposalsQuery.data?.results ?? [];

  return (
    <div className="animate-enter space-y-5">
      <h1 className="text-sm font-medium text-t2">Proposals</h1>

      {proposalsQuery.isLoading ? (
        <div className="py-16 text-center text-[11px] text-t3">Loading...</div>
      ) : proposals.length === 0 ? (
        <div className="rounded-lg border border-line bg-bg-raised px-6 py-10 text-center text-[11px] text-t3">
          No proposals
        </div>
      ) : (
        <div className="stagger space-y-2">
          {proposals.map((p) => (
            <ProposalRow key={p.id} proposal={p} />
          ))}
        </div>
      )}
    </div>
  );
}

function ProposalRow({ proposal }: { proposal: Proposal }) {
  const queryClient = useQueryClient();
  const ackMutation = useMutation({
    mutationFn: (data: { response: "APPROVED" | "BLOCKED" | "MIGRATING"; consumer_team_id: string }) =>
      api.acknowledgeProposal(proposal.id, { response: data.response, consumer_team_id: data.consumer_team_id }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["proposals"] });
    },
  });

  const ackRatio =
    proposal.total_consumers > 0
      ? proposal.acknowledgment_count / proposal.total_consumers
      : 0;

  const [teamId, setTeamId] = React.useState("");

  return (
    <div className="rounded-lg border border-line bg-bg-raised p-4 transition-colors hover:border-line-strong">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <div className={cn("mt-0.5 h-1.5 w-1.5 shrink-0 rounded-full", STATUS_DOT[proposal.status] ?? "bg-t3")} />
            <p className="truncate font-mono text-[11px] font-medium text-t1">
              {proposal.asset_fqn ?? proposal.asset_id}
            </p>
            <span className="shrink-0 text-[10px] text-t3">{proposal.status}</span>
          </div>
          <p className="ml-3.5 mt-0.5 text-[10px] text-t3">
            {proposal.breaking_changes_count} breaking
            {" \u00b7 "}
            <span className="font-mono">{proposal.proposed_version}</span>
            {" \u00b7 "}
            {formatDate(proposal.proposed_at)}
          </p>
        </div>

        {proposal.total_consumers > 0 && (
          <div className="flex shrink-0 items-center gap-2">
            <div className="h-1 w-10 overflow-hidden rounded-full bg-bg-hover">
              <div
                className="h-full rounded-full"
                style={{
                  width: `${ackRatio * 100}%`,
                  background:
                    ackRatio >= 1 ? "var(--green)" : ackRatio > 0 ? "var(--amber)" : "var(--red)",
                }}
              />
            </div>
            <span className="font-mono text-[10px] text-t3">
              {proposal.acknowledgment_count}/{proposal.total_consumers}
            </span>
          </div>
        )}
      </div>

      {proposal.status === "pending" && (
        <div className="ml-3.5 mt-3 space-y-2 border-t border-line/40 pt-2.5">
          <input
            type="text"
            placeholder="Consumer team ID"
            value={teamId}
            onChange={(e) => setTeamId(e.target.value)}
            className="w-full rounded-md border border-line bg-bg-surface px-2 py-1 font-mono text-[10px] text-t1 placeholder:text-t3 focus:border-accent focus:outline-none"
          />
          {ackMutation.isError && (
            <p className="text-[10px] text-red">{ackMutation.error instanceof Error ? ackMutation.error.message : "Acknowledgment failed"}</p>
          )}
          <div className="flex gap-1.5">
            <ActionBtn label="Approve" color="green" disabled={ackMutation.isPending || !teamId} onClick={() => ackMutation.mutate({ response: "APPROVED", consumer_team_id: teamId })} />
            <ActionBtn label="Migrating" color="amber" disabled={ackMutation.isPending || !teamId} onClick={() => ackMutation.mutate({ response: "MIGRATING", consumer_team_id: teamId })} />
            <ActionBtn label="Block" color="red" disabled={ackMutation.isPending || !teamId} onClick={() => ackMutation.mutate({ response: "BLOCKED", consumer_team_id: teamId })} />
          </div>
        </div>
      )}
    </div>
  );
}

function ActionBtn({ label, color, disabled, onClick }: { label: string; color: "green" | "amber" | "red"; disabled?: boolean; onClick: () => void }) {
  const styles: Record<string, string> = {
    green: "bg-green/8 text-green hover:bg-green/15",
    amber: "bg-amber/8 text-amber hover:bg-amber/15",
    red: "bg-red/8 text-red hover:bg-red/15",
  };
  return (
    <button
      disabled={disabled}
      onClick={onClick}
      className={cn("rounded-md px-2.5 py-1 text-[10px] font-medium transition-colors disabled:opacity-50", styles[color])}
    >
      {label}
    </button>
  );
}
