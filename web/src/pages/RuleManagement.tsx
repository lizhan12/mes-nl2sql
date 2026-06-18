import { Edit3, Plus, Save, Trash2, X } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { createRuntimeRule, deleteRuntimeRule, fetchRuntimeRules, updateRuntimeRule } from "@/lib/api";
import type { RuntimeRuleItem } from "@/types";

export default function RuleManagement() {
  const [items, setItems] = useState<RuntimeRuleItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [showForm, setShowForm] = useState(false);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const [normalizedQuestion, setNormalizedQuestion] = useState("");
  const [preferredMainTable, setPreferredMainTable] = useState("");
  const [requiredTablesStr, setRequiredTablesStr] = useState("");
  const [requiredJoinsStr, setRequiredJoinsStr] = useState("");
  const [source, setSource] = useState("manual");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchRuntimeRules();
      setItems(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function openCreate() {
    setEditingKey(null);
    setQuestion("");
    setNormalizedQuestion("");
    setPreferredMainTable("");
    setRequiredTablesStr("");
    setRequiredJoinsStr("");
    setSource("manual");
    setFormError("");
    setShowForm(true);
  }

  function openEdit(item: RuntimeRuleItem) {
    setEditingKey(item.normalized_question);
    setQuestion(item.question);
    setNormalizedQuestion(item.normalized_question);
    setPreferredMainTable(item.preferred_main_table);
    setRequiredTablesStr(item.required_tables.join(", "));
    setRequiredJoinsStr(item.required_joins.join(", "));
    setSource(item.source);
    setFormError("");
    setShowForm(true);
  }

  function closeForm() {
    setShowForm(false);
    setEditingKey(null);
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!question.trim() || !normalizedQuestion.trim()) {
      setFormError("问题与规范化问题必填");
      return;
    }
    setFormError("");
    setSaving(true);
    const requiredTables = requiredTablesStr.split(",").map((s) => s.trim()).filter(Boolean);
    const requiredJoins = requiredJoinsStr.split(",").map((s) => s.trim()).filter(Boolean);
    try {
      if (editingKey) {
        await updateRuntimeRule(editingKey, question.trim(), preferredMainTable.trim(), requiredTables, requiredJoins, source);
      } else {
        await createRuntimeRule(question.trim(), normalizedQuestion.trim(), preferredMainTable.trim(), requiredTables, requiredJoins, source);
      }
      closeForm();
      await load();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(key: string) {
    if (!confirm(`确定删除该规则吗？`)) return;
    try {
      await deleteRuntimeRule(key);
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "删除失败");
    }
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-[var(--border-default)] px-4 py-3">
        <h2 className="font-display text-sm font-semibold text-[var(--text-primary)]">运行时规则管理</h2>
        <button
          type="button"
          onClick={openCreate}
          className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90"
        >
          <Plus className="h-3.5 w-3.5" />
          新增
        </button>
      </div>

      {error && (
        <div className="mx-4 mt-3 rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      )}

      {showForm && (
        <div className="mx-4 mt-3 rounded border border-[var(--border-default)] bg-[var(--bg-default)] p-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-xs font-semibold text-[var(--text-primary)]">
              {editingKey ? "编辑规则" : "新增规则"}
            </h3>
            <button type="button" onClick={closeForm} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)]">
              <X className="h-4 w-4" />
            </button>
          </div>
          <form onSubmit={handleSave} className="space-y-3">
            <div>
              <label className="mb-1 block text-[11px] text-[var(--text-secondary)]">自然语言问题</label>
              <input
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-input)] px-2 py-1.5 text-xs focus:border-[var(--accent)] focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-[var(--text-secondary)]">规范化问题</label>
              <input
                type="text"
                value={normalizedQuestion}
                onChange={(e) => setNormalizedQuestion(e.target.value)}
                className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-input)] px-2 py-1.5 text-xs focus:border-[var(--accent)] focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-[var(--text-secondary)]">推荐主表</label>
              <input
                type="text"
                value={preferredMainTable}
                onChange={(e) => setPreferredMainTable(e.target.value)}
                className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-input)] px-2 py-1.5 text-xs focus:border-[var(--accent)] focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-[var(--text-secondary)]">必需表（逗号分隔）</label>
              <input
                type="text"
                value={requiredTablesStr}
                onChange={(e) => setRequiredTablesStr(e.target.value)}
                className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-input)] px-2 py-1.5 text-xs focus:border-[var(--accent)] focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-[var(--text-secondary)]">必需 JOIN（逗号分隔）</label>
              <input
                type="text"
                value={requiredJoinsStr}
                onChange={(e) => setRequiredJoinsStr(e.target.value)}
                className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-input)] px-2 py-1.5 text-xs focus:border-[var(--accent)] focus:outline-none"
              />
            </div>
            {formError && (
              <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
                {formError}
              </div>
            )}
            <div className="flex gap-2">
              <button type="submit" disabled={saving} className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60">
                <Save className="h-3.5 w-3.5" />
                {saving ? "保存中..." : "保存"}
              </button>
              <button type="button" onClick={closeForm} className="rounded border border-[var(--border-default)] px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-subtle)]">
                取消
              </button>
            </div>
          </form>
        </div>
      )}

      <div className="flex-1 overflow-auto px-4 py-3">
        {loading ? (
          <div className="py-8 text-center text-xs text-[var(--text-tertiary)]">加载中...</div>
        ) : items.length === 0 ? (
          <div className="py-8 text-center text-xs text-[var(--text-tertiary)]">暂无数据</div>
        ) : (
          <div className="space-y-2">
            {items.map((item) => (
              <div key={item.normalized_question} className="rounded border border-[var(--border-default)] bg-[var(--bg-default)] p-3">
                <div className="mb-1 flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <span className="rounded bg-[var(--accent-surface)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--accent)]">
                      {item.preferred_main_table || "未指定主表"}
                    </span>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <button type="button" onClick={() => openEdit(item)} className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--bg-subtle)] hover:text-[var(--accent)]" title="编辑">
                      <Edit3 className="h-3.5 w-3.5" />
                    </button>
                    <button type="button" onClick={() => handleDelete(item.normalized_question)} className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--error-glow)] hover:text-[var(--error)]" title="删除">
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
                <p className="text-xs text-[var(--text-primary)]">{item.question}</p>
                {item.required_tables.length > 0 && (
                  <div className="mt-1 flex flex-wrap gap-1">
                    {item.required_tables.map((t) => (
                      <span key={t} className="rounded bg-[var(--bg-subtle)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--text-secondary)]">{t}</span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
