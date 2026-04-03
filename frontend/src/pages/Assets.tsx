import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/utils";

const TYPE_LABEL: Record<string, string> = {
  api_endpoint: "api",
  grpc_service: "grpc",
  graphql_query: "graphql",
  kafka_topic: "kafka",
  model: "model",
  source: "source",
};

export function Assets() {
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState("");

  const assetsQuery = useQuery({
    queryKey: ["assets", search, typeFilter],
    queryFn: () =>
      api.listAssets({
        limit: 50,
        ...(search ? { fqn: search } : {}),
        ...(typeFilter ? { resource_type: typeFilter } : {}),
      }),
  });

  const assets = assetsQuery.data?.results ?? [];
  const total = assetsQuery.data?.total ?? 0;

  return (
    <div className="animate-enter space-y-5">
      <h1 className="text-sm font-medium text-t2">Assets</h1>

      {/* Filters */}
      <div className="flex gap-2">
        <input
          type="text"
          placeholder="Search by FQN..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 rounded-md border border-line bg-bg-raised px-3 py-1.5 font-mono text-xs text-t1 placeholder:text-t3 focus:border-accent/40 focus:outline-none"
        />
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="rounded-md border border-line bg-bg-raised px-3 py-1.5 text-xs text-t2 focus:border-accent/40 focus:outline-none"
        >
          <option value="">All types</option>
          <option value="api_endpoint">API Endpoint</option>
          <option value="grpc_service">gRPC Service</option>
          <option value="graphql_query">GraphQL</option>
          <option value="kafka_topic">Kafka Topic</option>
          <option value="model">Model</option>
          <option value="source">Source</option>
        </select>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-lg border border-line bg-bg-raised">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-line text-left">
              <th className="px-4 py-2.5 text-[10px] font-medium uppercase tracking-widest text-t3">FQN</th>
              <th className="px-4 py-2.5 text-[10px] font-medium uppercase tracking-widest text-t3">Type</th>
              <th className="px-4 py-2.5 text-[10px] font-medium uppercase tracking-widest text-t3">Team</th>
              <th className="px-4 py-2.5 text-[10px] font-medium uppercase tracking-widest text-t3">Contract</th>
              <th className="px-4 py-2.5 text-[10px] font-medium uppercase tracking-widest text-t3">Updated</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line/40">
            {assets.map((asset) => (
              <tr key={asset.id} className="transition-colors hover:bg-bg-hover">
                <td className="px-4 py-2.5">
                  <span className="font-mono text-[11px] font-medium text-t1">{asset.fqn}</span>
                </td>
                <td className="px-4 py-2.5">
                  <span className="rounded bg-bg-surface px-1.5 py-0.5 font-mono text-[10px] text-t2">
                    {TYPE_LABEL[asset.resource_type] ?? asset.resource_type}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-[11px] text-t3">
                  {asset.owner_team_name ?? "\u2014"}
                </td>
                <td className="px-4 py-2.5">
                  {asset.active_contract_version ? (
                    <span className="font-mono text-[11px] text-accent">v{asset.active_contract_version}</span>
                  ) : (
                    <span className="text-[10px] text-t3">none</span>
                  )}
                </td>
                <td className="px-4 py-2.5 text-[11px] text-t3">
                  {formatDate(asset.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {assets.length === 0 && (
          <div className="py-12 text-center text-[11px] text-t3">
            {assetsQuery.isLoading ? "Loading..." : "No assets found"}
          </div>
        )}

        {total > 0 && (
          <div className="border-t border-line px-4 py-2 text-[10px] text-t3">
            {assets.length} of {total}
          </div>
        )}
      </div>
    </div>
  );
}
