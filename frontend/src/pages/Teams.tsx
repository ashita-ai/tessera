import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/utils";

export function Teams() {
  const [showCreate, setShowCreate] = useState(false);

  const teamsQuery = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams({ limit: 50 }),
  });

  const teams = teamsQuery.data?.results ?? [];

  return (
    <div className="animate-enter space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-sm font-medium text-t2">Teams</h1>
        <button
          onClick={() => setShowCreate(true)}
          className="rounded-md bg-accent/10 px-3 py-1.5 font-mono text-[11px] font-medium text-accent transition-colors hover:bg-accent/20"
        >
          Create team
        </button>
      </div>

      {teamsQuery.isLoading ? (
        <div className="py-16 text-center text-[11px] text-t3">Loading...</div>
      ) : teams.length === 0 ? (
        <div className="rounded-lg border border-line bg-bg-raised px-6 py-10 text-center">
          <p className="text-[11px] text-t3">No teams found</p>
          <button
            onClick={() => setShowCreate(true)}
            className="mt-3 rounded-md bg-accent/10 px-3 py-1.5 font-mono text-[11px] font-medium text-accent transition-colors hover:bg-accent/20"
          >
            Create your first team
          </button>
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

      {showCreate && <CreateTeamModal onClose={() => setShowCreate(false)} />}
    </div>
  );
}

function CreateTeamModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () => api.createTeam({ name }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["teams"] });
      onClose();
    },
    onError: (err: Error) => setError(err.message),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim()) {
      setError("Team name is required.");
      return;
    }
    mutation.mutate();
  };

  return (
    <>
      <div className="fixed inset-0 z-40 bg-bg/70 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="w-full max-w-md rounded-lg border border-line bg-bg-raised p-5 shadow-2xl">
          <p className="text-[13px] font-medium text-t1">Create team</p>
          <p className="mt-1 text-[11px] text-t3">Teams own repositories, services, and assets.</p>

          <form className="mt-4 space-y-3" onSubmit={handleSubmit}>
            <div>
              <label className="mb-1 block text-[11px] font-medium text-t2">Team name</label>
              <input
                type="text"
                placeholder="e.g., platform-eng"
                value={name}
                onChange={(e) => setName(e.target.value)}
                autoFocus
                className="w-full rounded-md border border-line bg-bg-surface px-3 py-1.5 font-mono text-xs text-t1 placeholder:text-t3 focus:border-accent/40 focus:outline-none"
              />
            </div>

            {error && <p className="text-[11px] text-red">{error}</p>}

            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-md border border-line px-3 py-1.5 text-[11px] text-t3 transition-colors hover:bg-bg-hover hover:text-t2"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={mutation.isPending}
                className="rounded-md bg-accent/10 px-3 py-1.5 text-[11px] font-medium text-accent transition-colors hover:bg-accent/20 disabled:opacity-50"
              >
                {mutation.isPending ? "Creating..." : "Create"}
              </button>
            </div>
          </form>
        </div>
      </div>
    </>
  );
}
