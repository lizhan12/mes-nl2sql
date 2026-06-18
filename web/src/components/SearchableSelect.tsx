import { Search } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

export interface SearchableSelectOption {
  value: string;
  label: string;
}

interface SearchableSelectProps {
  value: string;
  onChange: (value: string) => void;
  options: SearchableSelectOption[];
  placeholder?: string;
  disabled?: boolean;
}

export function SearchableSelect({ value, onChange, options, placeholder = "搜索...", disabled }: SearchableSelectProps) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    if (!search) return options;
    const s = search.toLowerCase();
    return options.filter((o) => o.label.toLowerCase().includes(s) || o.value.toLowerCase().includes(s));
  }, [options, search]);

  const selected = options.find((o) => o.value === value);

  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, []);

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        disabled={disabled}
        onClick={() => {
          if (!disabled) {
            setOpen((v) => !v);
            setSearch("");
            setTimeout(() => inputRef.current?.focus(), 0);
          }
        }}
        className="flex w-full items-center justify-between rounded border border-[var(--border-default)] bg-[var(--bg-input)] px-2 py-1.5 text-left text-xs text-[var(--text-primary)] disabled:cursor-not-allowed disabled:opacity-50"
      >
        <span className={selected ? "" : "text-[var(--text-tertiary)]"}>
          {selected?.label ?? placeholder}
        </span>
        <span className="ml-1 text-[10px] text-[var(--text-tertiary)]">▼</span>
      </button>
      {open && (
        <div className="absolute z-50 mt-1 max-h-48 w-full overflow-y-auto rounded border border-[var(--border-default)] bg-[var(--bg-raised)] shadow-lg">
          <div className="sticky top-0 border-b border-[var(--border-default)] bg-[var(--bg-raised)] px-2 py-1">
            <div className="relative">
              <Search className="pointer-events-none absolute left-1.5 top-1/2 h-3 w-3 -translate-y-1/2 text-[var(--text-tertiary)]" />
              <input
                ref={inputRef}
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索..."
                className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-input)] py-1 pl-6 pr-2 text-[11px] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent)] focus:outline-none"
              />
            </div>
          </div>
          {filtered.length === 0 ? (
            <div className="px-2 py-3 text-center text-[11px] text-[var(--text-tertiary)]">无匹配选项</div>
          ) : (
            filtered.map((opt) => (
              <button
                key={opt.value}
                type="button"
                className="w-full px-2 py-1.5 text-left text-xs text-[var(--text-primary)] hover:bg-[var(--bg-subtle)]"
                onClick={() => {
                  onChange(opt.value);
                  setOpen(false);
                  setSearch("");
                }}
              >
                {opt.label}
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}
