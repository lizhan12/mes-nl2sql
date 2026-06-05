import { ChevronLeft, ChevronRight, Loader2 } from "lucide-react";

interface PaginationBarProps {
  page: number;
  totalPages: number;
  totalRows: number;
  loading: boolean;
  onPageChange: (page: number) => void;
}

export function PaginationBar({ page, totalPages, totalRows, loading, onPageChange }: PaginationBarProps) {
  if (totalRows === 0) return null;

  return (
    <div className="flex items-center justify-center gap-2 pt-2">
      <button
        type="button"
        disabled={page <= 1 || loading}
        onClick={() => onPageChange(page - 1)}
        className="inline-flex items-center gap-1 rounded border border-[var(--border-default)] bg-[var(--bg-subtle)] px-2.5 py-1.5 font-mono text-[11px] text-[var(--text-secondary)] transition-all duration-150 hover:border-[var(--border-strong)] hover:text-[var(--text-primary)] disabled:pointer-events-none disabled:opacity-25"
      >
        <ChevronLeft className="h-3.5 w-3.5" />
        Prev
      </button>

      <span className="font-mono text-[11px] text-[var(--text-tertiary)] tabular-nums">
        {page} <span className="opacity-50">/</span> {totalPages}
        <span className="ml-1.5 opacity-40">{totalRows} rows</span>
      </span>

      <button
        type="button"
        disabled={page >= totalPages || loading}
        onClick={() => onPageChange(page + 1)}
        className="inline-flex items-center gap-1 rounded border border-[var(--border-default)] bg-[var(--bg-subtle)] px-2.5 py-1.5 font-mono text-[11px] text-[var(--text-secondary)] transition-all duration-150 hover:border-[var(--border-strong)] hover:text-[var(--text-primary)] disabled:pointer-events-none disabled:opacity-25"
      >
        Next
        <ChevronRight className="h-3.5 w-3.5" />
      </button>

      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-[var(--accent)]" />}
    </div>
  );
}
