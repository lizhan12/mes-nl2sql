import { ChevronDown, ChevronUp } from "lucide-react";
import { type ReactNode, useState } from "react";

interface PanelProps {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
  action?: ReactNode;
}

export function Panel({ title, children, defaultOpen = true, action }: PanelProps) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="mb-1 overflow-hidden rounded border border-[var(--border-default)] bg-[var(--bg-default)]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center justify-between px-3 py-1.5 text-left font-mono text-[10px] font-semibold uppercase tracking-[0.06em] text-[var(--text-secondary)] hover:bg-[var(--bg-subtle)]"
      >
        <span>{title}</span>
        <div className="flex items-center gap-2">
          {action}
          {open ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
        </div>
      </button>
      {open && <div className="border-t border-[var(--border-default)] px-3 py-2">{children}</div>}
    </div>
  );
}
