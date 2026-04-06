import { Link, useNavigate, useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Contract } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import { DependencyGraph } from "@/components/graph/DependencyGraph";
import { GraphSkeleton, TableSkeleton } from "@/components/shared/Skeleton";
import { EmptyState } from "@/components/shared/EmptyState";

const TYPE_LABEL: Record<string, string> = {
  api_endpoint: "API Endpoint",
  grpc_service: "gRPC Service",
  graphql_query: "GraphQL Query",
  kafka_topic: "Kafka Topic",
  model: "Model",
  source: "Source",
};

const STATUS_STYLE: Record<string, string> = {
  active: "bg-green/10 text-green",
  deprecated: "bg-amber/10 text-amber",
  retired: "bg-red/10 text-red",
};

export function AssetDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();

  const assetQuery = useQuery({
    queryKey: ["asset", id],
    queryFn: () => api.getAsset(id!),
    enabled: !!id,
  });

  const contractsQuery = useQuery({
    queryKey: ["asset-contracts", id],
    queryFn: () => api.listAssetContracts(id!, { limit: 50 }),
    enabled: !!id,
  });

  const lineageQuery = useQuery({
    queryKey: ["asset-lineage", id],
    queryFn: () => api.getLineage(id!),
    enabled: !!id,
    retry: false,
  });

  // Build neighborhood graph from lineage data
  const graphQuery = useQuery({
    queryKey: ["asset-graph", id],
    queryFn: async () => {
      const lineage = await api.getLineage(id!);
      const nodeMap = new Map<string, { id: string; label: string; type: "asset"; team_name?: string }>();

      // Center node
      nodeMap.set(lineage.asset_id, {
        id: lineage.asset_id,
        label: lineage.asset_fqn.split(".").pop() ?? lineage.asset_fqn,
        type: "asset",
        team_name: lineage.owner_team_name,
      });

      const edges: { source: string; target: string; dependency_type: string }[] = [];

      for (const up of lineage.upstream) {
        nodeMap.set(up.asset_id, {
          id: up.asset_id,
          label: up.asset_fqn.split(".").pop() ?? up.asset_fqn,
          type: "asset",
          team_name: up.owner_team,
        });
        edges.push({
          source: lineage.asset_id,
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
          target: lineage.asset_id,
          dependency_type: down.dependency_type,
        });
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

  const asset = assetQuery.data;
  const contracts = contractsQuery.data?.results ?? [];
  const lineage = lineageQuery.data;

  if (assetQuery.isLoading) {
    return (
      <div className="animate-enter space-y-5">
        <div className="h-6 w-48 animate-pulse rounded bg-bg-hover" />
        <div className="h-40 animate-pulse rounded-lg bg-bg-raised" />
        <TableSkeleton />
      </div>
    );
  }

  if (assetQuery.isError || !asset) {
    return (
      <div className="animate-enter">
        <EmptyState
          title="Asset not found"
          description="This asset may have been deleted or you don't have access."
          actionLabel="Back to assets"
          actionHref="/assets"
        />
      </div>
    );
  }

  return (
    <div className="animate-enter space-y-5">
      {/* Breadcrumb */}
      <div className="flex items-center gap-3">
        <Link to="/assets" className="text-[11px] text-t3 transition-colors hover:text-t2">
          Assets
        </Link>
        <span className="text-t3">/</span>
        <h1 className="font-mono text-sm font-medium text-t1">{asset.fqn}</h1>
      </div>

      {/* Metadata */}
      <div className="rounded-lg border border-line bg-bg-raised p-5">
        <p className="text-[13px] font-medium text-t1">Asset details</p>
        <div className="mt-4 grid grid-cols-1 gap-x-8 gap-y-3 sm:grid-cols-2">
          <MetaRow label="FQN" value={asset.fqn} mono />
          <MetaRow label="Type" value={TYPE_LABEL[asset.resource_type] ?? asset.resource_type} />
          <MetaRow label="Environment" value={asset.environment} accent />
          <MetaRow label="Team" value={asset.owner_team_name ?? "\u2014"} />
          {asset.owner_user_name && (
            <MetaRow label="Owner" value={asset.owner_user_name} />
          )}
          {asset.repo_name && (
            <MetaRow label="Repository" value={asset.repo_name} mono link={`/repos/${asset.repo_id}`} />
          )}
          {asset.service_name && (
            <MetaRow label="Service" value={asset.service_name} mono link={`/services/${asset.service_id}`} />
          )}
          <MetaRow label="Guarantee" value={asset.guarantee_mode} mono />
          <MetaRow label="Semver" value={asset.semver_mode} mono />
          <MetaRow label="Created" value={formatDate(asset.created_at)} />
          {asset.updated_at && (
            <MetaRow label="Updated" value={formatDate(asset.updated_at)} />
          )}
        </div>
        {asset.tags.length > 0 && (
          <div className="mt-4 flex items-baseline gap-3">
            <span className="w-24 shrink-0 text-[11px] text-t3">Tags</span>
            <div className="flex flex-wrap gap-1.5">
              {asset.tags.map((tag) => (
                <span key={tag} className="rounded-full bg-accent/10 px-2 py-0.5 text-[10px] font-medium text-accent">
                  {tag}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Lineage summary */}
      {lineage && (lineage.upstream.length > 0 || lineage.downstream.length > 0 || lineage.downstream_assets.length > 0) && (
        <div className="rounded-lg border border-line bg-bg-raised">
          <div className="flex items-center justify-between border-b border-line px-4 py-2">
            <span className="text-[13px] font-medium text-t2">Dependency graph</span>
            <span className="text-[10px] text-t3">1-hop neighborhood</span>
          </div>
          <div className="h-[400px]">
            {graphQuery.isLoading ? (
              <GraphSkeleton />
            ) : !graphQuery.data || graphQuery.data.nodes.length <= 1 ? (
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

          {/* Upstream list */}
          {lineage.upstream.length > 0 && (
            <div className="border-t border-line px-4 py-3">
              <p className="mb-2 text-[11px] font-medium text-t3">
                Upstream ({lineage.upstream.length})
              </p>
              <div className="space-y-1">
                {lineage.upstream.map((up) => (
                  <div key={up.asset_id} className="flex items-center gap-3 text-[11px]">
                    <Link to={`/assets/${up.asset_id}`} className="font-mono text-[10px] text-accent hover:underline">
                      {up.asset_fqn}
                    </Link>
                    <span className="rounded bg-bg-surface px-1.5 py-0.5 text-[9px] text-t3">
                      {up.dependency_type}
                    </span>
                    <span className="text-t3">{up.owner_team}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Downstream assets */}
          {lineage.downstream_assets.length > 0 && (
            <div className="border-t border-line px-4 py-3">
              <p className="mb-2 text-[11px] font-medium text-t3">
                Downstream ({lineage.downstream_assets.length})
              </p>
              <div className="space-y-1">
                {lineage.downstream_assets.map((down) => (
                  <div key={down.asset_id} className="flex items-center gap-3 text-[11px]">
                    <Link to={`/assets/${down.asset_id}`} className="font-mono text-[10px] text-accent hover:underline">
                      {down.asset_fqn}
                    </Link>
                    <span className="rounded bg-bg-surface px-1.5 py-0.5 text-[9px] text-t3">
                      {down.dependency_type}
                    </span>
                    <span className="text-t3">{down.owner_team}</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Downstream consumer teams */}
          {lineage.downstream.length > 0 && (
            <div className="border-t border-line px-4 py-3">
              <p className="mb-2 text-[11px] font-medium text-t3">
                Consumer teams ({lineage.downstream.length})
              </p>
              <div className="space-y-1">
                {lineage.downstream.map((d) => (
                  <div key={d.team_id} className="flex items-center gap-3 text-[11px]">
                    <span className="text-t2">{d.team_name}</span>
                    <span className="text-[10px] text-t3">
                      {d.registrations.length} registration{d.registrations.length !== 1 ? "s" : ""}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Contract history */}
      <div>
        <p className="mb-3 text-[13px] font-medium text-t2">
          Contracts <span className="text-t3">({contracts.length})</span>
        </p>

        {contractsQuery.isLoading ? (
          <TableSkeleton />
        ) : contracts.length === 0 ? (
          <EmptyState
            title="No contracts published"
            description="Contracts are created when a schema is published via sync or the API."
            actionLabel="View all assets"
            actionHref="/assets"
          />
        ) : (
          <div className="overflow-hidden rounded-lg border border-line">
            <table className="w-full text-left text-[11px]">
              <thead>
                <tr className="border-b border-line bg-bg-raised text-t3">
                  <th className="px-4 py-2 font-medium">Version</th>
                  <th className="px-4 py-2 font-medium">Status</th>
                  <th className="px-4 py-2 font-medium">Format</th>
                  <th className="px-4 py-2 font-medium">Compatibility</th>
                  <th className="px-4 py-2 font-medium">Published by</th>
                  <th className="px-4 py-2 font-medium">Published</th>
                </tr>
              </thead>
              <tbody>
                {contracts.map((contract) => (
                  <ContractRow key={contract.id} contract={contract} />
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

function ContractRow({ contract }: { contract: Contract }) {
  return (
    <tr className="border-b border-line/50 transition-colors hover:bg-bg-hover">
      <td className="px-4 py-2">
        <span className="font-mono text-[11px] font-medium text-t1">v{contract.version}</span>
      </td>
      <td className="px-4 py-2">
        <span className={`rounded-full px-1.5 py-px text-[10px] font-medium ${STATUS_STYLE[contract.status] ?? "bg-bg-hover text-t3"}`}>
          {contract.status}
        </span>
      </td>
      <td className="px-4 py-2">
        <span className="font-mono text-[10px] text-t2">{contract.schema_format}</span>
      </td>
      <td className="px-4 py-2">
        <span className="font-mono text-[10px] text-t2">{contract.compatibility_mode}</span>
      </td>
      <td className="px-4 py-2 text-t2">
        {contract.publisher_name ?? "\u2014"}
      </td>
      <td className="px-4 py-2 text-t3">
        {formatDate(contract.published_at)}
      </td>
    </tr>
  );
}
