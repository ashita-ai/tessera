import { cn } from "@/lib/utils";

function Pulse({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "animate-pulse rounded-md bg-bg-hover",
        className,
      )}
    />
  );
}

export function CardSkeleton() {
  return (
    <div className="rounded-lg border border-line bg-bg-raised p-4">
      <div className="flex items-start justify-between">
        <Pulse className="h-4 w-32" />
        <Pulse className="h-4 w-12 rounded-full" />
      </div>
      <Pulse className="mt-3 h-3 w-20" />
      <div className="mt-4 space-y-2">
        <Pulse className="h-3 w-full" />
        <Pulse className="h-3 w-3/4" />
        <Pulse className="h-3 w-1/2" />
      </div>
    </div>
  );
}

export function CardGridSkeleton({ count = 6 }: { count?: number }) {
  return (
    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
      {Array.from({ length: count }, (_, i) => (
        <CardSkeleton key={i} />
      ))}
    </div>
  );
}

export function GraphSkeleton() {
  return (
    <div className="flex h-[520px] items-center justify-center">
      <div className="flex flex-col items-center gap-3">
        <div className="relative h-16 w-16">
          <Pulse className="absolute left-0 top-0 h-5 w-5 rounded-full" />
          <Pulse className="absolute right-0 top-0 h-5 w-5 rounded-full" />
          <Pulse className="absolute bottom-0 left-1/2 h-5 w-5 -translate-x-1/2 rounded-full" />
        </div>
        <p className="text-[11px] text-t3">Loading graph…</p>
      </div>
    </div>
  );
}

export function TableSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2">
      <Pulse className="h-8 w-full rounded" />
      {Array.from({ length: rows }, (_, i) => (
        <Pulse key={i} className="h-10 w-full rounded" />
      ))}
    </div>
  );
}
