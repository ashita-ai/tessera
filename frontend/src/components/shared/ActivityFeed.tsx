import { formatDate, cn } from "@/lib/utils";

export interface ActivityItem {
  id: string;
  action: string;
  entity: string;
  entityType: string;
  actor: string;
  actorType: "human" | "agent";
  timestamp: string;
  severity?: "info" | "warning" | "danger";
}

const DOT: Record<string, string> = {
  info: "bg-accent",
  warning: "bg-amber",
  danger: "bg-red",
};

export function ActivityFeed({ items, className }: { items: ActivityItem[]; className?: string }) {
  if (!items.length) {
    return <p className={cn("py-6 text-center text-xs text-t3", className)}>No recent activity</p>;
  }

  return (
    <div className={cn("space-y-0", className)}>
      {items.map((item) => (
        <div key={item.id} className="flex items-start gap-3 py-2.5">
          <div className={cn("mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full", DOT[item.severity ?? "info"])} />
          <div className="min-w-0">
            <p className="text-[13px] text-t2">
              {item.action}{" "}
              <span className="font-mono text-xs text-accent">{item.entity}</span>
            </p>
            <p className="mt-0.5 text-[11px] text-t3">
              {item.actor}
              {item.actorType === "agent" && (
                <span className="ml-1 rounded-sm bg-accent-dim px-1 py-px font-mono text-[10px] text-accent">bot</span>
              )}
              {" \u00b7 "}
              {formatDate(item.timestamp)}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
