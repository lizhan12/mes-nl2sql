import { Database } from "lucide-react";

export default function Empty() {
  return (
    <div className="flex flex-col items-center justify-center gap-3 py-16">
      <div className="flex h-12 w-12 items-center justify-center rounded-full border border-[var(--border-default)] bg-[var(--bg-subtle)]">
        <Database className="h-5 w-5 text-[var(--text-tertiary)]" />
      </div>
      <p className="font-mono text-[11px] uppercase tracking-[0.06em] text-[var(--text-tertiary)]">
        暂无数据
      </p>
    </div>
  );
}
