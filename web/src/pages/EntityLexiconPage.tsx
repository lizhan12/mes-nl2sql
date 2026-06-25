import { Edit3, Loader2, Plus, Save, Search, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Panel } from "@/components/Panel";
import { fetchEntityLexicon, previewEntityExtract, updateEntityLexicon } from "@/lib/api";
import type { ActionPattern, EntityExtractPreview, EntityLexiconEntry } from "@/types";

const DOMAIN_OPTIONS = ["production", "quality", "warehouse", "equipment", "master", "barcode"] as const;

// ── 可编辑行：Entity Lexicon ──────────────────────────────────────

function EntityRow({
  entry,
  onChange,
  onRemove,
}: {
  entry: EntityLexiconEntry;
  onChange: (e: EntityLexiconEntry) => void;
  onRemove: () => void;
}) {
  return (
    <tr className="border-t border-[var(--border-default)]">
      <td className="px-2.5 py-2">
        <input
          type="text"
          value={entry.entity}
          onChange={(e) => onChange({ ...entry, entity: e.target.value })}
          className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2 py-1 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
        />
      </td>
      <td className="px-2.5 py-2">
        <select
          value={entry.domain}
          onChange={(e) => onChange({ ...entry, domain: e.target.value })}
          className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2 py-1 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
        >
          {DOMAIN_OPTIONS.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>
      </td>
      <td className="px-2.5 py-2">
        <input
          type="text"
          value={entry.tables.join(", ")}
          onChange={(e) =>
            onChange({
              ...entry,
              tables: e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            })
          }
          className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2 py-1 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
        />
      </td>
      <td className="px-2.5 py-2 text-center">
        <button
          onClick={onRemove}
          className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--bg-hover)] hover:text-[var(--error)]"
          title="删除"
        >
          <Trash2 size={14} />
        </button>
      </td>
    </tr>
  );
}

// ── 可编辑行：Action Pattern ──────────────────────────────────────

function ActionRow({
  pattern,
  onChange,
  onRemove,
}: {
  pattern: ActionPattern;
  onChange: (p: ActionPattern) => void;
  onRemove: () => void;
}) {
  return (
    <tr className="border-t border-[var(--border-default)]">
      <td className="px-2.5 py-2">
        <input
          type="text"
          value={pattern.action}
          onChange={(e) => onChange({ ...pattern, action: e.target.value })}
          className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2 py-1 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
        />
      </td>
      <td className="px-2.5 py-2">
        <input
          type="text"
          value={pattern.keywords.join(", ")}
          onChange={(e) =>
            onChange({
              ...pattern,
              keywords: e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean),
            })
          }
          className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2 py-1 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
        />
      </td>
      <td className="px-2.5 py-2 text-center">
        <button
          onClick={onRemove}
          className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--bg-hover)] hover:text-[var(--error)]"
          title="删除"
        >
          <Trash2 size={14} />
        </button>
      </td>
    </tr>
  );
}

// ── 主页面 ─────────────────────────────────────────────────────────

export default function EntityLexiconPage() {
  const [entities, setEntities] = useState<EntityLexiconEntry[]>([]);
  const [actions, setActions] = useState<ActionPattern[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Preview 状态
  const [previewQuery, setPreviewQuery] = useState("");
  const [previewResult, setPreviewResult] = useState<EntityExtractPreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const loadData = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchEntityLexicon();
      setEntities(data.entity_lexicon ?? []);
      setActions(data.action_patterns ?? []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadData();
  }, [loadData]);

  // Entity 操作
  const updateEntity = useCallback((index: number, entry: EntityLexiconEntry) => {
    setEntities((prev) => {
      const next = [...prev];
      next[index] = entry;
      return next;
    });
  }, []);

  const removeEntity = useCallback((index: number) => {
    setEntities((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const addEntity = useCallback(() => {
    setEntities((prev) => [...prev, { entity: "", domain: DOMAIN_OPTIONS[0], tables: [] }]);
  }, []);

  // Action 操作
  const updateAction = useCallback((index: number, pattern: ActionPattern) => {
    setActions((prev) => {
      const next = [...prev];
      next[index] = pattern;
      return next;
    });
  }, []);

  const removeAction = useCallback((index: number) => {
    setActions((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const addAction = useCallback(() => {
    setActions((prev) => [...prev, { action: "", keywords: [] }]);
  }, []);

  // 保存
  const handleSave = async () => {
    setSaving(true);
    setError(null);
    try {
      await updateEntityLexicon({ entity_lexicon: entities, action_patterns: actions });
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  // 预览
  const handlePreview = async () => {
    if (!previewQuery.trim()) return;
    setPreviewLoading(true);
    setPreviewError(null);
    setPreviewResult(null);
    try {
      const result = await previewEntityExtract(previewQuery.trim());
      setPreviewResult(result);
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : String(e));
    } finally {
      setPreviewLoading(false);
    }
  };

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <Loader2 size={24} className="animate-spin text-[var(--text-tertiary)]" />
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto p-6">
      <div className="mx-auto max-w-6xl space-y-6">
        {/* 错误提示 */}
        {error && (
          <div className="rounded border border-red-200 bg-red-50 px-4 py-2 text-xs text-red-700">
            {error}
          </div>
        )}

        {/* Entity Lexicon 表 */}
        <Panel
          title={`实体词典 (${entities.length})`}
          action={
            <button
              onClick={addEntity}
              className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90"
            >
              <Plus size={13} />
              新增
            </button>
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-[var(--border-default)] text-[11px] font-medium text-[var(--text-secondary)]">
                  <th className="px-2.5 py-2">Entity</th>
                  <th className="px-2.5 py-2">Domain</th>
                  <th className="px-2.5 py-2">Tables</th>
                  <th className="w-12 px-2.5 py-2 text-center">操作</th>
                </tr>
              </thead>
              <tbody>
                {entities.map((entry, idx) => (
                  <EntityRow
                    key={idx}
                    entry={entry}
                    onChange={(e) => updateEntity(idx, e)}
                    onRemove={() => removeEntity(idx)}
                  />
                ))}
                {entities.length === 0 && (
                  <tr>
                    <td colSpan={4} className="px-2.5 py-6 text-center text-[var(--text-tertiary)]">
                      暂无实体条目
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>

        {/* Action Patterns 表 */}
        <Panel
          title={`动作模式 (${actions.length})`}
          action={
            <button
              onClick={addAction}
              className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90"
            >
              <Plus size={13} />
              新增
            </button>
          }
        >
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-[var(--border-default)] text-[11px] font-medium text-[var(--text-secondary)]">
                  <th className="px-2.5 py-2">Action</th>
                  <th className="px-2.5 py-2">Keywords</th>
                  <th className="w-12 px-2.5 py-2 text-center">操作</th>
                </tr>
              </thead>
              <tbody>
                {actions.map((pattern, idx) => (
                  <ActionRow
                    key={idx}
                    pattern={pattern}
                    onChange={(p) => updateAction(idx, p)}
                    onRemove={() => removeAction(idx)}
                  />
                ))}
                {actions.length === 0 && (
                  <tr>
                    <td colSpan={3} className="px-2.5 py-6 text-center text-[var(--text-tertiary)]">
                      暂无动作模式
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </Panel>

        {/* 保存按钮 */}
        <div className="flex justify-end">
          <button
            onClick={handleSave}
            disabled={saving}
            className="inline-flex items-center gap-1.5 rounded bg-[var(--accent)] px-4 py-2 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {saving ? <Loader2 size={14} className="animate-spin" /> : <Save size={14} />}
            保存全部
          </button>
        </div>

        {/* 预览面板 */}
        <Panel title="预览" subtitle="输入查询文本，测试实体抽取效果">
          <div className="space-y-3">
            <div className="flex gap-2">
              <input
                type="text"
                value={previewQuery}
                onChange={(e) => setPreviewQuery(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handlePreview()}
                placeholder="输入查询文本，例如：查询昨天A产线的良率"
                className="flex-1 rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
              />
              <button
                onClick={handlePreview}
                disabled={previewLoading || !previewQuery.trim()}
                className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
              >
                {previewLoading ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />}
                抽取
              </button>
            </div>

            {previewError && (
              <div className="rounded border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-700">
                {previewError}
              </div>
            )}

            {previewResult && (
              <div className="rounded border border-[var(--border-default)] bg-[var(--bg-subtle)] p-3">
                <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-xs">
                  <div>
                    <span className="text-[var(--text-tertiary)]">object_entity：</span>
                    <span className="font-medium text-[var(--text-primary)]">
                      {previewResult.structural.object_entity || "—"}
                    </span>
                  </div>
                  <div>
                    <span className="text-[var(--text-tertiary)]">action_type：</span>
                    <span className="font-medium text-[var(--text-primary)]">
                      {previewResult.structural.action_type || "—"}
                    </span>
                  </div>
                  <div>
                    <span className="text-[var(--text-tertiary)]">domain：</span>
                    <span className="font-medium text-[var(--text-primary)]">
                      {previewResult.structural.domain || "—"}
                    </span>
                  </div>
                  <div>
                    <span className="text-[var(--text-tertiary)]">archive_key：</span>
                    <span className="font-mono text-[var(--text-primary)]">
                      {previewResult.archive_key || "—"}
                    </span>
                  </div>
                </div>
              </div>
            )}
          </div>
        </Panel>
      </div>
    </div>
  );
}
