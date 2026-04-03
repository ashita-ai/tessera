const BASE = "/api/v1";

interface PaginatedResponse<T> {
  results: T[];
  total: number;
  offset: number;
  limit: number;
}

export interface Service {
  id: string;
  name: string;
  owner_team_id: string;
  owner_team_name?: string;
  repo_url: string;
  spec_paths: string[];
  otel_service_name?: string;
  poll_interval_seconds: number;
  last_synced_at?: string;
  asset_count?: number;
  created_at: string;
}

export interface Asset {
  id: string;
  fqn: string;
  resource_type: string;
  environment: string;
  owner_team_id: string;
  owner_team_name?: string;
  owner_user_id?: string;
  owner_user_name?: string;
  service_id?: string;
  service_name?: string;
  active_contract_version?: string;
  active_contract_id?: string;
  created_at: string;
}

export interface Contract {
  id: string;
  asset_id: string;
  version: string;
  schema: Record<string, unknown>;
  compatibility_mode: string;
  status: "active" | "deprecated" | "retired";
  published_by: string;
  published_at: string;
  breaking_changes?: BreakingChange[];
}

export interface BreakingChange {
  kind: string;
  path: string;
  message: string;
  old_value?: unknown;
  new_value?: unknown;
}

export interface Proposal {
  id: string;
  asset_id: string;
  asset_fqn?: string;
  contract_id: string;
  proposed_version: string;
  change_type: string;
  breaking_changes_count: number;
  status: "pending" | "approved" | "rejected" | "expired" | "withdrawn";
  proposed_by: string;
  proposed_at: string;
  total_consumers: number;
  acknowledgment_count: number;
  acknowledgments?: Acknowledgment[];
}

export interface Acknowledgment {
  id: string;
  proposal_id: string;
  team_id: string;
  team_name?: string;
  response: "APPROVED" | "BLOCKED" | "MIGRATING";
  responded_by: string;
  responded_at: string;
  comment?: string;
}

export interface Team {
  id: string;
  name: string;
  created_at: string;
  asset_count?: number;
  member_count?: number;
}

export interface AuditEvent {
  id: string;
  entity_type: string;
  entity_id: string;
  action: string;
  actor_id?: string;
  actor_type: string;
  payload: Record<string, unknown>;
  created_at: string;
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
  services: number;
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
      services: await request<PaginatedResponse<Service>>("/services", {}, { limit: 1 })
        .then((r) => r.total)
        .catch(() => 0),
    };
  },

  // Services (future — these will call the endpoints from Spec-006)
  listServices: (params?: QueryParams) =>
    request<PaginatedResponse<Service>>("/services", {}, params),
  getService: (id: string) => request<Service>(`/services/${id}`),
  createService: (data: Partial<Service>) =>
    request<Service>("/services", { method: "POST", body: JSON.stringify(data) }),

  // Assets
  listAssets: (params?: QueryParams) =>
    request<PaginatedResponse<Asset>>("/assets", {}, params),
  getAsset: (id: string) => request<Asset>(`/assets/${id}`),

  // Contracts
  listContracts: (params?: QueryParams) =>
    request<PaginatedResponse<Contract>>("/contracts", {}, params),
  getContract: (id: string) => request<Contract>(`/contracts/${id}`),

  // Proposals
  listProposals: (params?: QueryParams) =>
    request<PaginatedResponse<Proposal>>("/proposals", {}, params),
  getProposal: (id: string) => request<Proposal>(`/proposals/${id}`),
  acknowledgeProposal: (id: string, data: { response: string; comment?: string }) =>
    request<Acknowledgment>(`/proposals/${id}/acknowledge`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  // Teams
  listTeams: (params?: QueryParams) =>
    request<PaginatedResponse<Team>>("/teams", {}, params),
  getTeam: (id: string) => request<Team>(`/teams/${id}`),

  // Dependencies
  listDependencies: (assetId: string, params?: QueryParams) =>
    request<PaginatedResponse<Dependency>>(`/assets/${assetId}/dependencies`, {}, params),

  // Audit
  listAuditEvents: (params?: QueryParams) =>
    request<PaginatedResponse<AuditEvent>>("/audit/events", {}, params),
};
