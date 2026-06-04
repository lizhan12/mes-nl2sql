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
      <div className="flex items-center justify-between border-b border-[var(--border-default)] px-4 py-2.5">
        <span className="text-[12px] font-medium tracking-[0.04em] text-[var(--text-secondary)] uppercase">{title}</span>
        <button
          type="button"
          onClick={handleCopy}
          className={cn(
            "inline-flex items-center gap-1.5 rounded-md border border-[var(--border-default)] px-2.5 py-1 text-[12px] transition-colors duration-150",
            copied
              ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
              : "bg-[var(--bg-overlay)] text-[var(--text-tertiary)] hover:border-[var(--border-strong)] hover:text-[var(--text-secondary)]",
          )}
        >
          {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          {copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre
        className={cn(
          "overflow-auto whitespace-pre-wrap break-all px-4 py-3.5 font-mono text-[14px] leading-relaxed text-[var(--text-secondary)]",
          maxHeightClassName,
        )}
      >
        <code>{content}</code>
      </pre>
    </div>
  );
}
