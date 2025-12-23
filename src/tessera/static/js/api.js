/**
 * Tessera API Client
 * Minimalist JavaScript client for the Tessera API
 */

const API_BASE = '/api/v1';

class TesseraAPI {
  constructor() {
    this.baseUrl = API_BASE;
  }

  async request(endpoint, options = {}) {
    const url = `${this.baseUrl}${endpoint}`;
    const config = {
      headers: {
        'Content-Type': 'application/json',
        ...options.headers,
      },
      ...options,
    };

    try {
      const response = await fetch(url, config);

      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new APIError(
          error.message || `HTTP ${response.status}`,
          response.status,
          error.code
        );
      }

      if (response.status === 204) {
        return null;
      }

      return response.json();
    } catch (error) {
      if (error instanceof APIError) {
        throw error;
      }
      throw new APIError(error.message, 0, 'NETWORK_ERROR');
    }
  }

  // Teams
  async listTeams(params = {}) {
    const query = new URLSearchParams(params).toString();
    return this.request(`/teams${query ? `?${query}` : ''}`);
  }

  async getTeam(id) {
    return this.request(`/teams/${id}`);
  }

  async createTeam(data) {
    return this.request('/teams', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updateTeam(id, data) {
    return this.request(`/teams/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async deleteTeam(id) {
    return this.request(`/teams/${id}`, {
      method: 'DELETE',
    });
  }

  // Assets
  async listAssets(params = {}) {
    const query = new URLSearchParams(params).toString();
    return this.request(`/assets${query ? `?${query}` : ''}`);
  }

  async getAsset(id) {
    return this.request(`/assets/${id}`);
  }

  async createAsset(data) {
    return this.request('/assets', {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async updateAsset(id, data) {
    return this.request(`/assets/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(data),
    });
  }

  async deleteAsset(id) {
    return this.request(`/assets/${id}`, {
      method: 'DELETE',
    });
  }

  // Contracts
  async listContracts(params = {}) {
    const query = new URLSearchParams(params).toString();
    return this.request(`/contracts${query ? `?${query}` : ''}`);
  }

  async getContract(id) {
    return this.request(`/contracts/${id}`);
  }

  async publishContract(assetId, data, publishedBy) {
    return this.request(`/assets/${assetId}/contracts?published_by=${publishedBy}`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async getAssetContracts(assetId) {
    return this.request(`/assets/${assetId}/contracts`);
  }

  // Registrations
  async listRegistrations(params = {}) {
    const query = new URLSearchParams(params).toString();
    return this.request(`/registrations${query ? `?${query}` : ''}`);
  }

  async createRegistration(contractId, data) {
    return this.request(`/registrations?contract_id=${contractId}`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  async deleteRegistration(id) {
    return this.request(`/registrations/${id}`, {
      method: 'DELETE',
    });
  }

  // Proposals
  async listProposals(params = {}) {
    const query = new URLSearchParams(params).toString();
    return this.request(`/proposals${query ? `?${query}` : ''}`);
  }

  async getProposal(id) {
    return this.request(`/proposals/${id}`);
  }

  async getProposalStatus(id) {
    return this.request(`/proposals/${id}/status`);
  }

  async acknowledgeProposal(id, teamId) {
    return this.request(`/proposals/${id}/acknowledge?team_id=${teamId}`, {
      method: 'POST',
    });
  }

  async forceApproveProposal(id, actorId) {
    return this.request(`/proposals/${id}/force?actor_id=${actorId}`, {
      method: 'POST',
    });
  }

  async withdrawProposal(id) {
    return this.request(`/proposals/${id}/withdraw`, {
      method: 'POST',
    });
  }

  // Dependencies
  async getAssetDependencies(assetId) {
    return this.request(`/assets/${assetId}/dependencies`);
  }

  async createDependency(assetId, data) {
    return this.request(`/assets/${assetId}/dependencies`, {
      method: 'POST',
      body: JSON.stringify(data),
    });
  }

  // Impact Analysis
  async analyzeImpact(assetId, schema) {
    return this.request(`/assets/${assetId}/impact`, {
      method: 'POST',
      body: JSON.stringify({ schema }),
    });
  }

  // Health
  async health() {
    return this.request('/health');
  }

  async healthReady() {
    return this.request('/health/ready');
  }
}

class APIError extends Error {
  constructor(message, status, code) {
    super(message);
    this.name = 'APIError';
    this.status = status;
    this.code = code;
  }
}

// Global API instance
const api = new TesseraAPI();

// Utility functions
function formatDate(dateString) {
  if (!dateString) return '-';
  const date = new Date(dateString);
  return date.toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

function truncate(str, length = 50) {
  if (!str) return '';
  return str.length > length ? str.substring(0, length) + '...' : str;
}

function escapeHtml(str) {
  if (!str) return '';
  const div = document.createElement('div');
  div.textContent = str;
  return div.innerHTML;
}

function showError(message) {
  const container = document.getElementById('error-container');
  if (container) {
    container.innerHTML = `<div class="error">${escapeHtml(message)}</div>`;
    container.style.display = 'block';
    setTimeout(() => {
      container.style.display = 'none';
    }, 5000);
  }
}

function showLoading(elementId) {
  const el = document.getElementById(elementId);
  if (el) {
    el.innerHTML = '<div class="loading">Loading...</div>';
  }
}

function showEmpty(elementId, message = 'No data found') {
  const el = document.getElementById(elementId);
  if (el) {
    el.innerHTML = `<div class="empty">${escapeHtml(message)}</div>`;
  }
}
