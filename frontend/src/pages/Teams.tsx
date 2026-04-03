import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/utils";

export function Teams() {
  const teamsQuery = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams({ limit: 50 }),
  });

  const teams = teamsQuery.data?.results ?? [];

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-xl font-bold text-text-primary">Teams</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Teams own services and assets, and acknowledge proposals
        </p>
      </div>

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {teams.map((team) => (
          <div
            key={team.id}
            className="group rounded-xl border border-border bg-surface-1 p-5 transition-all hover:border-border-strong hover:bg-surface-2"
          >
            <h3 className="font-mono text-sm font-semibold text-text-primary">
              {team.name}
            </h3>
            <div className="mt-3 flex gap-4 text-xs text-text-muted">
              <span>
                <span className="font-medium text-text-secondary">
                  {team.asset_count ?? 0}
                </span>{" "}
                assets
              </span>
              <span>
                <span className="font-medium text-text-secondary">
                  {team.member_count ?? 0}
                </span>{" "}
                members
              </span>
            </div>
            <p className="mt-2 text-2xs text-text-muted">
              Created {formatDate(team.created_at)}
            </p>
          </div>
        ))}
      </div>

      {teamsQuery.isLoading && (
        <div className="py-12 text-center text-sm text-text-muted">Loading...</div>
      )}
      {!teamsQuery.isLoading && teams.length === 0 && (
        <div className="rounded-xl border border-border bg-surface-1 p-8 text-center text-sm text-text-muted">
          No teams found
        </div>
      )}
    </div>
  );
}
