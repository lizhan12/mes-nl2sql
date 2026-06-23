import { Loader2, Pencil, Plus, Save, Search, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";

import Empty from "@/components/Empty";
import { Panel } from "@/components/Panel";
import {
  createGenericItem,
  deleteGenericItem,
  listGenericItems,
  updateGenericItem,
} from "@/lib/api";
import type { GenericKnowledgeFieldDef, GenericKnowledgeItem } from "@/types";

const EMBED_MAX_CHARS = 800;

function emptyField(): GenericKnowledgeFieldDef {
  return { name: "", value: "", embed: false };
}

function buildEmbedPreview(fields: GenericKnowledgeFieldDef[]): string {
  const embedFields = fields.filter((f) => f.embed && f.name);
  if (!embedFields.length) return "";
  const anchor = embedFields.map((f) => f.name).join(" ");
  const values = embedFields.map((f) => f.value).filter(Boolean).join(" ");
  return `${anchor} ${values}`.trim();
}

export default function GenericKnowledgePage() {
  const { kbName } = useParams<{ kbName: string }>();

  const [items, setItems] = useState<GenericKnowledgeItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [searchTerm, setSearchTerm] = useState("");

  // 详情
  const [selectedId, setSelectedId] = useState("");
  const [detail, setDetail] = useState<GenericKnowledgeItem | null>(null);

  // 编辑
  const [editing, setEditing] = useState(false);
  const [editLabel, setEditLabel] = useState("");
  const [editFields, setEditFields] = useState<GenericKnowledgeFieldDef[]>([]);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");

  // 添加对话框
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [addLabel, setAddLabel] = useState("");
  const [addFields, setAddFields] = useState<GenericKnowledgeFieldDef[]>([emptyField()]);
  const [adding, setAdding] = useState(false);

  // 加载列表
  const loadItems = useCallback(async () => {
    if (!kbName) return;
    setLoading(true);
    setError("");
    try {
      const data = await listGenericItems(kbName);
      setItems(data);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [kbName]);

  useEffect(() => {
    loadItems();
  }, [loadItems]);

  // 选中条目
  const selectItem = (item: GenericKnowledgeItem) => {
    setSelectedId(item.item_id);
    setDetail(item);
    setEditing(false);
    setSaveMessage("");
  };

  // 开始编辑
  const startEdit = () => {
    if (!detail) return;
    setEditLabel(detail.label);
    setEditFields(JSON.parse(JSON.stringify(detail.fields)) as GenericKnowledgeFieldDef[]);
    setEditing(true);
    setSaveMessage("");
  };

  const cancelEdit = () => {
    setEditing(false);
    setSaveMessage("");
  };

  // 保存编辑
  const saveEdit = async () => {
    if (!kbName || !detail) return;
    setSaving(true);
    setSaveMessage("");
    try {
      await updateGenericItem(kbName, detail.item_id, editLabel, editFields);
      setSaveMessage("保存成功");
      setEditing(false);
      await loadItems();
      // 更新详情
      const updated = await listGenericItems(kbName);
      const found = updated.find((i) => i.item_id === detail.item_id);
      if (found) setDetail(found);
    } catch (e) {
      setSaveMessage(`保存失败: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  // 删除条目
  const handleDelete = async (itemId: string) => {
    if (!kbName) return;
    if (!window.confirm("确定删除此条目？")) return;
    try {
      await deleteGenericItem(kbName, itemId);
      if (selectedId === itemId) {
        setSelectedId("");
        setDetail(null);
      }
      await loadItems();
    } catch (e) {
      alert(`删除失败: ${e}`);
    }
  };

  // 添加条目
  const handleAdd = async () => {
    if (!kbName) return;
    setAdding(true);
    try {
      await createGenericItem(kbName, addLabel, addFields);
      setAddModalOpen(false);
      setAddLabel("");
      setAddFields([emptyField()]);
      await loadItems();
    } catch (e) {
      alert(`添加失败: ${e}`);
    } finally {
      setAdding(false);
    }
  };

  // 编辑字段辅助
  const updateEditField = (idx: number, key: keyof GenericKnowledgeFieldDef, value: string | boolean) => {
    const fields = [...editFields];
    fields[idx] = { ...fields[idx], [key]: value };
    setEditFields(fields);
  };

  const addEditField = () => setEditFields([...editFields, emptyField()]);
  const removeEditField = (idx: number) => setEditFields(editFields.filter((_, i) => i !== idx));

  // 添加字段辅助
  const updateAddField = (idx: number, key: keyof GenericKnowledgeFieldDef, value: string | boolean) => {
    const fields = [...addFields];
    fields[idx] = { ...fields[idx], [key]: value };
    setAddFields(fields);
  };

  const addAddField = () => setAddFields([...addFields, emptyField()]);
  const removeAddField = (idx: number) => setAddFields(addFields.filter((_, i) => i !== idx));

  // 过滤
  const filteredItems = useMemo(() => {
    if (!searchTerm) return items;
    const lower = searchTerm.toLowerCase();
    return items.filter(
      (i) =>
        i.label.toLowerCase().includes(lower) ||
        i.item_id.toLowerCase().includes(lower) ||
        i.fields.some((f) => f.name.toLowerCase().includes(lower) || f.value.toLowerCase().includes(lower)),
    );
  }, [items, searchTerm]);

  // embedding 预览
  const editEmbedPreview = useMemo(() => buildEmbedPreview(editFields), [editFields]);
  const addEmbedPreview = useMemo(() => buildEmbedPreview(addFields), [addFields]);

  return (
    <div className="flex h-full flex-col bg-[var(--bg-default)]">
      {/* 顶部标题栏 */}
      <header className="flex items-center justify-between border-b border-[var(--border-default)] px-5 py-2.5">
        <div className="flex items-center gap-3">
          <span className="text-sm font-semibold text-[var(--text-primary)]">{kbName}</span>
          <span className="text-[11px] text-[var(--text-tertiary)]">{items.length} 条</span>
        </div>
        <button
          onClick={() => {
            setAddLabel("");
            setAddFields([emptyField()]);
            setAddModalOpen(true);
          }}
          className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90"
        >
          <Plus size={13} />
          添加条目
        </button>
      </header>

      {/* 主体 */}
      <div className="flex flex-1 overflow-hidden">
        {/* 左侧列表 */}
        <aside className="flex w-72 shrink-0 flex-col border-r border-[var(--border-default)]">
          <div className="border-b border-[var(--border-default)] p-3">
            <div className="relative">
              <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" />
              <input
                type="text"
                placeholder="搜索..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] py-1.5 pl-8 pr-2 text-xs text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent)] focus:outline-none"
              />
            </div>
          </div>
          <div className="flex-1 overflow-y-auto">
            {loading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 size={20} className="animate-spin text-[var(--text-tertiary)]" />
              </div>
            ) : error ? (
              <div className="p-4 text-xs text-[var(--error)]">{error}</div>
            ) : filteredItems.length === 0 ? (
              <Empty message={searchTerm ? "无匹配结果" : "暂无数据"} />
            ) : (
              <ul className="divide-y divide-[var(--border-subtle)]">
                {filteredItems.map((item) => (
                  <li
                    key={item.item_id}
                    onClick={() => selectItem(item)}
                    className={`cursor-pointer px-4 py-2.5 transition-colors hover:bg-[var(--bg-hover)] ${
                      selectedId === item.item_id ? "bg-[var(--bg-raised)] border-l-2 border-l-[var(--accent)]" : ""
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-xs font-medium text-[var(--text-primary)] truncate">
                        {item.label || item.item_id}
                      </span>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDelete(item.item_id); }}
                        className="rounded p-0.5 text-[var(--text-tertiary)] hover:bg-red-50 hover:text-red-600"
                        title="删除"
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {item.fields.slice(0, 3).map((f, i) => (
                        <span key={i} className="text-[10px] text-[var(--text-tertiary)]">
                          {f.name}:{f.value}
                        </span>
                      ))}
                      {item.fields.length > 3 && (
                        <span className="text-[10px] text-[var(--text-tertiary)]">+{item.fields.length - 3}</span>
                      )}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        {/* 右侧详情 */}
        <main className="flex-1 overflow-y-auto p-6">
          {!selectedId ? (
            <Empty message="请从左侧选择一条记录查看详情" />
          ) : detail ? (
            <div className="mx-auto max-w-3xl space-y-5">
              {saveMessage && (
                <div
                  className={`rounded border px-3 py-2 text-xs ${
                    saveMessage.includes("失败")
                      ? "border-red-300 bg-red-50 text-red-700"
                      : "border-green-300 bg-green-50 text-green-700"
                  }`}
                >
                  {saveMessage}
                </div>
              )}

              <Panel
                title={editing ? "编辑条目" : "条目详情"}
                action={
                  editing ? (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={saveEdit}
                        disabled={saving}
                        className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
                      >
                        {saving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                        保存
                      </button>
                      <button onClick={cancelEdit} className="rounded px-2 py-1.5 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]">
                        取消
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={startEdit}
                      className="inline-flex items-center gap-1 rounded px-2.5 py-1.5 text-xs text-[var(--accent)] hover:bg-[var(--bg-hover)]"
                    >
                      <Pencil size={13} />
                      编辑
                    </button>
                  )
                }
              >
                {editing ? (
                  <div className="space-y-4">
                    <label className="block space-y-1">
                      <span className="text-[11px] font-medium text-[var(--text-secondary)]">标签</span>
                      <input
                        type="text"
                        value={editLabel}
                        onChange={(e) => setEditLabel(e.target.value)}
                        className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                      />
                    </label>

                    {/* 字段表格 */}
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-medium text-[var(--text-secondary)]">字段</span>
                        <button onClick={addEditField} className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[11px] text-[var(--accent)] hover:bg-[var(--bg-hover)]">
                          <Plus size={12} /> 添加字段
                        </button>
                      </div>
                      <div className="overflow-x-auto rounded border border-[var(--border-default)]">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-[var(--border-default)] bg-[var(--bg-raised)]">
                              <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">字段名</th>
                              <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">值</th>
                              <th className="w-16 px-3 py-2 text-center font-medium text-[var(--text-secondary)]">Embed</th>
                              <th className="w-10 px-3 py-2" />
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-[var(--border-subtle)]">
                            {editFields.map((f, idx) => (
                              <tr key={idx}>
                                <td className="px-3 py-1.5">
                                  <input
                                    type="text"
                                    value={f.name}
                                    onChange={(e) => updateEditField(idx, "name", e.target.value)}
                                    placeholder="字段名"
                                    className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 font-mono text-xs text-[var(--text-primary)] hover:border-[var(--border-default)] focus:border-[var(--accent)] focus:outline-none"
                                  />
                                </td>
                                <td className="px-3 py-1.5">
                                  <input
                                    type="text"
                                    value={f.value}
                                    onChange={(e) => updateEditField(idx, "value", e.target.value)}
                                    placeholder="值"
                                    className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-xs text-[var(--text-primary)] hover:border-[var(--border-default)] focus:border-[var(--accent)] focus:outline-none"
                                  />
                                </td>
                                <td className="px-3 py-1.5 text-center">
                                  <input
                                    type="checkbox"
                                    checked={f.embed}
                                    onChange={(e) => updateEditField(idx, "embed", e.target.checked)}
                                    className="accent-[var(--accent)]"
                                  />
                                </td>
                                <td className="px-3 py-1.5">
                                  <button onClick={() => removeEditField(idx)} className="rounded p-0.5 text-[var(--text-tertiary)] hover:bg-[var(--bg-hover)] hover:text-[var(--error)]">
                                    <X size={13} />
                                  </button>
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                      {/* Embedding 预览 */}
                      {editEmbedPreview && (
                        <div className="rounded border border-[var(--border-subtle)] bg-[var(--bg-subtle)] p-2">
                          <span className="text-[10px] font-medium text-[var(--text-tertiary)]">Embedding 文本预览</span>
                          <p className={`mt-0.5 text-[11px] font-mono break-all ${editEmbedPreview.length > EMBED_MAX_CHARS ? "text-[var(--error)]" : "text-[var(--text-secondary)]"}`}>
                            {editEmbedPreview.length > EMBED_MAX_CHARS
                              ? `${editEmbedPreview.slice(0, EMBED_MAX_CHARS)}... (超出 ${editEmbedPreview.length - EMBED_MAX_CHARS} 字符将被截断)`
                              : editEmbedPreview}
                          </p>
                        </div>
                      )}
                    </div>
                  </div>
                ) : (
                  <div className="space-y-4">
                    <div>
                      <span className="text-[11px] font-medium text-[var(--text-tertiary)]">标签</span>
                      <p className="mt-0.5 text-sm text-[var(--text-primary)]">{detail.label || "无"}</p>
                    </div>
                    <div>
                      <span className="text-[11px] font-medium text-[var(--text-tertiary)]">ID</span>
                      <p className="mt-0.5 font-mono text-xs text-[var(--text-secondary)]">{detail.item_id}</p>
                    </div>
                    <div>
                      <span className="text-[11px] font-medium text-[var(--text-tertiary)]">
                        字段（{detail.fields.length}）
                      </span>
                      <div className="mt-1.5 overflow-x-auto rounded border border-[var(--border-default)]">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-[var(--border-default)] bg-[var(--bg-raised)]">
                              <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">字段名</th>
                              <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">值</th>
                              <th className="w-16 px-3 py-2 text-center font-medium text-[var(--text-secondary)]">Embed</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-[var(--border-subtle)]">
                            {detail.fields.map((f, idx) => (
                              <tr key={idx} className="hover:bg-[var(--bg-hover)]">
                                <td className="px-3 py-1.5 font-mono text-[var(--text-primary)]">{f.name}</td>
                                <td className="px-3 py-1.5 text-[var(--text-secondary)]">{f.value}</td>
                                <td className="px-3 py-1.5 text-center">
                                  {f.embed && <span className="text-[10px] text-[var(--accent)]">✓</span>}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  </div>
                )}
              </Panel>
            </div>
          ) : null}
        </main>
      </div>

      {/* 添加条目对话框 */}
      {addModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-[560px] max-h-[80vh] overflow-y-auto rounded-lg border border-[var(--border-default)] bg-white p-5 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">添加条目</h3>
              <button onClick={() => setAddModalOpen(false)} className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--bg-hover)]">
                <X size={16} />
              </button>
            </div>
            <div className="space-y-3">
              <label className="block space-y-1">
                <span className="text-[11px] font-medium text-[var(--text-secondary)]">标签 <span className="text-[var(--error)]">*</span></span>
                <input
                  type="text"
                  value={addLabel}
                  onChange={(e) => setAddLabel(e.target.value)}
                  placeholder="如: 张三"
                  className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                />
              </label>

              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-medium text-[var(--text-secondary)]">字段</span>
                  <button onClick={addAddField} className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[11px] text-[var(--accent)] hover:bg-[var(--bg-hover)]">
                    <Plus size={12} /> 添加字段
                  </button>
                </div>
                <div className="overflow-x-auto rounded border border-[var(--border-default)]">
                  <table className="w-full text-xs">
                    <thead>
                      <tr className="border-b border-[var(--border-default)] bg-[var(--bg-raised)]">
                        <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">字段名</th>
                        <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">值</th>
                        <th className="w-16 px-3 py-2 text-center font-medium text-[var(--text-secondary)]">Embed</th>
                        <th className="w-10 px-3 py-2" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-[var(--border-subtle)]">
                      {addFields.map((f, idx) => (
                        <tr key={idx}>
                          <td className="px-3 py-1.5">
                            <input
                              type="text"
                              value={f.name}
                              onChange={(e) => updateAddField(idx, "name", e.target.value)}
                              placeholder="字段名"
                              className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 font-mono text-xs text-[var(--text-primary)] hover:border-[var(--border-default)] focus:border-[var(--accent)] focus:outline-none"
                            />
                          </td>
                          <td className="px-3 py-1.5">
                            <input
                              type="text"
                              value={f.value}
                              onChange={(e) => updateAddField(idx, "value", e.target.value)}
                              placeholder="值"
                              className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-xs text-[var(--text-primary)] hover:border-[var(--border-default)] focus:border-[var(--accent)] focus:outline-none"
                            />
                          </td>
                          <td className="px-3 py-1.5 text-center">
                            <input
                              type="checkbox"
                              checked={f.embed}
                              onChange={(e) => updateAddField(idx, "embed", e.target.checked)}
                              className="accent-[var(--accent)]"
                            />
                          </td>
                          <td className="px-3 py-1.5">
                            <button onClick={() => removeAddField(idx)} className="rounded p-0.5 text-[var(--text-tertiary)] hover:bg-[var(--bg-hover)] hover:text-[var(--error)]">
                              <X size={13} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                {/* Embedding 预览 */}
                {addEmbedPreview && (
                  <div className="rounded border border-[var(--border-subtle)] bg-[var(--bg-subtle)] p-2">
                    <span className="text-[10px] font-medium text-[var(--text-tertiary)]">Embedding 文本预览</span>
                    <p className={`mt-0.5 text-[11px] font-mono break-all ${addEmbedPreview.length > EMBED_MAX_CHARS ? "text-[var(--error)]" : "text-[var(--text-secondary)]"}`}>
                      {addEmbedPreview.length > EMBED_MAX_CHARS
                        ? `${addEmbedPreview.slice(0, EMBED_MAX_CHARS)}... (超出 ${addEmbedPreview.length - EMBED_MAX_CHARS} 字符将被截断)`
                        : addEmbedPreview}
                    </p>
                  </div>
                )}
              </div>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button onClick={() => setAddModalOpen(false)} className="rounded px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]">
                取消
              </button>
              <button
                onClick={handleAdd}
                disabled={adding || !addLabel.trim()}
                className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
              >
                {adding ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
                添加
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
