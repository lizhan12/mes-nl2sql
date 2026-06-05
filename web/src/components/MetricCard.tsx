import type { ReactNode } from "react";

interface MetricCardProps {
  label: string;
  value: string | number;
  hint?: string;
  icon: ReactNode;
}

export function MetricCard({ label, value, hint, icon }: MetricCardProps) {
  return (
    <div className="group relative overflow-hidden rounded-lg border border-[var(--border-default)] bg-[var(--bg-raised)] p-4 transition-all duration-300 hover:border-[var(--border-accent)] hover:shadow-[0_0_24px_var(--accent-glow)]">
      {/* Subtle top accent line on hover */}
      <div className="absolute inset-x-0 top-0 h-[1px] bg-gradient-to-r from-transparent via-[var(--accent)] to-transparent opacity-0 transition-opacity duration-300 group-hover:opacity-40" />

      <div className="mb-3 flex h-8 w-8 items-center justify-center rounded border border-[var(--border-default)] bg-[var(--bg-subtle)] text-[var(--accent)] transition-colors duration-300 group-hover:border-[var(--border-accent)] group-hover:bg-[var(--accent-surface)]">
        {icon}
      </div>
      <div className="font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-[var(--text-tertiary)]">
        {label}
      </div>
      <div className="mt-1 font-display text-[30px] font-semibold leading-none tracking-tight text-[var(--text-primary)] tabular-nums">
        {value}
      </div>
      {hint ? <div className="mt-2 text-[11px] text-[var(--text-tertiary)]">{hint}</div> : null}
    </div>
  );
}
