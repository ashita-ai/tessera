import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/utils";

const TYPE_BADGES: Record<string, { bg: string; text: string; label: string }> = {
  api_endpoint: { bg: "bg-blue-500/10", text: "text-blue-400", label: "api" },
  grpc_service: { bg: "bg-violet-500/10", text: "text-violet-400", label: "grpc" },
  graphql_query: { bg: "bg-purple-500/10", text: "text-purple-400", label: "graphql" },
  kafka_topic: { bg: "bg-rose-500/10", text: "text-rose-400", label: "kafka" },
  model: { bg: "bg-sky-500/10", text: "text-sky-400", label: "model" },
  source: { bg: "bg-amber-500/10", text: "text-amber-400", label: "source" },
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
    <div className="space-y-6">
      <div>
        <h1 className="font-display text-xl font-bold text-text-primary">Assets</h1>
        <p className="mt-1 text-sm text-text-secondary">
          API endpoints, gRPC services, GraphQL operations, and other contract-bearing resources
        </p>
      </div>

      {/* Filters */}
      <div className="flex gap-3">
        <input
          type="text"
          placeholder="Search by FQN..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 rounded-lg border border-border bg-surface-1 px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
        />
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="rounded-lg border border-border bg-surface-1 px-3 py-2 text-sm text-text-secondary focus:border-accent focus:outline-none"
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

      {/* Results */}
      <div className="overflow-hidden rounded-xl border border-border bg-surface-1">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs font-medium uppercase tracking-wider text-text-muted">
              <th className="px-5 py-3">FQN</th>
              <th className="px-5 py-3">Type</th>
              <th className="px-5 py-3">Team</th>
              <th className="px-5 py-3">Contract</th>
              <th className="px-5 py-3">Updated</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border/50">
            {assets.map((asset) => {
              const badge = TYPE_BADGES[asset.resource_type] ?? {
                bg: "bg-slate-500/10",
                text: "text-slate-400",
                label: asset.resource_type,
              };
              return (
                <tr
                  key={asset.id}
                  className="transition-colors hover:bg-surface-2"
                >
                  <td className="px-5 py-3">
                    <span className="font-mono text-xs font-medium text-text-primary">
                      {asset.fqn}
                    </span>
                  </td>
                  <td className="px-5 py-3">
                    <span
                      className={`inline-block rounded-md px-2 py-0.5 text-2xs font-medium ${badge.bg} ${badge.text}`}
                    >
                      {badge.label}
                    </span>
                  </td>
                  <td className="px-5 py-3 text-xs text-text-secondary">
                    {asset.owner_team_name ?? "\u2014"}
                  </td>
                  <td className="px-5 py-3">
                    {asset.active_contract_version ? (
                      <span className="font-mono text-xs text-accent">
                        v{asset.active_contract_version}
                      </span>
                    ) : (
                      <span className="text-2xs text-text-muted">none</span>
                    )}
                  </td>
                  <td className="px-5 py-3 text-xs text-text-muted">
                    {formatDate(asset.created_at)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {assets.length === 0 && (
          <div className="py-12 text-center text-sm text-text-muted">
            {assetsQuery.isLoading ? "Loading..." : "No assets found"}
          </div>
        )}
        {total > 0 && (
          <div className="border-t border-border px-5 py-2.5 text-xs text-text-muted">
            Showing {assets.length} of {total}
          </div>
        )}
      </div>
    </div>
  );
}
