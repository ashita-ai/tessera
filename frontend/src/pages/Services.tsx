import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
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
  const isError = servicesQuery.isError;

  return (
    <div className="animate-enter space-y-5">
      <div className="flex items-center justify-between">
        <h1 className="text-sm font-medium text-t2">Services</h1>
        <button
          onClick={() => setShowRegister(true)}
          className="rounded-md bg-accent/10 px-3 py-1.5 font-mono text-[11px] font-medium text-accent transition-colors hover:bg-accent/20"
        >
          Register
        </button>
      </div>

      {isError ? (
        <div className="rounded-lg border border-line bg-bg-raised px-6 py-10 text-center">
          <p className="text-[13px] text-t2">Service registry not available</p>
          <p className="mt-1.5 text-[11px] text-t3">
            <span className="font-mono text-accent">POST /api/v1/services</span> endpoint has not been implemented yet.
          </p>
        </div>
      ) : isLoading ? (
        <div className="py-16 text-center text-[11px] text-t3">Loading...</div>
      ) : services.length === 0 ? (
        <div className="rounded-lg border border-line bg-bg-raised px-6 py-10 text-center">
          <p className="text-[11px] text-t3">No services registered</p>
        </div>
      ) : (
        <div className="stagger grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {services.map((svc) => (
            <ServiceCard key={svc.id} service={svc} />
          ))}
        </div>
      )}

      {showRegister && (
        <RegisterModal onClose={() => setShowRegister(false)} />
      )}
    </div>
  );
}

function ServiceCard({ service }: { service: Service }) {
  return (
    <div className="group rounded-lg border border-line bg-bg-raised p-4 transition-colors hover:border-line-strong">
      <div className="flex items-start justify-between">
        <p className="font-mono text-xs font-medium text-t1">{service.name}</p>
        {service.last_synced_at && (
          <span className="rounded-full bg-green/10 px-1.5 py-px text-[10px] font-medium text-green">
            synced
          </span>
        )}
      </div>
      {service.owner_team_name && (
        <p className="mt-0.5 text-[10px] text-t3">{service.owner_team_name}</p>
      )}

      <div className="mt-3 space-y-1 text-[11px]">
        <div className="flex items-center gap-2">
          <span className="w-8 shrink-0 text-t3">repo</span>
          <span className="truncate font-mono text-[10px] text-t2">{service.repo_url}</span>
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

      {service.last_synced_at && (
        <p className="mt-3 border-t border-line/50 pt-2 text-[10px] text-t3">
          Synced {formatDate(service.last_synced_at)}
        </p>
      )}
    </div>
  );
}

function RegisterModal({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [repoUrl, setRepoUrl] = useState("");
  const [specPaths, setSpecPaths] = useState("");
  const [otelName, setOtelName] = useState("");
  const [error, setError] = useState<string | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      api.createService({
        name,
        repo_url: repoUrl,
        spec_paths: specPaths.split(",").map((s) => s.trim()).filter(Boolean),
        otel_service_name: otelName || undefined,
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["services"] });
      onClose();
    },
    onError: (err: Error) => setError(err.message),
  });

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!name.trim() || !repoUrl.trim()) {
      setError("Service name and repository URL are required.");
      return;
    }
    mutation.mutate();
  };

  return (
    <>
      <div className="fixed inset-0 z-40 bg-bg/70 backdrop-blur-sm" onClick={onClose} />
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
        <div className="w-full max-w-md rounded-lg border border-line bg-bg-raised p-5 shadow-2xl">
          <p className="text-[13px] font-medium text-t1">Register service</p>
          <p className="mt-1 text-[11px] text-t3">Point Tessera at a git repository containing API specs.</p>

          <form className="mt-4 space-y-3" onSubmit={handleSubmit}>
            <Field label="Service name" placeholder="e.g., order-service" value={name} onChange={setName} />
            <Field label="Git repository URL" placeholder="https://github.com/org/repo" value={repoUrl} onChange={setRepoUrl} />
            <Field label="Spec file paths" placeholder="api/openapi.yaml, proto/" hint="Comma-separated paths to OpenAPI, protobuf, or GraphQL specs" value={specPaths} onChange={setSpecPaths} />
            <Field label="OTEL service name" placeholder="order-service" hint="Matches the service.name attribute in your OTEL traces" value={otelName} onChange={setOtelName} />

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

function Field({ label, placeholder, hint, value, onChange }: { label: string; placeholder: string; hint?: string; value: string; onChange: (v: string) => void }) {
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
