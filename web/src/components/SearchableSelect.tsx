import { useEffect, useRef, useState } from "react";

export interface SearchableSelectOption {
  value: string;
  label: string;
  hint?: string;
}

interface SearchableSelectProps {
  options: SearchableSelectOption[];
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  className?: string;
}

/**
 * 可搜索的下拉选择器。
 * 输入关键字过滤选项列表，点击选中后回填到输入框。
 */
export function SearchableSelect({
  options,
  value,
  onChange,
  placeholder = "输入搜索...",
  className = "",
}: SearchableSelectProps) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  // 点击外部关闭
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  const filtered = query
    ? options.filter(
        (o) =>
          o.value.toLowerCase().includes(query.toLowerCase()) ||
          o.label.toLowerCase().includes(query.toLowerCase()) ||
          (o.hint && o.hint.toLowerCase().includes(query.toLowerCase())),
      )
    : options;

  const selected = options.find((o) => o.value === value);

  return (
    <div ref={containerRef} className={`relative ${className}`}>
      <input
        ref={inputRef}
        type="text"
        value={open ? query : (selected?.label ?? value)}
        placeholder={placeholder}
        onFocus={() => {
          setOpen(true);
          setQuery("");
        }}
        onChange={(e) => {
          setQuery(e.target.value);
          if (!open) setOpen(true);
        }}
        onBlur={() => {
          // 延迟关闭，让 onClick 有时间触发
          setTimeout(() => setOpen(false), 150);
        }}
        className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-raised)] px-2 py-1.5 font-mono text-xs text-[var(--text-primary)] outline-none focus:ring-1 focus:ring-[var(--accent)]"
      />
      {open && filtered.length > 0 && (
        <ul
          className="absolute z-[9999] mt-1 max-h-48 w-full overflow-auto rounded border border-[var(--border-default)] bg-[var(--bg-raised)] shadow-lg"
        >
          {filtered.map((o) => (
            <li
              key={o.value}
              onMouseDown={(e) => {
                e.preventDefault();
                onChange(o.value);
                setOpen(false);
                setQuery("");
              }}
              className={`flex cursor-pointer items-center gap-2 px-2 py-1.5 text-xs hover:bg-[var(--bg-subtle)] ${
                o.value === value ? "bg-[var(--bg-subtle)] font-medium text-[var(--accent)]" : "text-[var(--text-primary)]"
              }`}
            >
              <span className="font-mono">{o.label}</span>
              {o.hint && <span className="truncate text-[10px] text-[var(--text-tertiary)]">{o.hint}</span>}
            </li>
          ))}
        </ul>
      )}
      {open && filtered.length === 0 && (
        <div
          className="absolute z-[9999] mt-1 w-full rounded border border-[var(--border-default)] bg-[var(--bg-raised)] px-2 py-2 text-center text-[10px] text-[var(--text-tertiary)] shadow-lg"
        >
          无匹配项
        </div>
      )}
    </div>
  );
}
