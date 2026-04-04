import { Link, useParams } from "react-router-dom";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Service } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { CardGridSkeleton } from "@/components/shared/Skeleton";
import { EmptyState } from "@/components/shared/EmptyState";

export function RepoDetail() {
  const { id } = useParams<{ id: string }>();
  const queryClient = useQueryClient();

  const repoQuery = useQuery({
    queryKey: ["repo", id],
    queryFn: () => api.getRepo(id!),
    enabled: !!id,
  });

  const servicesQuery = useQuery({
    queryKey: ["repo-services", id],
    queryFn: () => api.listServices({ repo_id: id, limit: 50 }),
    enabled: !!id,
  });

  const syncMutation = useMutation({
    mutationFn: () => api.triggerRepoSync(id!),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["repo", id] });
    },
  });

  const repo = repoQuery.data;
  const services = servicesQuery.data?.results ?? [];

  if (repoQuery.isLoading) {
    return (
      <div className="animate-enter space-y-5">
        <div className="h-6 w-48 animate-pulse rounded bg-bg-hover" />
        <div className="h-40 animate-pulse rounded-lg bg-bg-raised" />
        <CardGridSkeleton count={3} />
      </div>
    );
  }

  if (repoQuery.isError || !repo) {
    return (
      <div className="animate-enter">
        <EmptyState
          title="Repository not found"
          description="This repository may have been deleted or you don't have access."
          actionLabel="Back to repos"
          actionHref="/repos"
        />
      </div>
    );
  }

  return (
    <div className="animate-enter space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <Link to="/repos" className="text-[11px] text-t3 transition-colors hover:text-t2">
          Repos
        </Link>
        <span className="text-t3">/</span>
        <h1 className="font-mono text-sm font-medium text-t1">{repo.name}</h1>
      </div>

      {/* Metadata */}
      <div className="rounded-lg border border-line bg-bg-raised p-5">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-[13px] font-medium text-t1">Repository details</p>
          </div>
          <button
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
            className="rounded-md bg-accent/10 px-3 py-1.5 font-mono text-[11px] font-medium text-accent transition-colors hover:bg-accent/20 disabled:opacity-50"
          >
            {syncMutation.isPending ? "Syncing..." : "Trigger sync"}
          </button>
        </div>

        {syncMutation.isSuccess && (
          <p className="mt-2 text-[11px] text-green">Sync triggered successfully.</p>
        )}
        {syncMutation.isError && (
          <p className="mt-2 text-[11px] text-red">
            {(syncMutation.error as Error).message}
          </p>
        )}

        <div className="mt-4 grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-2">
          <MetaRow label="Git URL" value={repo.git_url} mono />
          <MetaRow label="Default branch" value={repo.default_branch} mono accent />
          <MetaRow label="Sync enabled" value={repo.sync_enabled ? "Yes" : "No"} />
          <MetaRow
            label="Last synced"
            value={repo.last_synced_at ? formatDate(repo.last_synced_at) : "Never"}
          />
          {repo.last_synced_commit && (
            <MetaRow label="Last commit" value={repo.last_synced_commit.slice(0, 8)} mono />
          )}
          {repo.spec_paths.length > 0 && (
            <MetaRow label="Spec paths" value={repo.spec_paths.join(", ")} mono />
          )}
          {repo.codeowners_path && (
            <MetaRow label="CODEOWNERS" value={repo.codeowners_path} mono />
          )}
          <MetaRow label="Created" value={formatDate(repo.created_at)} />
        </div>
      </div>

      {/* Services */}
      <div>
        <p className="mb-3 text-[13px] font-medium text-t2">
          Services <span className="text-t3">({services.length})</span>
        </p>

        {servicesQuery.isLoading ? (
          <CardGridSkeleton count={3} />
        ) : services.length === 0 ? (
          <EmptyState
            title="No services in this repository"
            description="Services are discovered during sync or can be registered manually."
            actionLabel="Go to services"
            actionHref="/services"
          />
        ) : (
          <div className="stagger grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {services.map((svc) => (
              <ServiceMiniCard key={svc.id} service={svc} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function MetaRow({
  label,
  value,
  mono,
  accent,
}: {
  label: string;
  value: string;
  mono?: boolean;
  accent?: boolean;
}) {
  return (
    <div className="flex items-baseline gap-3">
      <span className="w-28 shrink-0 text-[11px] text-t3">{label}</span>
      <span
        className={`truncate text-[11px] ${mono ? "font-mono text-[10px]" : ""} ${accent ? "text-accent" : "text-t2"}`}
      >
        {value}
      </span>
    </div>
  );
}

function ServiceMiniCard({ service }: { service: Service }) {
  return (
    <Link
      to={`/services/${service.id}`}
      className="group rounded-lg border border-line bg-bg-raised p-4 transition-colors hover:border-line-strong"
    >
      <p className="font-mono text-xs font-medium text-t1">{service.name}</p>
      <div className="mt-2 space-y-1 text-[11px]">
        <div className="flex items-center gap-2">
          <span className="w-8 shrink-0 text-t3">path</span>
          <span className="font-mono text-[10px] text-t2">{service.root_path}</span>
        </div>
        {service.otel_service_name && (
          <div className="flex items-center gap-2">
            <span className="w-8 shrink-0 text-t3">otel</span>
            <span className="font-mono text-[10px] text-accent">{service.otel_service_name}</span>
          </div>
        )}
        <div className="flex items-center gap-2">
          <span className="w-8 shrink-0 text-t3">assets</span>
          <span className="text-t2">{service.asset_count ?? 0}</span>
        </div>
      </div>
    </Link>
  );
}
