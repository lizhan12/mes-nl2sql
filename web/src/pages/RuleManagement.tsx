import { Edit3, Loader2, Plus, Save, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Panel } from "@/components/Panel";
import {
  createRuntimeRule,
  deleteRuntimeRule,
  fetchRuntimeRules,
  toggleRuntimeRule,
  updateRuntimeRule,
} from "@/lib/api";
import type { DedupSimilarItem, RuntimeRuleItem } from "@/types";

// ── 去重确认弹窗 ─────────────────────────────────────────────────

function DedupConfirmDialog({
  similarItems,
  onConfirm,
  onCancel,
}: {
  similarItems: DedupSimilarItem[];
  onConfirm: () => void;
  onCancel: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-[500px] max-h-[70vh] overflow-y-auto rounded-lg border border-[var(--border-default)] bg-white p-5 shadow-xl">
        <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">
          发现相似知识条目
        </h3>
        <p className="text-xs text-[var(--text-tertiary)] mb-4">
          以下条目与您要新增的内容高度相似（相似度 &gt; 阈值），请确认是否仍要新增：
        </p>
        <div className="space-y-2 max-h-[300px] overflow-y-auto">
          {similarItems.map((item, idx) => (
            <div
              key={idx}
              className="rounded border border-[var(--border-default)] bg-[var(--bg-subtle)] p-2 text-xs"
            >
              <div className="flex items-center gap-2 mb-1">
                <span className={`rounded px-1 py-0.5 text-[10px] font-medium ${item.match_type === "exact" ? "bg-red-100 text-red-700" : "bg-yellow-100 text-yellow-700"}`}>
                  {item.match_type === "exact" ? "精确匹配" : "向量相似"}
                </span>
                <span className="font-mono text-[10px] text-[var(--text-tertiary)]">
                  相似度: {(item.score * 100).toFixed(1)}%
                </span>
              </div>
              <div className="text-[var(--text-primary)]">{item.question}</div>
              <div className="mt-0.5 font-mono text-[10px] text-[var(--text-tertiary)]">
                Key: {item.key}
              </div>
            </div>
          ))}
        </div>
        <div className="mt-4 flex justify-end gap-2">
          <button
            onClick={onCancel}
            className="rounded px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
          >
            取消
          </button>
          <button
            onClick={onConfirm}
            className="rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90"
          >
            仍然新增
          </button>
        </div>
      </div>
    </div>
  );
}

// ── RuntimeRule 编辑弹窗 ──────────────────────────────────────────

function RuntimeRuleEditModal({
  item,
  onSave,
  onClose,
}: {
  item: RuntimeRuleItem | null;
  onSave: (
    question: string,
    normalizedQuestion: string,
    preferredMainTable: string,
    requiredTables: string[],
    requiredJoins: string[],
    source: string,
  ) => Promise<void>;
  onClose: () => void;
}) {
  const [question, setQuestion] = useState(item?.question || "");
  const [normalizedQuestion, setNormalizedQuestion] = useState(item?.normalized_question || "");
  const [preferredMainTable, setPreferredMainTable] = useState(item?.preferred_main_table || "");
  const [requiredTables, setRequiredTables] = useState(item?.required_tables?.join(", ") || "");
  const [requiredJoins, setRequiredJoins] = useState(item?.required_joins?.join(", ") || "");
  const [source, setSource] = useState(item?.source || "manual");
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    if (!question.trim() || !normalizedQuestion.trim()) {
      alert("请填写用户问题和归一化问题");
      return;
    }
    setSaving(true);
    try {
      const tables = requiredTables
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const joins = requiredJoins
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      await onSave(question.trim(), normalizedQuestion.trim(), preferredMainTable.trim(), tables, joins, source.trim());
      onClose();
    } catch (e) {
      alert(`保存失败: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-[600px] rounded-lg border border-[var(--border-default)] bg-white p-5 shadow-xl">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-[var(--text-primary)]">
            {item ? "编辑 RuntimeRule" : "新增 RuntimeRule"}
          </h3>
          <button
            onClick={onClose}
            className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--bg-hover)]"
          >
            <X size={16} />
          </button>
        </div>
        <div className="space-y-3">
          <label className="block space-y-1">
            <span className="text-[11px] font-medium text-[var(--text-secondary)]">用户问题</span>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={2}
              placeholder="例如：查询各产线当日的良品率"
              className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-[11px] font-medium text-[var(--text-secondary)]">
              归一化问题
              {item && <span className="ml-2 text-[10px] text-[var(--text-tertiary)]">（唯一键，不可修改）</span>}
            </span>
            <input
              type="text"
              value={normalizedQuestion}
              onChange={(e) => setNormalizedQuestion(e.target.value)}
              readOnly={!!item}
              placeholder="例如：查询产线当日良品率"
              className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none disabled:opacity-60"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-[11px] font-medium text-[var(--text-secondary)]">首选主表</span>
            <input
              type="text"
              value={preferredMainTable}
              onChange={(e) => setPreferredMainTable(e.target.value)}
              placeholder="例如：t_production_line"
              className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-[11px] font-medium text-[var(--text-secondary)]">所需表（逗号分隔）</span>
            <input
              type="text"
              value={requiredTables}
              onChange={(e) => setRequiredTables(e.target.value)}
              placeholder="例如：t_production_line, t_quality_inspection"
              className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-[11px] font-medium text-[var(--text-secondary)]">所需 JOIN（逗号分隔）</span>
            <input
              type="text"
              value={requiredJoins}
              onChange={(e) => setRequiredJoins(e.target.value)}
              placeholder="例如：t_production_line.id = t_quality_inspection.line_id"
              className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-[11px] font-medium text-[var(--text-secondary)]">来源</span>
            <input
              type="text"
              value={source}
              onChange={(e) => setSource(e.target.value)}
              placeholder="例如：manual, online_harness"
              className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
            />
          </label>
        </div>
        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onClose}
            className="rounded px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
          >
            取消
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
            保存
          </button>
        </div>
      </div>
    </div>
  );
}

// ── 主组件 ────────────────────────────────────────────────────────

export default function RuleManagement() {
  const [rules, setRules] = useState<RuntimeRuleItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [editModal, setEditModal] = useState<{ open: boolean; item: RuntimeRuleItem | null }>({
    open: false,
    item: null,
  });

  // 去重确认状态
  const [dedupDialog, setDedupDialog] = useState<{
    open: boolean;
    items: DedupSimilarItem[];
    onConfirm: () => void;
  }>({ open: false, items: [], onConfirm: () => {} });

  // 加载数据
  const loadRules = useCallback(async () => {
    setLoading(true);
    try {
      const data = await fetchRuntimeRules();
      setRules(data);
    } catch (e) {
      console.error("加载 RuntimeRule 失败:", e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadRules();
  }, [loadRules]);

  // 新增
  const handleCreate = async (
    question: string,
    normalizedQuestion: string,
    preferredMainTable: string,
    requiredTables: string[],
    requiredJoins: string[],
    source: string,
  ) => {
    try {
      await createRuntimeRule(
        question,
        normalizedQuestion,
        preferredMainTable,
        requiredTables,
        requiredJoins,
        source,
        false,
      );
      await loadRules();
    } catch (e: unknown) {
      if (e instanceof Response && e.status === 409) {
        try {
          const detail = (e as unknown as { detail?: string }).detail || "";
          const parsed = JSON.parse(detail);
          if (parsed.duplicate_items?.length > 0) {
            const hasExact = parsed.duplicate_items.some(
              (item: DedupSimilarItem) => item.match_type === "exact",
            );
            if (hasExact) {
              alert("已存在完全相同的规则，无法新增。");
              return;
            }
            setDedupDialog({
              open: true,
              items: parsed.duplicate_items,
              onConfirm: async () => {
                setDedupDialog({ open: false, items: [], onConfirm: () => {} });
                try {
                  await createRuntimeRule(
                    question,
                    normalizedQuestion,
                    preferredMainTable,
                    requiredTables,
                    requiredJoins,
                    source,
                    true,
                  );
                  await loadRules();
                } catch (e2) {
                  alert(`创建失败: ${e2}`);
                }
              },
            });
            return;
          }
        } catch {
          // ignore parse error
        }
        alert((e as { detail?: string }).detail || "规则已存在");
      } else {
        alert(`创建失败: ${e instanceof Error ? e.message : String(e)}`);
      }
    }
  };

  // 更新
  const handleUpdate = async (
    originalKey: string,
    question: string,
    _normalizedQuestion: string,
    preferredMainTable: string,
    requiredTables: string[],
    requiredJoins: string[],
    source: string,
  ) => {
    await updateRuntimeRule(originalKey, question, preferredMainTable, requiredTables, requiredJoins, source);
    await loadRules();
  };

  // 删除
  const handleDelete = async (normalizedQuestion: string) => {
    if (!confirm("确定删除此 RuntimeRule？")) return;
    try {
      await deleteRuntimeRule(normalizedQuestion);
      await loadRules();
    } catch (e) {
      alert(`删除失败: ${e}`);
    }
  };

  // 启用/禁用切换
  const handleToggle = async (normalizedQuestion: string, enabled: boolean) => {
    try {
      await toggleRuntimeRule(normalizedQuestion, enabled);
      await loadRules();
    } catch (e) {
      alert(`操作失败: ${e}`);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="mx-auto max-w-6xl space-y-6">
        {/* RuntimeRule 管理 */}
        <Panel
          title={`RuntimeRule 规则 (${rules.length})`}
          action={
            <button
              onClick={() => setEditModal({ open: true, item: null })}
              className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90"
            >
              <Plus size={13} />
              新增规则
            </button>
          }
        >
          {loading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 size={20} className="animate-spin text-[var(--text-tertiary)]" />
            </div>
          ) : rules.length === 0 ? (
            <div className="py-12 text-center text-sm text-[var(--text-tertiary)]">
              暂无 RuntimeRule 规则
            </div>
          ) : (
            <div className="space-y-3">
              {rules.map((rule) => (
                <div
                  key={rule.normalized_question}
                  className="rounded border border-[var(--border-default)] bg-[var(--bg-raised)] p-3"
                >
                  <div className="mb-2 flex items-start justify-between">
                    <div className="flex-1">
                      <div className="mb-1 flex items-center gap-2">
                        <span className="rounded border border-[var(--border-default)] bg-[var(--bg-subtle)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--text-secondary)]">
                          {rule.source || "未分类"}
                        </span>
                        {rule.preferred_main_table && (
                          <span className="font-mono text-[10px] text-[var(--text-tertiary)]">
                            {rule.preferred_main_table}
                          </span>
                        )}
                      </div>
                      <div className="text-xs font-medium text-[var(--text-primary)]">
                        {rule.question}
                      </div>
                      <div className="mt-0.5 font-mono text-[10px] text-[var(--text-tertiary)]">
                        {rule.normalized_question}
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <label className="relative inline-flex cursor-pointer items-center" title={rule.enabled !== false ? "禁用" : "启用"}>
                        <input
                          type="checkbox"
                          className="peer sr-only"
                          checked={rule.enabled !== false}
                          onChange={() => handleToggle(rule.normalized_question, rule.enabled === false)}
                        />
                        <span className="h-5 w-9 rounded-full border border-[var(--border-default)] bg-[var(--bg-subtle)] transition-colors peer-checked:bg-[var(--accent)] peer-checked:border-[var(--accent)] after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:bg-white after:shadow-sm after:transition-transform peer-checked:after:translate-x-[16px]"></span>
                      </label>
                      <button
                        onClick={() => setEditModal({ open: true, item: rule })}
                        className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--bg-hover)] hover:text-[var(--accent)]"
                        title="编辑"
                      >
                        <Edit3 size={14} />
                      </button>
                      <button
                        onClick={() => handleDelete(rule.normalized_question)}
                        className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--bg-hover)] hover:text-[var(--error)]"
                        title="删除"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                  <details className="text-[11px]">
                    <summary className="cursor-pointer text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]">
                      查看详情
                    </summary>
                    <div className="mt-2 space-y-1 rounded bg-[var(--bg-subtle)] p-2 font-mono text-[10px] text-[var(--text-primary)]">
                      {rule.required_tables?.length > 0 && (
                        <div><span className="text-[var(--text-tertiary)]">所需表：</span>{rule.required_tables.join(", ")}</div>
                      )}
                      {rule.required_joins?.length > 0 && (
                        <div><span className="text-[var(--text-tertiary)]">所需 JOIN：</span>{rule.required_joins.join(", ")}</div>
                      )}
                    </div>
                  </details>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      {/* 编辑弹窗 */}
      {editModal.open && (
        <RuntimeRuleEditModal
          item={editModal.item}
          onSave={async (question, normalizedQuestion, preferredMainTable, requiredTables, requiredJoins, source) => {
            if (editModal.item) {
              await handleUpdate(
                editModal.item.normalized_question,
                question,
                normalizedQuestion,
                preferredMainTable,
                requiredTables,
                requiredJoins,
                source,
              );
            } else {
              await handleCreate(question, normalizedQuestion, preferredMainTable, requiredTables, requiredJoins, source);
            }
          }}
          onClose={() => setEditModal({ open: false, item: null })}
        />
      )}

      {/* 去重确认弹窗 */}
      {dedupDialog.open && (
        <DedupConfirmDialog
          similarItems={dedupDialog.items}
          onConfirm={dedupDialog.onConfirm}
          onCancel={() => setDedupDialog({ open: false, items: [], onConfirm: () => {} })}
        />
      )}
    </div>
  );
}
