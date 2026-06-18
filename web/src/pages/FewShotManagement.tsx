import { Edit3, Plus, Save, Trash2, X } from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";

import { createFewShot, deleteFewShot, fetchFewShots, updateFewShot } from "@/lib/api";
import type { FewShotItem } from "@/types";

export default function FewShotManagement() {
  const [items, setItems] = useState<FewShotItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [scenario, setScenario] = useState("");
  const [question, setQuestion] = useState("");
  const [sql, setSql] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const data = await fetchFewShots();
      setItems(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function openCreate() {
    setEditingId(null);
    setScenario("");
    setQuestion("");
    setSql("");
    setFormError("");
    setShowForm(true);
  }

  function openEdit(item: FewShotItem) {
    setEditingId(item.id);
    setScenario(item.scenario);
    setQuestion(item.question);
    setSql("");
    setFormError("");
    setShowForm(true);
  }

  function closeForm() {
    setShowForm(false);
    setEditingId(null);
  }

  async function handleSave(e: FormEvent) {
    e.preventDefault();
    if (!scenario.trim() || !question.trim() || !sql.trim()) {
      setFormError("所有字段必填");
      return;
    }
    setFormError("");
    setSaving(true);
    try {
      if (editingId) {
        await updateFewShot(editingId, scenario.trim(), question.trim(), sql.trim());
      } else {
        await createFewShot(scenario.trim(), question.trim(), sql.trim());
      }
      closeForm();
      await load();
    } catch (err) {
      setFormError(err instanceof Error ? err.message : "保存失败");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(id: string, scenario: string) {
    if (!confirm(`确定删除 "${scenario}" 吗？`)) return;
    try {
      await deleteFewShot(id);
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "删除失败");
    }
  }

  return (
    <div className="flex h-full flex-col">
      {/* 顶部操作栏 */}
      <div className="flex items-center justify-between border-b border-[var(--border-default)] px-4 py-3">
        <h2 className="font-display text-sm font-semibold text-[var(--text-primary)]">FewShot 管理</h2>
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

      {/* 编辑表单 */}
      {showForm && (
        <div className="mx-4 mt-3 rounded border border-[var(--border-default)] bg-[var(--bg-default)] p-4">
          <div className="mb-2 flex items-center justify-between">
            <h3 className="text-xs font-semibold text-[var(--text-primary)]">
              {editingId ? "编辑 FewShot" : "新增 FewShot"}
            </h3>
            <button type="button" onClick={closeForm} className="text-[var(--text-tertiary)] hover:text-[var(--text-primary)]">
              <X className="h-4 w-4" />
            </button>
          </div>
          <form onSubmit={handleSave} className="space-y-3">
            <div>
              <label className="mb-1 block text-[11px] text-[var(--text-secondary)]">场景</label>
              <input
                type="text"
                value={scenario}
                onChange={(e) => setScenario(e.target.value)}
                placeholder="例如：生产日报查询"
                className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-input)] px-2 py-1.5 text-xs text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent)] focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-[var(--text-secondary)]">自然语言问题</label>
              <input
                type="text"
                value={question}
                onChange={(e) => setQuestion(e.target.value)}
                placeholder="例如：查询昨天各产线的产量"
                className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-input)] px-2 py-1.5 text-xs text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent)] focus:outline-none"
              />
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-[var(--text-secondary)]">SQL 语句</label>
              <textarea
                value={sql}
                onChange={(e) => setSql(e.target.value)}
                rows={4}
                placeholder="SELECT ..."
                className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-input)] px-2 py-1.5 font-mono text-xs text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent)] focus:outline-none"
              />
            </div>
            {formError && (
              <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
                {formError}
              </div>
            )}
            <div className="flex gap-2">
              <button
                type="submit"
                disabled={saving}
                className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60"
              >
                <Save className="h-3.5 w-3.5" />
                {saving ? "保存中..." : "保存"}
              </button>
              <button
                type="button"
                onClick={closeForm}
                className="rounded border border-[var(--border-default)] px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-subtle)]"
              >
                取消
              </button>
            </div>
          </form>
        </div>
      )}

      {/* 列表 */}
      <div className="flex-1 overflow-auto px-4 py-3">
        {loading ? (
          <div className="py-8 text-center text-xs text-[var(--text-tertiary)]">加载中...</div>
        ) : items.length === 0 ? (
          <div className="py-8 text-center text-xs text-[var(--text-tertiary)]">暂无数据</div>
        ) : (
          <div className="space-y-2">
            {items.map((item) => (
              <div key={item.id} className="rounded border border-[var(--border-default)] bg-[var(--bg-default)] p-3">
                <div className="mb-1 flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <span className="rounded bg-[var(--accent-surface)] px-1.5 py-0.5 font-mono text-[10px] text-[var(--accent)]">
                      {item.scenario}
                    </span>
                  </div>
                  <div className="flex shrink-0 gap-1">
                    <button
                      type="button"
                      onClick={() => openEdit(item)}
                      className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--bg-subtle)] hover:text-[var(--accent)]"
                      title="编辑"
                    >
                      <Edit3 className="h-3.5 w-3.5" />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(item.id, item.scenario)}
                      className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--error-glow)] hover:text-[var(--error)]"
                      title="删除"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </div>
                <p className="text-xs text-[var(--text-primary)]">{item.question}</p>
                <code className="mt-1 block text-[10px] text-[var(--text-tertiary)]">{item.full_text}</code>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
