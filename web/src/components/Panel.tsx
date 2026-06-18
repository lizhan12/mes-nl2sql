import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

interface PanelProps {
  title: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}

export function Panel({ title, subtitle, action, children, className }: PanelProps) {
  return (
    <section
      className={cn(
        "relative rounded-lg border border-[var(--border-default)] bg-[var(--bg-raised)] p-5",
        className,
      )}
    >
      {/* Corner accent line */}
      <div
        className="pointer-events-none absolute inset-0 rounded-lg opacity-[0.06]"
        style={{
          border: "1px solid transparent",
          borderImage: `linear-gradient(135deg, var(--accent) 0%, transparent 40%, transparent 60%, var(--accent) 100%) 1`,
        }}
      />

      <div className="relative z-10 mb-4 flex items-start justify-between gap-4">
        <div>
          <h2 className="font-display text-sm font-semibold uppercase tracking-[0.06em] text-[var(--text-primary)]">
            {title}
          </h2>
          {subtitle ? (
            <p className="mt-1 text-[12px] leading-relaxed text-[var(--text-tertiary)]">{subtitle}</p>
          ) : null}
        </div>
        {action}
      </div>
      <div className="relative z-10">{children}</div>
    </section>
  );
}
