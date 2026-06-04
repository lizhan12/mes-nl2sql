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
        className="inline-flex items-center gap-1 rounded-md border border-white/[0.08] bg-white/[0.02] px-2.5 py-1.5 text-[12px] text-text-secondary transition-colors duration-150 hover:border-white/15 hover:text-white disabled:pointer-events-none disabled:opacity-30"
      >
        <ChevronLeft className="h-3.5 w-3.5" />
        Prev
      </button>

      <span className="text-[12px] text-text-tertiary tabular-nums">
        {page} / {totalPages} <span className="text-text-tertiary/50">· {totalRows} rows</span>
      </span>

      <button
        type="button"
        disabled={page >= totalPages || loading}
        onClick={() => onPageChange(page + 1)}
        className="inline-flex items-center gap-1 rounded-md border border-white/[0.08] bg-white/[0.02] px-2.5 py-1.5 text-[12px] text-text-secondary transition-colors duration-150 hover:border-white/15 hover:text-white disabled:pointer-events-none disabled:opacity-30"
      >
        Next
        <ChevronRight className="h-3.5 w-3.5" />
      </button>

      {loading && <Loader2 className="h-3.5 w-3.5 animate-spin text-accent" />}
    </div>
  );
}
