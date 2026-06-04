import { Copy, CopyCheck } from "lucide-react";
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
    window.setTimeout(() => setCopied(false), 1200);
  }

  return (
    <div className="rounded-2xl border border-white/10 bg-slate-900/85">
      <div className="flex items-center justify-between border-b border-white/10 px-4 py-3">
        <div className="font-['Rajdhani'] text-sm tracking-[0.2em] text-slate-300 uppercase">{title}</div>
        <button
          type="button"
          onClick={handleCopy}
          className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-xs text-slate-200 transition hover:border-cyan-300/30 hover:bg-cyan-300/10"
        >
          {copied ? <CopyCheck className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
          {copied ? "已复制" : "复制"}
        </button>
      </div>
      <pre
        className={cn(
          "overflow-auto whitespace-pre-wrap break-all px-4 py-4 text-sm leading-6 text-slate-100 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent",
          maxHeightClassName,
        )}
      >
        <code>{content}</code>
      </pre>
    </div>
  );
}
