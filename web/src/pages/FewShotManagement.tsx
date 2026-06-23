import { Edit3, Loader2, Plus, Save, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Panel } from "@/components/Panel";
import {
  createFewShot,
  deleteFewShot,
  fetchFewShots,
  toggleFewShot,
  updateFewShot,
} from "@/lib/api";
import type { DedupSimilarItem, FewShotItem } from "@/types";

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

// ── FewShot 编辑弹窗 ──────────────────────────────────────────────

function FewShotEditModal({
  item,
  onSave,
  onClose,
}: {
  item: FewShotItem | null;
  onSave: (scenario: string, question: string, sql: string, type: string) => Promise<void>;
  onClose: () => void;
}) {
  const [scenario, setScenario] = useState(item?.scenario || "");
  const [question, setQuestion] = useState(item?.question || "");
  const [sql, setSql] = useState("");
  const [type, setType] = useState(item?.type || "manual");
  const [saving, setSaving] = useState(false);

  // 从 full_text 解析 SQL
  useEffect(() => {
    if (item?.full_text) {
      const text = item.full_text;
      // 匹配 "SQL：" 或 "SQL:" 后的所有内容
      const match = text.match(/SQL[：:]\s*\n?([\s\S]*)/);
      if (match) {
        setSql(match[1].trim());
      }
    }
  }, [item]);

  const handleSave = async () => {
    if (!scenario.trim() || !question.trim() || !sql.trim()) {
      alert("请填写完整信息");
      return;
    }
    setSaving(true);
    try {
      await onSave(scenario.trim(), question.trim(), sql.trim(), type);
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
            {item ? "编辑 FewShot" : "新增 FewShot"}
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
            <span className="text-[11px] font-medium text-[var(--text-secondary)]">场景</span>
            <input
              type="text"
              value={scenario}
              onChange={(e) => setScenario(e.target.value)}
              placeholder="例如：查询工单完成情况"
              className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-[11px] font-medium text-[var(--text-secondary)]">类型</span>
            <select
              value={type}
              onChange={(e) => setType(e.target.value)}
              className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
            >
              <option value="manual">手动</option>
              <option value="evolved">进化</option>
            </select>
          </label>
          <label className="block space-y-1">
            <span className="text-[11px] font-medium text-[var(--text-secondary)]">用户问题</span>
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="例如：今天各产线完成了多少工单"
              className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
            />
          </label>
          <label className="block space-y-1">
            <span className="text-[11px] font-medium text-[var(--text-secondary)]">SQL</span>
            <textarea
              value={sql}
              onChange={(e) => setSql(e.target.value)}
              rows={10}
              placeholder="SELECT ..."
              className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 font-mono text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
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

// ── FewShot 管理页面 ───────────────────────────────────────────────

export default function FewShotManagement() {
  // FewShot 状态
  const [fewShots, setFewShots] = useState<FewShotItem[]>([]);
  const [loadingFewShots, setLoadingFewShots] = useState(true);
  const [fewShotEditModal, setFewShotEditModal] = useState<{
    open: boolean;
    item: FewShotItem | null;
  }>({ open: false, item: null });

  // 去重确认状态
  const [dedupDialog, setDedupDialog] = useState<{
    open: boolean;
    items: DedupSimilarItem[];
    onConfirm: () => void;
  }>({ open: false, items: [], onConfirm: () => {} });

  // 解析 409 去重响应
  async function handleCreateWithDedup<T extends unknown[]>(
    createFn: (force: boolean) => Promise<unknown>,
    reloadFn: () => Promise<void>,
    onSuccess?: () => void,
  ) {
    try {
      await createFn(false);
      await reloadFn();
      onSuccess?.();
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
              alert("已存在完全相同的条目，无法新增。");
              return;
            }
            setDedupDialog({
              open: true,
              items: parsed.duplicate_items,
              onConfirm: async () => {
                setDedupDialog({ open: false, items: [], onConfirm: () => {} });
                try {
                  await createFn(true);
                  await reloadFn();
                  onSuccess?.();
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
        alert((e as { detail?: string }).detail || "条目已存在");
      } else {
        alert(`创建失败: ${e instanceof Error ? e.message : String(e)}`);
      }
    }
  }

  // 加载 FewShots
  const loadFewShots = useCallback(async () => {
    setLoadingFewShots(true);
    try {
      const data = await fetchFewShots();
      setFewShots(data);
    } catch (e) {
      console.error("加载 FewShot 失败:", e);
    } finally {
      setLoadingFewShots(false);
    }
  }, []);

  useEffect(() => {
    loadFewShots();
  }, [loadFewShots]);

  // FewShot 操作
  const handleCreateFewShot = async (scenario: string, question: string, sql: string, type: string) => {
    await handleCreateWithDedup(
      (force) => createFewShot(scenario, question, sql, type, force),
      loadFewShots,
    );
  };

  const handleUpdateFewShot = async (scenario: string, question: string, sql: string, type: string) => {
    if (!fewShotEditModal.item) return;
    await updateFewShot(fewShotEditModal.item.id, scenario, question, sql, type);
    await loadFewShots();
  };

  const handleDeleteFewShot = async (id: string) => {
    if (!confirm("确定删除此 FewShot？")) return;
    try {
      await deleteFewShot(id);
      await loadFewShots();
    } catch (e) {
      alert(`删除失败: ${e}`);
    }
  };

  // 启用/禁用切换
  const handleToggleFewShot = async (id: string, enabled: boolean) => {
    try {
      await toggleFewShot(id, enabled);
      await loadFewShots();
    } catch (e) {
      alert(`操作失败: ${e}`);
    }
  };

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="mx-auto max-w-6xl space-y-6">
        {/* FewShot 管理 */}
        <Panel
          title={`FewShot 示例 (${fewShots.length})`}
          action={
            <button
              onClick={() => setFewShotEditModal({ open: true, item: null })}
              className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90"
            >
              <Plus size={13} />
              新增
            </button>
          }
        >
          {loadingFewShots ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 size={20} className="animate-spin text-[var(--text-tertiary)]" />
            </div>
          ) : fewShots.length === 0 ? (
            <div className="py-12 text-center text-sm text-[var(--text-tertiary)]">
              暂无 FewShot 示例
            </div>
          ) : (
            <div className="space-y-3">
              {fewShots.map((item) => (
                <div
                  key={item.id}
                  className="rounded border border-[var(--border-default)] bg-[var(--bg-raised)] p-3"
                >
                  <div className="mb-2 flex items-start justify-between">
                    <div className="flex-1">
                      <div className="mb-1 flex items-center gap-2">
                        <span className="rounded border border-[var(--border-default)] bg-[var(--bg-subtle)] px-1.5 py-0.5 text-[10px] font-medium text-[var(--text-secondary)]">
                          {item.scenario || "未分类"}
                        </span>
                        <span className={`rounded px-1 py-0.5 text-[10px] font-medium ${item.type === "evolved" ? "bg-purple-100 text-purple-700" : "bg-blue-100 text-blue-700"}`}>
                          {item.type === "evolved" ? "进化" : "手动"}
                        </span>
                        <span className="font-mono text-[10px] text-[var(--text-tertiary)]">
                          {item.id}
                        </span>
                      </div>
                      <div className="text-xs font-medium text-[var(--text-primary)]">
                        {item.question}
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <label className="relative inline-flex cursor-pointer items-center" title={item.enabled !== false ? "禁用" : "启用"}>
                        <input
                          type="checkbox"
                          className="peer sr-only"
                          checked={item.enabled !== false}
                          onChange={() => handleToggleFewShot(item.id, item.enabled === false)}
                        />
                        <span className="h-5 w-9 rounded-full border border-[var(--border-default)] bg-[var(--bg-subtle)] transition-colors peer-checked:bg-[var(--accent)] peer-checked:border-[var(--accent)] after:absolute after:left-[2px] after:top-[2px] after:h-4 after:w-4 after:rounded-full after:bg-white after:shadow-sm after:transition-transform peer-checked:after:translate-x-[16px]"></span>
                      </label>
                      <button
                        onClick={() => setFewShotEditModal({ open: true, item })}
                        className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--bg-hover)] hover:text-[var(--accent)]"
                        title="编辑"
                      >
                        <Edit3 size={14} />
                      </button>
                      <button
                        onClick={() => handleDeleteFewShot(item.id)}
                        className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--bg-hover)] hover:text-[var(--error)]"
                        title="删除"
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </div>
                  <details className="text-[11px]">
                    <summary className="cursor-pointer text-[var(--text-tertiary)] hover:text-[var(--text-secondary)]">
                      查看 SQL
                    </summary>
                    <pre className="mt-2 max-h-60 overflow-auto rounded bg-[var(--bg-subtle)] p-2 font-mono text-[10px] text-[var(--text-primary)]">
                      {item.full_text}
                    </pre>
                  </details>
                </div>
              ))}
            </div>
          )}
        </Panel>
      </div>

      {/* FewShot 编辑弹窗 */}
      {fewShotEditModal.open && (
        <FewShotEditModal
          item={fewShotEditModal.item}
          onSave={fewShotEditModal.item ? handleUpdateFewShot : handleCreateFewShot}
          onClose={() => setFewShotEditModal({ open: false, item: null })}
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
