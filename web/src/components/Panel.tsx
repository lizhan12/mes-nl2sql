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
        "rounded-xl border border-white/[0.07] bg-[#141414] p-6",
        className,
      )}
    >
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-semibold tracking-tight text-white">{title}</h2>
          {subtitle ? <p className="mt-1 text-[13px] leading-relaxed text-text-tertiary">{subtitle}</p> : null}
        </div>
        {action}
      </div>
      {children}
    </section>
  );
}
