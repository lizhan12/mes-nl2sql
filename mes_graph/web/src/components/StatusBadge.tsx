import { AlertTriangle, CheckCircle2, LoaderCircle, ShieldAlert } from "lucide-react";

import { cn } from "@/lib/utils";

interface StatusBadgeProps {
  tone: "success" | "error" | "warning" | "loading" | "neutral";
  children: string;
}

const badgeStyle = {
  success: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200",
  error: "border-rose-400/30 bg-rose-400/10 text-rose-200",
  warning: "border-amber-400/30 bg-amber-400/10 text-amber-200",
  loading: "border-cyan-400/30 bg-cyan-400/10 text-cyan-200",
  neutral: "border-slate-400/20 bg-slate-400/10 text-slate-200",
};

const badgeIcon = {
  success: CheckCircle2,
  error: ShieldAlert,
  warning: AlertTriangle,
  loading: LoaderCircle,
  neutral: CheckCircle2,
};

export function StatusBadge({ tone, children }: StatusBadgeProps) {
  const Icon = badgeIcon[tone];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-2 rounded-full border px-3 py-1 text-xs font-medium tracking-[0.2em] uppercase",
        badgeStyle[tone],
      )}
    >
      <Icon className={cn("h-3.5 w-3.5", tone === "loading" ? "animate-spin" : "")} />
      {children}
    </span>
  );
}
