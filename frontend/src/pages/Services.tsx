import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/lib/api";
import type { Service } from "@/lib/api";
import { formatDate } from "@/lib/utils";

export function Services() {
  const [showRegister, setShowRegister] = useState(false);

  const servicesQuery = useQuery({
    queryKey: ["services"],
    queryFn: () => api.listServices({ limit: 50 }),
    retry: false,
  });

  const services = servicesQuery.data?.results ?? [];
  const isLoading = servicesQuery.isLoading;
  const isServiceEndpointMissing = servicesQuery.isError;

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-xl font-bold text-text-primary">
            Services
          </h1>
          <p className="mt-1 text-sm text-text-secondary">
            Registered services and their API specs
          </p>
        </div>
        <button
          onClick={() => setShowRegister(true)}
          className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-surface-0 transition-colors hover:bg-accent-glow"
        >
          Register Service
        </button>
      </div>

      {isServiceEndpointMissing ? (
        <div className="rounded-xl border border-border bg-surface-1 p-8 text-center">
          <p className="font-display text-lg font-semibold text-text-primary">
            Service endpoints not yet available
          </p>
          <p className="mt-2 text-sm text-text-muted">
            The service registry API (Spec-006) has not been implemented yet.
            <br />
            This page will populate once{" "}
            <span className="font-mono text-accent">POST /api/v1/services</span> is
            available.
          </p>
        </div>
      ) : isLoading ? (
        <div className="py-12 text-center text-sm text-text-muted">Loading...</div>
      ) : services.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface-1 p-8 text-center">
          <p className="text-sm text-text-muted">
            No services registered. Register your first service to get started.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {services.map((svc) => (
            <ServiceCard key={svc.id} service={svc} />
          ))}
        </div>
      )}

      {/* Register modal */}
      {showRegister && (
        <RegisterServiceModal onClose={() => setShowRegister(false)} />
      )}
    </div>
  );
}

function ServiceCard({ service }: { service: Service }) {
  return (
    <div className="group rounded-xl border border-border bg-surface-1 p-5 transition-all hover:border-border-strong hover:bg-surface-2">
      <div className="flex items-start justify-between">
        <div>
          <h3 className="font-mono text-sm font-semibold text-text-primary">
            {service.name}
          </h3>
          <p className="mt-0.5 text-2xs text-text-muted">
            {service.owner_team_name}
          </p>
        </div>
        {service.last_synced_at && (
          <span className="rounded-full bg-success/10 px-2 py-0.5 text-2xs font-medium text-success">
            synced
          </span>
        )}
      </div>

      <div className="mt-3 space-y-1.5 text-xs text-text-secondary">
        <div className="flex items-center gap-2">
          <span className="text-text-muted">repo</span>
          <span className="truncate font-mono text-2xs">{service.repo_url}</span>
        </div>
        {service.otel_service_name && (
          <div className="flex items-center gap-2">
            <span className="text-text-muted">otel</span>
            <span className="font-mono text-2xs text-accent">
              {service.otel_service_name}
            </span>
          </div>
        )}
        <div className="flex items-center gap-2">
          <span className="text-text-muted">assets</span>
          <span>{service.asset_count ?? 0}</span>
        </div>
      </div>

      {service.last_synced_at && (
        <p className="mt-3 text-2xs text-text-muted">
          Last synced {formatDate(service.last_synced_at)}
        </p>
      )}
    </div>
  );
}

function RegisterServiceModal({ onClose }: { onClose: () => void }) {
  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-surface-0/60 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="w-full max-w-lg rounded-xl border border-border bg-surface-1 p-6 shadow-2xl">
          <h2 className="font-display text-lg font-bold text-text-primary">
            Register Service
          </h2>
          <p className="mt-1 text-sm text-text-muted">
            Point Tessera at a git repository containing API specs.
          </p>

          <form className="mt-5 space-y-4" onSubmit={(e) => e.preventDefault()}>
            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                Service Name
              </label>
              <input
                type="text"
                placeholder="e.g., order-service"
                className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                Git Repository URL
              </label>
              <input
                type="text"
                placeholder="https://github.com/org/repo"
                className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                Spec File Paths
              </label>
              <input
                type="text"
                placeholder="api/openapi.yaml, proto/"
                className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
              />
              <p className="mt-1 text-2xs text-text-muted">
                Comma-separated paths to OpenAPI, protobuf, or GraphQL specs
              </p>
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-text-secondary">
                OTEL Service Name (optional)
              </label>
              <input
                type="text"
                placeholder="order-service"
                className="w-full rounded-lg border border-border bg-surface-2 px-3 py-2 font-mono text-sm text-text-primary placeholder:text-text-muted focus:border-accent focus:outline-none"
              />
              <p className="mt-1 text-2xs text-text-muted">
                Matches the service.name attribute in your OTEL traces
              </p>
            </div>

            <div className="flex justify-end gap-3 pt-2">
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg border border-border px-4 py-2 text-sm text-text-secondary hover:bg-surface-2"
              >
                Cancel
              </button>
              <button
                type="submit"
                className="rounded-lg bg-accent px-4 py-2 text-sm font-medium text-surface-0 hover:bg-accent-glow"
              >
                Register
              </button>
            </div>
          </form>
        </div>
      </div>
    </>
  );
}
