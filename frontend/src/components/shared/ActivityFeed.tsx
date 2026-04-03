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

interface Props {
  items: ActivityItem[];
  className?: string;
}

const SEVERITY_DOT: Record<string, string> = {
  info: "bg-accent",
  warning: "bg-warning",
  danger: "bg-danger",
};

export function ActivityFeed({ items, className }: Props) {
  if (items.length === 0) {
    return (
      <div className={cn("py-8 text-center text-sm text-text-muted", className)}>
        No recent activity
      </div>
    );
  }

  return (
    <div className={cn("space-y-0", className)}>
      {items.map((item, i) => (
        <div
          key={item.id}
          className="group flex items-start gap-3 border-b border-border/50 px-1 py-3 last:border-0"
          style={{ animationDelay: `${i * 60}ms` }}
        >
          {/* Timeline dot */}
          <div className="mt-1.5 flex flex-col items-center">
            <div
              className={cn(
                "h-2 w-2 rounded-full",
                SEVERITY_DOT[item.severity ?? "info"],
              )}
            />
          </div>

          {/* Content */}
          <div className="min-w-0 flex-1">
            <p className="text-sm text-text-primary">
              <span className="font-medium">{item.action}</span>{" "}
              <span className="font-mono text-xs text-accent">{item.entity}</span>
            </p>
            <p className="mt-0.5 text-2xs text-text-muted">
              {item.actor}
              {item.actorType === "agent" && (
                <span className="ml-1 rounded-sm bg-accent/10 px-1 py-px text-accent">
                  agent
                </span>
              )}
              <span className="mx-1">&middot;</span>
              {formatDate(item.timestamp)}
            </p>
          </div>
        </div>
      ))}
    </div>
  );
}
