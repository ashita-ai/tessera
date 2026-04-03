import { cn } from "@/lib/utils";

interface Props {
  label: string;
  value: string | number;
  alert?: boolean;
  href?: string;
}

export function StatCard({ label, value, alert, href }: Props) {
  const Tag = href ? "a" : "div";
  return (
    <Tag
      {...(href ? { href } : {})}
      className={cn(
        "rounded-lg border px-4 py-3 transition-colors",
        alert
          ? "border-red/20 bg-red-dim"
          : "border-line bg-bg-raised hover:border-line-strong",
      )}
    >
      <p className="text-[11px] font-medium uppercase tracking-widest text-t3">{label}</p>
      <p className={cn(
        "mt-1 font-mono text-xl font-semibold",
        alert ? "text-red" : "text-t1",
      )}>
        {value}
      </p>
    </Tag>
  );
}
