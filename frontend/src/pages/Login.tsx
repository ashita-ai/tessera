import { useState } from "react";
import { useSearchParams } from "react-router-dom";

export function Login() {
  const [searchParams] = useSearchParams();
  const error = searchParams.get("error");
  const [submitting, setSubmitting] = useState(false);

  return (
    <div className="flex min-h-screen items-center justify-center bg-bg px-4">
      <div className="w-full max-w-sm">
        <div className="mb-8 text-center">
          <img src="/static/images/logo.png" alt="Tessera" className="mx-auto h-8" />
        </div>

        <div className="rounded-lg border border-line bg-bg-raised p-6">
          <h2 className="mb-5 text-center text-sm font-medium text-t1">Sign in</h2>

          {error && (
            <div className="mb-4 rounded-md border border-red/20 bg-red-dim px-3 py-2 text-[11px] text-red">
              Invalid username or password.
            </div>
          )}

          <form
            method="POST"
            action="/login"
            onSubmit={() => setSubmitting(true)}
            className="space-y-3"
          >
            <div>
              <label htmlFor="username" className="mb-1 block text-[11px] font-medium text-t2">
                Username
              </label>
              <input
                type="text"
                id="username"
                name="username"
                required
                autoFocus
                autoComplete="username"
                placeholder="Username"
                className="w-full rounded-md border border-line bg-bg-surface px-3 py-2 font-mono text-xs text-t1 placeholder:text-t3 focus:border-accent/40 focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="password" className="mb-1 block text-[11px] font-medium text-t2">
                Password
              </label>
              <input
                type="password"
                id="password"
                name="password"
                required
                autoComplete="current-password"
                placeholder="Password"
                className="w-full rounded-md border border-line bg-bg-surface px-3 py-2 font-mono text-xs text-t1 placeholder:text-t3 focus:border-accent/40 focus:outline-none"
              />
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="w-full rounded-md bg-accent/10 px-3 py-2 text-xs font-medium text-accent transition-colors hover:bg-accent/20 disabled:opacity-50"
            >
              {submitting ? "Signing in..." : "Sign in"}
            </button>
          </form>
        </div>
      </div>
    </div>
  );
}
