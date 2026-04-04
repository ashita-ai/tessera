import { Link } from "react-router-dom";

interface Props {
  icon?: React.ReactNode;
  title: string;
  description: string;
  actionLabel?: string;
  actionHref?: string;
  onAction?: () => void;
}

export function EmptyState({ icon, title, description, actionLabel, actionHref, onAction }: Props) {
  return (
    <div className="rounded-lg border border-line bg-bg-raised px-6 py-10 text-center">
      {icon && <div className="mx-auto mb-4 text-t3">{icon}</div>}
      <p className="text-[13px] text-t2">{title}</p>
      <p className="mx-auto mt-1.5 max-w-xs text-[11px] text-t3">{description}</p>
      {actionLabel && (actionHref ? (
        <Link
          to={actionHref}
          className="mt-4 inline-block rounded-md bg-accent/10 px-3 py-1.5 font-mono text-[11px] font-medium text-accent transition-colors hover:bg-accent/20"
        >
          {actionLabel}
        </Link>
      ) : onAction ? (
        <button
          onClick={onAction}
          className="mt-4 rounded-md bg-accent/10 px-3 py-1.5 font-mono text-[11px] font-medium text-accent transition-colors hover:bg-accent/20"
        >
          {actionLabel}
        </button>
      ) : null)}
    </div>
  );
}
