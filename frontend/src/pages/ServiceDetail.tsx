import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Asset } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { DependencyGraph } from "@/components/graph/DependencyGraph";
import { GraphSkeleton, TableSkeleton } from "@/components/shared/Skeleton";
import { EmptyState } from "@/components/shared/EmptyState";

export function ServiceDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const serviceQuery = useQuery({
    queryKey: ["service", id],
    queryFn: () => api.getService(id!),
    enabled: !!id,
  });

  const assetsQuery = useQuery({
    queryKey: ["service-assets", id],
    queryFn: () => api.listServiceAssets(id!, { limit: 50 }),
    enabled: !!id,
  });

  // Build neighborhood graph from service's assets + their dependencies
  const graphQuery = useQuery({
    queryKey: ["service-graph", id],
    queryFn: async () => {
      const assetsResp = await api.listServiceAssets(id!, { limit: 100 });
      const assets = assetsResp.results;
      if (assets.length === 0) return { nodes: [], edges: [] };

      // Fetch lineage for each asset to build the neighborhood
      const lineages = await Promise.all(
        assets.map((a) => api.getLineage(a.id).catch(() => null)),
      );

      const nodeMap = new Map<string, { id: string; label: string; type: "asset"; team_id?: string; team_name?: string; resource_type?: string }>();
      const edges: { source: string; target: string; dependency_type: string }[] = [];

      for (let i = 0; i < assets.length; i++) {
        const asset = assets[i];
        nodeMap.set(asset.id, {
          id: asset.id,
          label: asset.fqn.split(".").pop() ?? asset.fqn,
          type: "asset",
          team_id: asset.owner_team_id,
          team_name: asset.owner_team_name,
          resource_type: asset.resource_type,
        });

        const lineage = lineages[i];
        if (!lineage) continue;

        for (const up of lineage.upstream) {
          nodeMap.set(up.asset_id, {
            id: up.asset_id,
            label: up.asset_fqn.split(".").pop() ?? up.asset_fqn,
            type: "asset",
            team_name: up.owner_team,
          });
          edges.push({
            source: asset.id,
            target: up.asset_id,
            dependency_type: up.dependency_type,
          });
        }

        for (const down of lineage.downstream_assets) {
          nodeMap.set(down.asset_id, {
            id: down.asset_id,
            label: down.asset_fqn.split(".").pop() ?? down.asset_fqn,
            type: "asset",
            team_name: down.owner_team,
          });
          edges.push({
            source: down.asset_id,
            target: asset.id,
            dependency_type: down.dependency_type,
          });
        }
      }

      return {
        nodes: Array.from(nodeMap.values()).map((n) => ({
          ...n,
          has_breaking_proposal: false,
          sync_status: "synced" as const,
        })),
        edges,
      };
    },
    enabled: !!id,
    retry: false,
  });

  const service = serviceQuery.data;
  const assets = assetsQuery.data?.results ?? [];

  if (serviceQuery.isLoading) {
    return (
      <div className="animate-enter space-y-5">
        <div className="h-6 w-48 animate-pulse rounded bg-bg-hover" />
        <div className="h-40 animate-pulse rounded-lg bg-bg-raised" />
        <TableSkeleton />
      </div>
    );
  }

  if (serviceQuery.isError || !service) {
    return (
      <div className="animate-enter">
        <EmptyState
          title="Service not found"
          description="This service may have been deleted or you don't have access."
          actionLabel="Back to services"
          actionHref="/services"
        />
      </div>
    );
  }

  return (
    <div className="animate-enter space-y-5">
      {/* Breadcrumb */}
      <div className="flex items-center gap-3">
        <Link to="/services" className="text-[11px] text-t3 transition-colors hover:text-t2">
          Services
        </Link>
        <span className="text-t3">/</span>
        <h1 className="font-mono text-sm font-medium text-t1">{service.name}</h1>
      </div>

      {/* Metadata */}
      <div className="rounded-lg border border-line bg-bg-raised p-5">
        <p className="text-[13px] font-medium text-t1">Service details</p>
        <div className="mt-4 grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-2">
          <MetaRow label="Repository" value={service.repo_id} mono link={`/repos/${service.repo_id}`} />
          <MetaRow label="Root path" value={service.root_path} mono />
          {service.otel_service_name && (
            <MetaRow label="OTEL name" value={service.otel_service_name} mono accent />
          )}
          <MetaRow label="Assets" value={String(service.asset_count ?? 0)} />
          <MetaRow label="Created" value={formatDate(service.created_at)} />
        </div>
      </div>

      {/* Neighborhood graph */}
      <div className="overflow-hidden rounded-lg border border-line bg-bg-raised">
        <div className="flex items-center justify-between border-b border-line px-4 py-2">
          <span className="text-[13px] font-medium text-t2">Neighborhood graph</span>
          <span className="text-[10px] text-t3">1-hop dependencies</span>
        </div>
        <div className="h-[400px]">
          {graphQuery.isLoading ? (
            <GraphSkeleton />
          ) : !graphQuery.data || graphQuery.data.nodes.length === 0 ? (
            <div className="flex h-full items-center justify-center">
              <p className="text-[11px] text-t3">No dependencies discovered yet</p>
            </div>
          ) : (
            <DependencyGraph
              graphData={graphQuery.data}
              onNodeClick={(nodeId) => navigate(`/assets/${nodeId}`)}
            />
          )}
        </div>
      </div>

      {/* Asset list */}
      <div>
        <p className="mb-3 text-[13px] font-medium text-t2">
          Assets <span className="text-t3">({assets.length})</span>
        </p>

        {assetsQuery.isLoading ? (
          <TableSkeleton />
        ) : assets.length === 0 ? (
          <EmptyState
            title="No assets in this service"
            description="Assets are created during spec sync or can be registered via the API."
            actionLabel="View all assets"
            actionHref="/assets"
          />
        ) : (
          <div className="overflow-hidden rounded-lg border border-line">
            <table className="w-full text-left text-[11px]">
              <thead>
                <tr className="border-b border-line bg-bg-raised text-t3">
                  <th className="px-4 py-2 font-medium">FQN</th>
                  <th className="px-4 py-2 font-medium">Type</th>
                  <th className="px-4 py-2 font-medium">Environment</th>
                  <th className="px-4 py-2 font-medium">Updated</th>
                </tr>
              </thead>
              <tbody>
                {assets.map((asset) => (
                  <AssetRow key={asset.id} asset={asset} />
                ))}
              </tbody>
            </table>
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
  link,
}: {
  label: string;
  value: string;
  mono?: boolean;
  accent?: boolean;
  link?: string;
}) {
  const textClass = `truncate text-[11px] ${mono ? "font-mono text-[10px]" : ""} ${accent ? "text-accent" : "text-t2"}`;
  return (
    <div className="flex items-baseline gap-3">
      <span className="w-24 shrink-0 text-[11px] text-t3">{label}</span>
      {link ? (
        <Link to={link} className={`${textClass} hover:text-accent`}>
          {value}
        </Link>
      ) : (
        <span className={textClass}>{value}</span>
      )}
    </div>
  );
}

const TYPE_COLORS: Record<string, string> = {
  api: "bg-blue-500/10 text-blue-400",
  grpc: "bg-violet-500/10 text-violet-400",
  graphql: "bg-purple-500/10 text-purple-400",
  kafka: "bg-rose-500/10 text-rose-400",
  model: "bg-amber/8 text-amber",
  source: "bg-green/10 text-green",
};

function AssetRow({ asset }: { asset: Asset }) {
  return (
    <tr className="border-b border-line/50 transition-colors hover:bg-bg-hover">
      <td className="px-4 py-2">
        <Link to={`/assets/${asset.id}`} className="font-mono text-[10px] text-accent hover:underline">
          {asset.fqn}
        </Link>
      </td>
      <td className="px-4 py-2">
        <span
          className={`rounded-full px-1.5 py-px text-[10px] font-medium ${TYPE_COLORS[asset.resource_type] ?? "bg-bg-hover text-t3"}`}
        >
          {asset.resource_type}
        </span>
      </td>
      <td className="px-4 py-2 text-t2">{asset.environment}</td>
      <td className="px-4 py-2 text-t3">
        {asset.updated_at ? formatDate(asset.updated_at) : formatDate(asset.created_at)}
      </td>
    </tr>
  );
}
