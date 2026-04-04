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
    <div className="animate-enter space-y-5">
      <h1 className="text-sm font-medium text-t2">Teams</h1>

      {teamsQuery.isLoading ? (
        <div className="py-16 text-center text-[11px] text-t3">Loading...</div>
      ) : teams.length === 0 ? (
        <div className="rounded-lg border border-line bg-bg-raised px-6 py-10 text-center text-[11px] text-t3">
          No teams found
        </div>
      ) : (
        <div className="stagger grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {teams.map((team) => (
            <div
              key={team.id}
              className="rounded-lg border border-line bg-bg-raised p-4 transition-colors hover:border-line-strong"
            >
              <p className="font-mono text-xs font-medium text-t1">{team.name}</p>
              <div className="mt-2 text-[11px] text-t3">
                <span className="font-medium text-t2">{team.asset_count ?? 0}</span> assets
              </div>
              <p className="mt-2 text-[10px] text-t3">Created {formatDate(team.created_at)}</p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
