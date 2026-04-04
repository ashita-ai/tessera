import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Repo } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { CardGridSkeleton } from "@/components/shared/Skeleton";
import { EmptyState } from "@/components/shared/EmptyState";

export function Repos() {
  const [showRegister, setShowRegister] = useState(false);

  const reposQuery = useQuery({
    queryKey: ["repos"],
    queryFn: () => api.listRepos({ limit: 50 }),
    retry: false,
  });

  const repos = reposQuery.data?.results ?? [];

  return (
    <div className="animate-enter space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-sm font-medium text-t2">Repositories</h1>
        <button
          onClick={() => setShowRegister(true)}
          className="rounded-md bg-accent/10 px-3 py-1.5 font-mono text-[11px] font-medium text-accent transition-colors hover:bg-accent/20"
        >
          Register
        </button>
      </div>

      {reposQuery.isError ? (
        <EmptyState
          title="Repository registry not available"
          description="The repos API endpoint has not been implemented yet."
        />
      ) : reposQuery.isLoading ? (
        <CardGridSkeleton />
      ) : repos.length === 0 ? (
        <EmptyState
          title="No repositories registered"
          description="Register a git repository to start tracking API specs and discovering services."
          actionLabel="Register repository"
          onAction={() => setShowRegister(true)}
        />
      ) : (
        <div className="stagger grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {repos.map((repo) => (
            <RepoCard key={repo.id} repo={repo} />
          ))}
        </div>
      )}

      {showRegister && <RegisterRepoModal onClose={() => setShowRegister(false)} />}
    </div>
  );
}

function SyncBadge({ repo }: { repo: Repo }) {
  if (!repo.sync_enabled) {
    return (
      <span className="rounded-full bg-bg-hover px-1.5 py-px text-[10px] font-medium text-t3">
        disabled
      </span>
    );
  }
  if (repo.last_synced_at) {
    return (
      <span className="rounded-full bg-green/10 px-1.5 py-px text-[10px] font-medium text-green">
        synced
      </span>
    );
  }
  return (
    <span className="rounded-full bg-amber/8 px-1.5 py-px text-[10px] font-medium text-amber">
      pending
    </span>
  );
}

function RepoCard({ repo }: { repo: Repo }) {
  return (
    <Link
      to={`/repos/${repo.id}`}
      className="group rounded-lg border border-line bg-bg-raised p-4 transition-colors hover:border-line-strong"
    >
      <div className="flex items-start justify-between">
        <p className="font-mono text-xs font-medium text-t1">{repo.name}</p>
        <SyncBadge repo={repo} />
      </div>

      <div className="mt-3 space-y-1 text-[11px]">
        <div className="flex items-center gap-2">
          <span className="w-10 shrink-0 text-t3">url</span>
          <span className="truncate font-mono text-[10px] text-t2">{repo.git_url}</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="w-10 shrink-0 text-t3">branch</span>
          <span className="font-mono text-[10px] text-accent">{repo.default_branch}</span>
        </div>
        {repo.spec_paths.length > 0 && (
          <div className="flex items-center gap-2">
            <span className="w-10 shrink-0 text-t3">specs</span>
            <span className="truncate font-mono text-[10px] text-t2">
              {repo.spec_paths.join(", ")}
            </span>
          </div>
        )}
        <div className="flex items-center gap-2">
          <span className="w-10 shrink-0 text-t3">services</span>
          <span className="text-t2">{repo.services_count ?? 0}</span>
        </div>
      </div>

      {repo.last_synced_at && (
        <p className="mt-3 border-t border-line/50 pt-2 text-[10px] text-t3">
          Synced {formatDate(repo.last_synced_at)}
        </p>
      )}
    </Link>
  );
}

function RegisterRepoModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [gitUrl, setGitUrl] = useState("");
  const [branch, setBranch] = useState("main");
  const [specPaths, setSpecPaths] = useState("");
  const [teamId, setTeamId] = useState("");
  const [codeownersPath, setCodeownersPath] = useState("");
  const [error, setError] = useState<string | null>(null);

  const teamsQuery = useQuery({
    queryKey: ["teams"],
    queryFn: () => api.listTeams({ limit: 200 }),
  });

  const teams = teamsQuery.data?.results ?? [];

  const mutation = useMutation({
    mutationFn: () =>
      api.createRepo({
        name,
        git_url: gitUrl,
        owner_team_id: teamId,
        default_branch: branch || "main",
        spec_paths: specPaths
          .split(",")
          .map((s) => s.trim())
          .filter(Boolean),
        codeowners_path: codeownersPath || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["repos"] });
      onClose();
    },
    onError: (err: Error) => setError(err.message),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim() || !gitUrl.trim() || !teamId) {
      setError("Name, git URL, and owner team are required.");
      return;
    }
    mutation.mutate();
  };

  return (
    <>
      <div className="fixed inset-0 z-40 bg-bg/70 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="w-full max-w-md rounded-lg border border-line bg-bg-raised p-5 shadow-2xl">
          <p className="text-[13px] font-medium text-t1">Register repository</p>
          <p className="mt-1 text-[11px] text-t3">
            Point Tessera at a git repository containing API specs.
          </p>

          <form className="mt-4 space-y-3" onSubmit={handleSubmit}>
            <Field label="Repository name" placeholder="e.g., order-service" value={name} onChange={setName} />
            <Field label="Git URL" placeholder="https://github.com/org/repo" value={gitUrl} onChange={setGitUrl} />
            <SelectField
              label="Owner team"
              placeholder={teamsQuery.isLoading ? "Loading teams..." : "Select a team"}
              value={teamId}
              onChange={setTeamId}
              options={teams.map((t) => ({ value: t.id, label: t.name }))}
              hint="The team responsible for this repository"
            />
            <Field label="Default branch" placeholder="main" value={branch} onChange={setBranch} />
            <Field
              label="Spec file paths"
              placeholder="api/openapi.yaml, proto/"
              hint="Comma-separated paths to OpenAPI, protobuf, or GraphQL specs"
              value={specPaths}
              onChange={setSpecPaths}
            />
            <Field
              label="CODEOWNERS path"
              placeholder=".github/CODEOWNERS"
              hint="Path to CODEOWNERS file for team suggestions"
              value={codeownersPath}
              onChange={setCodeownersPath}
            />

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
                {mutation.isPending ? "Registering..." : "Register"}
              </button>
            </div>
          </form>
        </div>
      </div>
    </>
  );
}

function Field({
  label,
  placeholder,
  hint,
  value,
  onChange,
}: {
  label: string;
  placeholder: string;
  hint?: string;
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-medium text-t2">{label}</label>
      <input
        type="text"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-line bg-bg-surface px-3 py-1.5 font-mono text-xs text-t1 placeholder:text-t3 focus:border-accent/40 focus:outline-none"
      />
      {hint && <p className="mt-0.5 text-[10px] text-t3">{hint}</p>}
    </div>
  );
}

function SelectField({ label, placeholder, hint, value, onChange, options }: { label: string; placeholder: string; hint?: string; value: string; onChange: (v: string) => void; options: { value: string; label: string }[] }) {
  return (
    <div>
      <label className="mb-1 block text-[11px] font-medium text-t2">{label}</label>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-md border border-line bg-bg-surface px-3 py-1.5 font-mono text-xs text-t1 focus:border-accent/40 focus:outline-none"
      >
        <option value="" disabled className="text-t3">{placeholder}</option>
        {options.map((opt) => (
          <option key={opt.value} value={opt.value}>{opt.label}</option>
        ))}
      </select>
      {hint && <p className="mt-0.5 text-[10px] text-t3">{hint}</p>}
    </div>
  );
}
