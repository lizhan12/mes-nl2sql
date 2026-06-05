import { Check, Copy } from "lucide-react";
import { useMemo, useState } from "react";

import { cn } from "@/lib/utils";

interface CodeBlockProps {
  title: string;
  value: unknown;
  language?: "sql" | "json" | "text";
  maxHeightClassName?: string;
}

function stringifyValue(value: unknown, language: CodeBlockProps["language"]) {
  if (typeof value === "string") {
    return value.trim() || "(空)";
  }
  if (language === "json") {
    return JSON.stringify(value ?? {}, null, 2);
  }
  return JSON.stringify(value ?? {}, null, 2);
}

export function CodeBlock({ title, value, language = "text", maxHeightClassName = "max-h-72" }: CodeBlockProps) {
  const [copied, setCopied] = useState(false);
  const content = useMemo(() => stringifyValue(value, language), [language, value]);

  async function handleCopy() {
    await navigator.clipboard.writeText(content);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  }

  return (
    <div className="rounded-lg border border-[var(--border-default)] bg-[var(--bg-overlay)] overflow-hidden">
      {/* Header bar — terminal style */}
      <div className="flex items-center justify-between border-b border-[var(--border-default)] bg-[var(--bg-subtle)] px-4 py-2">
        <div className="flex items-center gap-2">
          <span className="h-1.5 w-1.5 rounded-full bg-[var(--accent)] opacity-60" />
          <span className="font-mono text-[10px] font-medium uppercase tracking-[0.08em] text-[var(--text-tertiary)]">
            {title}
          </span>
        </div>
        <button
          type="button"
          onClick={handleCopy}
          className={cn(
            "inline-flex items-center gap-1 rounded border border-[var(--border-default)] px-2 py-0.5 font-mono text-[10px] transition-all duration-150",
            copied
              ? "border-[var(--success)]/30 bg-[var(--success)]/10 text-[var(--success)]"
              : "bg-transparent text-[var(--text-tertiary)] hover:border-[var(--border-strong)] hover:text-[var(--text-secondary)]",
          )}
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          {copied ? "已复制" : "复制"}
        </button>
      </div>
      {/* Code area */}
      <pre
        className={cn(
          "overflow-auto whitespace-pre-wrap break-all px-4 py-3 font-mono text-[13px] leading-relaxed text-[var(--text-secondary)]",
          maxHeightClassName,
        )}
      >
        <code>{content}</code>
      </pre>
    </div>
  );
}
