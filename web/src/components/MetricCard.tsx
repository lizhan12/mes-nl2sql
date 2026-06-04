import type { ReactNode } from "react";

interface MetricCardProps {
  label: string;
  value: string | number;
  hint?: string;
  icon: ReactNode;
}

export function MetricCard({ label, value, hint, icon }: MetricCardProps) {
  return (
    <div className="rounded-lg border border-white/[0.06] bg-[#111] p-4 hover:border-accent-border transition-colors duration-200">
      <div className="mb-3 flex h-9 w-9 items-center justify-center rounded-md border border-white/[0.08] bg-white/[0.04] text-text-secondary">
        {icon}
      </div>
      <div className="text-[11px] font-medium tracking-[0.04em] text-text-tertiary uppercase">{label}</div>
      <div className="mt-1.5 text-[28px] font-semibold tracking-tight text-white tabular-nums">{value}</div>
      {hint ? <div className="mt-2 text-[12px] text-text-tertiary">{hint}</div> : null}
    </div>
  );
}
