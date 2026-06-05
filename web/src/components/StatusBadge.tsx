import { AlertTriangle, CheckCircle2, Loader2, XCircle } from "lucide-react";

import { cn } from "@/lib/utils";

interface StatusBadgeProps {
  tone: "success" | "error" | "warning" | "loading" | "neutral";
  children: string;
}

const badgeVariant: Record<StatusBadgeProps["tone"], string> = {
  success:
    "bg-[var(--success)]/10 text-[var(--success)] border-[var(--success)]/20",
  error: "bg-[var(--error)]/10 text-[var(--error)] border-[var(--error)]/20",
  warning:
    "bg-[var(--warning)]/10 text-[var(--warning)] border-[var(--warning)]/20",
  loading:
    "bg-[var(--accent-soft)] text-[var(--accent)] border-[var(--border-accent)]",
  neutral:
    "bg-[var(--bg-subtle)] text-[var(--text-secondary)] border-[var(--border-default)]",
};

const BadgeIcon = ({ tone }: { tone: StatusBadgeProps["tone"] }) => {
  const cls = "h-3 w-3";
  switch (tone) {
    case "success":
      return <CheckCircle2 className={cls} />;
    case "error":
      return <XCircle className={cls} />;
    case "warning":
      return <AlertTriangle className={cls} />;
    case "loading":
      return <Loader2 className={cn(cls, "animate-spin")} />;
    case "neutral":
      return <CheckCircle2 className={cls} />;
  }
};

export function StatusBadge({ tone, children }: StatusBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded border px-2 py-0.5 font-mono text-[10px] font-medium uppercase tracking-[0.04em]",
        badgeVariant[tone],
      )}
    >
      <BadgeIcon tone={tone} />
      {children}
    </span>
  );
}
