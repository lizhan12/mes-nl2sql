import { Search } from "lucide-react";

interface EmptyProps {
  message: string;
}

export default function Empty({ message }: EmptyProps) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-[var(--text-tertiary)]">
      <Search className="mb-3 h-8 w-8 opacity-30" />
      <span className="text-sm">{message}</span>
    </div>
  );
}
