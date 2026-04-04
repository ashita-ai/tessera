const BASE = "/api/v1";

interface PaginatedResponse<T> {
  results: T[];
  total: number;
  offset: number;
  limit: number;
}

export interface Repo {
  id: string;
  name: string;
  git_url: string;
  default_branch: string;
  spec_paths: string[];
  owner_team_id: string;
  sync_enabled: boolean;
  codeowners_path?: string;
  last_synced_at?: string;
  last_synced_commit?: string;
  created_at: string;
  updated_at?: string;
  services_count?: number;
}

export interface Service {
  id: string;
  name: string;
  repo_id: string;
  root_path: string;
  otel_service_name?: string;
  owner_team_id: string;
  created_at: string;
  updated_at?: string;
  asset_count?: number;
}

export interface Asset {
  id: string;
  fqn: string;
  resource_type: string;
  environment: string;
  guarantee_mode: string;
  semver_mode: string;
  owner_team_id: string;
  owner_team_name?: string;
  owner_user_id?: string;
  owner_user_name?: string;
  owner_user_email?: string;
  active_contract_version?: string;
  metadata: Record<string, unknown>;
  tags: string[];
  created_at: string;
  updated_at?: string;
}

export interface Contract {
  id: string;
  asset_id: string;
  asset_fqn?: string;
  version: string;
  schema_def: Record<string, unknown>;
  schema_format: string;
  compatibility_mode: string;
  guarantees?: Record<string, unknown>;
  field_descriptions: Record<string, string>;
  field_tags: Record<string, string[]>;
  status: "active" | "deprecated" | "retired";
  published_by: string;
  publisher_name?: string;
  published_by_user_id?: string;
  published_at: string;
  updated_at?: string;
}

export interface Proposal {
  id: string;
  asset_id: string;
  asset_fqn?: string;
  change_type: string;
  breaking_changes_count: number;
  status: "pending" | "approved" | "published" | "rejected" | "expired" | "withdrawn";
  proposed_by: string;
  proposed_at: string;
  total_consumers: number;
  acknowledgment_count: number;
}

export interface Acknowledgment {
  id: string;
  proposal_id: string;
  consumer_team_id: string;
  response: "approved" | "blocked" | "migrating";
  migration_deadline?: string;
  notes?: string;
  acknowledged_by_user_id?: string;
}

export interface Team {
  id: string;
  name: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at?: string;
  asset_count?: number;
}

export interface AuditEvent {
  id: string;
  entity_type: string;
  entity_id: string;
  action: string;
  actor_id?: string;
  actor_type: string;
  payload: Record<string, unknown>;
  occurred_at: string;
}

export interface Dependency {
  id: string;
  dependent_asset_id: string;
  dependent_asset_fqn?: string;
  dependency_asset_id: string;
  dependency_asset_fqn?: string;
  dependency_type: "CONSUMES" | "REFERENCES" | "TRANSFORMS";
  confidence?: number;
  source?: "manual" | "otel" | "inferred";
}

export interface DashboardStats {
  teams: number;
  assets: number;
  contracts: number;
  pending_proposals: number;
}

export interface GraphNode {
  id: string;
  label: string;
  type: "service" | "asset";
  team_id?: string;
  team_name?: string;
  resource_type?: string;
  has_breaking_proposal?: boolean;
  sync_status?: "synced" | "pending" | "error" | "never";
}

export interface GraphEdge {
  source: string;
  target: string;
  dependency_type: string;
  confidence?: number;
  source_label?: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface Lineage {
  asset_id: string;
  asset_fqn: string;
  owner_team_id: string;
  owner_team_name: string;
  upstream: { asset_id: string; asset_fqn: string; dependency_type: string; owner_team: string }[];
  downstream: { team_id: string; team_name: string; registrations: { contract_id: string; status: string; pinned_version?: string }[] }[];
  downstream_assets: { asset_id: string; asset_fqn: string; dependency_type: string; owner_team: string }[];
}


type QueryParams = Record<string, string | number | boolean | undefined>;

async function request<T>(
  path: string,
  options: RequestInit = {},
  params?: QueryParams,
): Promise<T> {
  const url = new URL(`${BASE}${path}`, window.location.origin);
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) {
        url.searchParams.set(key, String(value));
      }
    }
  }

  const response = await fetch(url.toString(), {
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
  });

  if (response.status === 401) {
    window.location.href = "/login";
    throw new Error("Unauthorized — redirecting to login");
  }

  if (!response.ok) {
    const body = await response.json().catch(() => null);
    throw new Error(
      body?.detail ?? `Request failed: ${response.status} ${response.statusText}`,
    );
  }

  if (response.status === 204) return undefined as T;
  return response.json();
}

export const api = {
  // Dashboard
  async getStats(): Promise<DashboardStats> {
    const [teams, assets, contracts, proposals] = await Promise.all([
      request<PaginatedResponse<Team>>("/teams", {}, { limit: 1 }),
      request<PaginatedResponse<Asset>>("/assets", {}, { limit: 1 }),
      request<PaginatedResponse<Contract>>("/contracts", {}, { limit: 1 }),
      request<PaginatedResponse<Proposal>>("/proposals", {}, { status: "pending", limit: 1 }),
    ]);
    return {
      teams: teams.total,
      assets: assets.total,
      contracts: contracts.total,
      pending_proposals: proposals.total,
    };
  },

  // Repos
  listRepos: (params?: QueryParams) =>
    request<PaginatedResponse<Repo>>("/repos", {}, params),
  getRepo: (id: string) => request<Repo>(`/repos/${id}`),
  createRepo: (data: { name: string; git_url: string; owner_team_id: string; default_branch?: string; spec_paths?: string[]; codeowners_path?: string; sync_enabled?: boolean }) =>
    request<Repo>("/repos", { method: "POST", body: JSON.stringify(data) }),
  triggerRepoSync: (id: string) =>
    request<{ status: string; message: string }>(`/repos/${id}/sync`, { method: "POST" }),

  // Services
  listServices: (params?: QueryParams) =>
    request<PaginatedResponse<Service>>("/services", {}, params),
  getService: (id: string) => request<Service>(`/services/${id}`),
  listServiceAssets: (id: string, params?: QueryParams) =>
    request<PaginatedResponse<Asset>>(`/services/${id}/assets`, {}, params),
  createService: (data: { name: string; repo_id: string; owner_team_id: string; root_path?: string; otel_service_name?: string }) =>
    request<Service>("/services", { method: "POST", body: JSON.stringify(data) }),

  // Assets
  listAssets: (params?: QueryParams) =>
    request<PaginatedResponse<Asset>>("/assets", {}, params),
  getAsset: (id: string) => request<Asset>(`/assets/${id}`),

  // Proposals
  listProposals: (params?: QueryParams) =>
    request<PaginatedResponse<Proposal>>("/proposals", {}, params),
  getProposal: (id: string) => request<Proposal>(`/proposals/${id}`),
  acknowledgeProposal: (id: string, data: { response: "approved" | "blocked" | "migrating"; consumer_team_id: string; notes?: string }) =>
    request<Acknowledgment>(`/proposals/${id}/acknowledge`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Teams
  listTeams: (params?: QueryParams) =>
    request<PaginatedResponse<Team>>("/teams", {}, params),
  getTeam: (id: string) => request<Team>(`/teams/${id}`),
  createTeam: (data: { name: string; metadata?: Record<string, unknown> }) =>
    request<Team>("/teams", { method: "POST", body: JSON.stringify(data) }),

  // Dependencies & Lineage
  listDependencies: (assetId: string, params?: QueryParams) =>
    request<PaginatedResponse<Dependency>>(`/assets/${assetId}/dependencies`, {}, params),
  getLineage: (assetId: string) =>
    request<Lineage>(`/assets/${assetId}/lineage`),

  // Audit
  listAuditEvents: (params?: QueryParams) =>
    request<PaginatedResponse<AuditEvent>>("/audit/events", {}, params),

  // Graph — aggregates assets + dependencies into a renderable graph
  async getGraphData(): Promise<GraphData> {
    const [assets, proposals] = await Promise.all([
      request<PaginatedResponse<Asset>>("/assets", {}, { limit: 200 }),
      request<PaginatedResponse<Proposal>>("/proposals", {}, { status: "pending", limit: 200 }),
    ]);

    const breakingAssetIds = new Set(
      proposals.results
        .filter((p) => p.breaking_changes_count > 0)
        .map((p) => p.asset_id),
    );

    const nodes: GraphNode[] = assets.results.map((a) => ({
      id: a.id,
      label: a.fqn.split(".").pop() ?? a.fqn,
      type: "asset" as const,
      team_id: a.owner_team_id,
      team_name: a.owner_team_name,
      resource_type: a.resource_type,
      has_breaking_proposal: breakingAssetIds.has(a.id),
      sync_status: "synced" as const,
    }));

    // Fetch dependencies for all assets in parallel (batched)
    const depResults = await Promise.all(
      assets.results.map((a) =>
        request<PaginatedResponse<Dependency>>(`/assets/${a.id}/dependencies`, {}, { limit: 100 })
          .catch(() => ({ results: [] as Dependency[], total: 0, offset: 0, limit: 100 })),
      ),
    );

    const edges: GraphEdge[] = [];
    const seen = new Set<string>();
    for (const depPage of depResults) {
      for (const dep of depPage.results) {
        const key = `${dep.dependent_asset_id}->${dep.dependency_asset_id}`;
        if (!seen.has(key)) {
          seen.add(key);
          edges.push({
            source: dep.dependent_asset_id,
            target: dep.dependency_asset_id,
            dependency_type: dep.dependency_type,
            confidence: dep.confidence,
            source_label: dep.source,
          });
        }
      }
    }

    return { nodes, edges };
  },
};
