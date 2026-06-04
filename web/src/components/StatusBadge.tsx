import { AlertTriangle, CheckCircle2, Loader2, XCircle } from "lucide-react";

import { cn } from "@/lib/utils";

interface StatusBadgeProps {
  tone: "success" | "error" | "warning" | "loading" | "neutral";
  children: string;
}

const badgeVariant: Record<StatusBadgeProps["tone"], string> = {
  success: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
  error: "bg-red-500/10 text-red-400 border-red-500/20",
  warning: "bg-amber-500/10 text-amber-400 border-amber-500/20",
  loading: "bg-accent/10 text-accent-400 border-accent/20",
  neutral: "bg-white/5 text-text-secondary border-white/10",
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
        "inline-flex items-center gap-1.5 rounded-[6px] border px-2.5 py-0.5 font-mono text-[11px] font-medium tracking-wide",
        badgeVariant[tone],
      )}
    >
      <BadgeIcon tone={tone} />
      {children}
    </span>
  );
}
