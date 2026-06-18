import {
  Database,
  Edit3,
  Loader2,
  Plus,
  Save,
  Search,
  Trash2,
  X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { DataSet } from "vis-data";
import { Network } from "vis-network";

import Empty from "@/components/Empty";
import { Panel } from "@/components/Panel";
import { SearchableSelect, type SearchableSelectOption } from "@/components/SearchableSelect";
import { useTheme } from "@/hooks/useTheme";
import {
  addGraphEdge,
  batchAddKnowledgeTables,
  deleteGraphEdgeByTables,
  deleteKnowledgeTable,
  extractTableStructure,
  fetchKnowledgeTable,
  fetchKnowledgeTables,
  fetchRelationGraph,
  fetchTableColumnsFromDB,
  updateKnowledgeTable,
  type GraphEdge,
  type GraphEdgeCreate,
} from "@/lib/api";
import type {
  TableFieldInfo,
  TableKnowledgeDetail,
  TableKnowledgeSummary,
  TableKnowledgeUpdate,
} from "@/types";

// ── 域配置 ────────────────────────────────────────────────────────
const DOMAIN_CONFIG: Record<string, { label: string; color: string; borderColor: string }> = {
  production: { label: "生产", color: "#3b82f6", borderColor: "#2563eb" },
  quality: { label: "质量", color: "#22c55e", borderColor: "#16a34a" },
  warehouse: { label: "仓储", color: "#f59e0b", borderColor: "#d97706" },
  equipment: { label: "设备", color: "#8b5cf6", borderColor: "#7c3aed" },
  master: { label: "主数据", color: "#ef4444", borderColor: "#dc2626" },
  barcode: { label: "条码", color: "#06b6d4", borderColor: "#0891b2" },
  other: { label: "其他", color: "#6b7280", borderColor: "#4b5563" },
};

const DOMAIN_MAP: Record<string, string> = {
  "t_pd_": "production",
  "t_qm_": "quality",
  "t_wms_": "warehouse",
  "t_ems_": "equipment",
  "t_bd_": "master",
  "t_bc_": "barcode",
};

function getDomain(table: string): string {
  for (const [prefix, domain] of Object.entries(DOMAIN_MAP)) {
    if (table.startsWith(prefix)) return domain;
  }
  return "other";
}

// ── 模块颜色 ──────────────────────────────────────────────────────
const MODULE_COLORS: Record<string, string> = {
  "条码管理": "bg-cyan-100 text-cyan-800 border-cyan-200",
  "基础数据": "bg-red-100 text-red-800 border-red-200",
  "生产执行": "bg-blue-100 text-blue-800 border-blue-200",
  "质量管理": "bg-green-100 text-green-800 border-green-200",
  "仓储管理": "bg-amber-100 text-amber-800 border-amber-200",
  "设备管理": "bg-purple-100 text-purple-800 border-purple-200",
};

function getModuleColor(mod: string): string {
  return MODULE_COLORS[mod] || "bg-gray-100 text-gray-700 border-gray-200";
}

// ── 空字段行模板 ──────────────────────────────────────────────────
function emptyField(): TableFieldInfo {
  return { name: "", type: "", comment: "" };
}

// ── 组件 ──────────────────────────────────────────────────────────
export default function KnowledgePage() {
  const { isDark } = useTheme();

  // 列表
  const [tables, setTables] = useState<TableKnowledgeSummary[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [errorList, setErrorList] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [moduleFilter, setModuleFilter] = useState("");

  // 详情
  const [selectedTable, setSelectedTable] = useState("");
  const [detail, setDetail] = useState<TableKnowledgeDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [errorDetail, setErrorDetail] = useState("");

  // 编辑
  const [editing, setEditing] = useState(false);
  const [editData, setEditData] = useState<TableKnowledgeDetail | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMessage, setSaveMessage] = useState("");

  // 图数据
  const [graphData, setGraphData] = useState<Record<string, GraphEdge[]> | null>(null);
  const graphContainerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);

  // 从DB同步字段
  const [syncingFields, setSyncingFields] = useState(false);

  // 关系编辑弹窗
  const [relationModalOpen, setRelationModalOpen] = useState(false);
  const [relationEditing, setRelationEditing] = useState<GraphEdge | null>(null);
  const [relationForm, setRelationForm] = useState<GraphEdgeCreate>({
    from_table: "",
    to_table: "",
    from_field: "",
    to_field: "",
    join_condition: "",
    join_type: "LEFT",
    description: "",
    confidence: "high",
    note: "",
  });
  const [savingRelation, setSavingRelation] = useState(false);
  const [fromTableFields, setFromTableFields] = useState<SearchableSelectOption[]>([]);
  const [toTableFields, setToTableFields] = useState<SearchableSelectOption[]>([]);
  const [loadingFromFields, setLoadingFromFields] = useState(false);
  const [loadingToFields, setLoadingToFields] = useState(false);

  // 表名选项（从 tables 列表派生）
  const tableOptions: SearchableSelectOption[] = useMemo(
    () =>
      tables.map((t) => ({
        value: t.table_name,
        label: t.table_name,
        hint: t.business_meaning,
      })),
    [tables],
  );

  // 当源表/目标表变化时，加载对应字段列表
  useEffect(() => {
    if (!relationForm.from_table) {
      setFromTableFields([]);
      setLoadingFromFields(false);
      return;
    }
    // 先用本地知识库已有字段快速填充（有注释），不再被 DB 空数据覆盖
    if (detail && detail.table_name === relationForm.from_table && detail.fields && detail.fields.length > 0) {
      setFromTableFields(
        detail.fields.map((f) => ({ value: f.name, label: f.name, hint: f.comment || f.type })),
      );
      setLoadingFromFields(false);
      return;
    }
    // detail 不是当前表或字段为空，回退到 DB
    setLoadingFromFields(true);
    fetchTableColumnsFromDB(relationForm.from_table)
      .then((cols) => {
        setFromTableFields(
          cols.map((c) => ({ value: c.name, label: c.name, hint: c.comment || c.type })),
        );
        setLoadingFromFields(false);
      })
      .catch((err) => {
        console.error("获取源表字段失败:", relationForm.from_table, err);
        setLoadingFromFields(false);
      });
  }, [relationForm.from_table, detail?.table_name]);

  // 目标表字段：从知识库获取（有注释），知识库没有则回退到 DB
  useEffect(() => {
    if (!relationForm.to_table) {
      setToTableFields([]);
      setLoadingToFields(false);
      return;
    }
    setLoadingToFields(true);
    fetchKnowledgeTable(relationForm.to_table)
      .then((kbDetail) => {
        if (kbDetail.fields && kbDetail.fields.length > 0) {
          setToTableFields(
            kbDetail.fields.map((f) => ({ value: f.name, label: f.name, hint: f.comment || f.type })),
          );
          setLoadingToFields(false);
        } else {
          return fetchTableColumnsFromDB(relationForm.to_table).then((cols) => {
            setToTableFields(
              cols.map((c) => ({ value: c.name, label: c.name, hint: c.comment || c.type })),
            );
            setLoadingToFields(false);
          });
        }
      })
      .catch((err) => {
        console.error("获取目标表字段失败:", relationForm.to_table, err);
        setLoadingToFields(false);
      });
  }, [relationForm.to_table]);

  // 添加表对话框
  const [addTableModalOpen, setAddTableModalOpen] = useState(false);
  const [addTableRawText, setAddTableRawText] = useState("");
  const [addTableExtracting, setAddTableExtracting] = useState(false);
  const [addTableExtracted, setAddTableExtracted] = useState<{
    tables: TableKnowledgeUpdate[];
    relations: GraphEdgeCreate[];
  } | null>(null);
  const [addTableSaving, setAddTableSaving] = useState(false);
  const [addTableMessage, setAddTableMessage] = useState("");

  // ── 提取所有模块 ──
  const modules = useMemo(() => {
    const set = new Set<string>();
    for (const t of tables) {
      if (t.module) set.add(t.module);
    }
    return Array.from(set).sort();
  }, [tables]);

  // ── 加载列表 ──
  const loadList = useCallback(async () => {
    setLoadingList(true);
    setErrorList("");
    try {
      const data = await fetchKnowledgeTables(undefined, undefined);
      setTables(data);
    } catch (e) {
      setErrorList(String(e));
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    loadList();
  }, [loadList]);

  // ── 加载图数据（一次性） ──
  useEffect(() => {
    fetchRelationGraph()
      .then((res) => setGraphData(res.graph))
      .catch(() => {});
  }, []);

  // ── 加载详情 ──
  const loadDetail = useCallback(async (tableName: string) => {
    setSelectedTable(tableName);
    setEditing(false);
    setSaveMessage("");
    setErrorDetail("");
    setLoadingDetail(true);
    try {
      const data = await fetchKnowledgeTable(tableName);
      setDetail(data);
    } catch (e) {
      setErrorDetail(String(e));
      setDetail(null);
    } finally {
      setLoadingDetail(false);
    }
  }, []);

  // ── 渲染迷你关系图 ──
  useEffect(() => {
    if (!graphData || !selectedTable || !graphContainerRef.current || !detail) return;

    // 收集 1 跳邻居
    const neighborTables = new Set<string>();
    const edgesFromSelected: { to: string; join: string; desc: string; confidence: string; note: string }[] = [];
    const edgesToSelected: { from: string; join: string; desc: string; confidence: string; note: string }[] = [];

    // 出边（只展示正向，跳过反向边）
    for (const edge of graphData[selectedTable] || []) {
      if (edge.desc.includes("(反向)")) continue;
      neighborTables.add(edge.to);
      edgesFromSelected.push(edge);
    }
    // 入边（只展示正向，跳过反向边）
    for (const [fromTable, outEdges] of Object.entries(graphData)) {
      if (fromTable === selectedTable) continue;
      for (const edge of outEdges) {
        if (edge.desc.includes("(反向)")) continue;
        if (edge.to === selectedTable) {
          neighborTables.add(fromTable);
          edgesToSelected.push({ from: fromTable, join: edge.join, desc: edge.desc, confidence: edge.confidence, note: edge.note });
        }
      }
    }

    // 构建节点
    const nodes: { id: string; label: string; group: string; title: string; color?: { background: string; border: string; highlight: { background: string; border: string } } }[] = [];
    const edges: { id: string; from: string; to: string; label: string; arrows: string; title: string }[] = [];

    // 中心节点（高亮）
    const centerDomain = getDomain(selectedTable);
    const centerColor = DOMAIN_CONFIG[centerDomain] || DOMAIN_CONFIG.other;
    nodes.push({
      id: selectedTable,
      label: selectedTable,
      group: centerDomain,
      title: `<b>${selectedTable}</b><br/>域: ${centerColor.label}`,
      color: {
        background: centerColor.color,
        border: centerColor.borderColor,
        highlight: { background: centerColor.color, border: centerColor.borderColor },
      },
    });

    // 邻居节点
    for (const neighbor of neighborTables) {
      const domain = getDomain(neighbor);
      const cfg = DOMAIN_CONFIG[domain] || DOMAIN_CONFIG.other;
      nodes.push({
        id: neighbor,
        label: neighbor,
        group: domain,
        title: `<b>${neighbor}</b><br/>域: ${cfg.label}`,
      });
    }

    // 出边
    for (const edge of edgesFromSelected) {
      const key = `${selectedTable}->${edge.to}`;
      if (edges.some((e) => e.id === key)) continue;
      edges.push({
        id: key,
        from: selectedTable,
        to: edge.to,
        label: edge.join,
        arrows: "to",
        title: `<b>${edge.desc}</b><br/>${edge.join}<br/>置信度: ${edge.confidence}${edge.note ? `<br/>⚠️ ${edge.note}` : ""}`,
      });
    }

    // 入边
    for (const edge of edgesToSelected) {
      const key = `${edge.from}->${selectedTable}`;
      if (edges.some((e) => e.id === key)) continue;
      edges.push({
        id: key,
        from: edge.from,
        to: selectedTable,
        label: edge.join,
        arrows: "to",
        title: `<b>${edge.desc}</b><br/>${edge.join}<br/>置信度: ${edge.confidence}${edge.note ? `<br/>⚠️ ${edge.note}` : ""}`,
      });
    }

    const nodesDS = new DataSet(nodes);
    const edgesDS = new DataSet(edges);

    const nodeFontColor = isDark ? "#e8edf2" : "#111822";
    const edgeColor = isDark ? "rgba(255,255,255,0.12)" : "rgba(0,0,0,0.12)";
    const edgeFontColor = isDark ? "#556677" : "#8899aa";

    // 销毁旧网络
    if (networkRef.current) {
      networkRef.current.destroy();
      networkRef.current = null;
    }

    const network = new Network(graphContainerRef.current, { nodes: nodesDS, edges: edgesDS }, {
      nodes: {
        shape: "dot",
        size: 16,
        font: {
          size: 10,
          face: "'JetBrains Mono', monospace",
          color: nodeFontColor,
          strokeWidth: 0,
        },
        borderWidth: 2,
        shadow: { enabled: true, size: 6 },
      },
      edges: {
        width: 1.5,
        color: { color: edgeColor, highlight: "#00c2ff" },
        font: {
          size: 9,
          face: "'JetBrains Mono', monospace",
          color: edgeFontColor,
          strokeWidth: 0,
          align: "top",
        },
        smooth: { enabled: true, type: "continuous", roundness: 0.5 },
        arrows: { to: { scaleFactor: 0.6 } },
      },
      physics: {
        enabled: true,
        solver: "forceAtlas2Based",
        forceAtlas2Based: { gravitationalConstant: -80, springLength: 120 },
        stabilization: { iterations: 100 },
      },
      interaction: {
        hover: true,
        tooltipDelay: 150,
        zoomView: true,
        dragView: true,
      },
    });

    // 点击邻居节点 → 跳转到该表
    network.on("click", (params) => {
      if (params.nodes && params.nodes.length === 1) {
        const clickedNode = params.nodes[0] as string;
        if (clickedNode !== selectedTable) {
          loadDetail(clickedNode);
        }
      }
    });

    networkRef.current = network;

    return () => {
      if (networkRef.current) {
        networkRef.current.destroy();
        networkRef.current = null;
      }
    };
  }, [graphData, selectedTable, detail, isDark, loadDetail]);

  // ── 开始编辑 ──
  const startEdit = () => {
    if (!detail) return;
    setEditData(JSON.parse(JSON.stringify(detail)) as TableKnowledgeDetail);
    setEditing(true);
    setSaveMessage("");
  };

  // ── 取消编辑 ──
  const cancelEdit = () => {
    setEditing(false);
    setEditData(null);
    setSaveMessage("");
  };

  // ── 保存编辑 ──
  const saveEdit = async () => {
    if (!editData || !detail) return;
    setSaving(true);
    setSaveMessage("");
    try {
      await updateKnowledgeTable(detail.table_name, {
        table_name: editData.table_name,
        module: editData.module,
        business_meaning: editData.business_meaning,
        fields: editData.fields,
        relations: editData.relations,
        scenarios: editData.scenarios,
      });
      setSaveMessage("保存成功");
      setEditing(false);
      setEditData(null);
      await loadList();
      await loadDetail(editData.table_name);
    } catch (e) {
      setSaveMessage(`保存失败: ${e}`);
    } finally {
      setSaving(false);
    }
  };

  // ── 字段编辑辅助 ──
  const updateField = (idx: number, key: keyof TableFieldInfo, value: string) => {
    if (!editData) return;
    const fields = [...editData.fields];
    fields[idx] = { ...fields[idx], [key]: value };
    setEditData({ ...editData, fields });
  };

  const addField = () => {
    if (!editData) return;
    setEditData({ ...editData, fields: [...editData.fields, emptyField()] });
  };

  const removeField = (idx: number) => {
    if (!editData) return;
    setEditData({ ...editData, fields: editData.fields.filter((_, i) => i !== idx) });
  };

  // ── 从数据库同步字段 ──
  const syncFieldsFromDB = async () => {
    if (!editData) return;
    setSyncingFields(true);
    try {
      const dbCols = await fetchTableColumnsFromDB(editData.table_name);
      // 合并：DB 字段同步类型和注释，保留 DB 中不存在但用户手动添加的字段
      const existingMap = new Map(editData.fields.map((f) => [f.name.toLowerCase(), f]));
      const merged: TableFieldInfo[] = [];
      for (const col of dbCols) {
        const existing = existingMap.get(col.name.toLowerCase());
        if (existing) {
          merged.push({
            ...existing,
            type: col.type || existing.type,
            comment: col.comment || existing.comment,
          });
          existingMap.delete(col.name.toLowerCase());
        } else {
          merged.push({ name: col.name, type: col.type, comment: col.comment });
        }
      }
      // 保留 DB 中不存在但用户手动添加的字段
      for (const f of existingMap.values()) {
        merged.push(f);
      }
      setEditData({ ...editData, fields: merged });
    } catch (e) {
      alert(`同步失败: ${e}`);
    } finally {
      setSyncingFields(false);
    }
  };

  // ── 删除表 ──
  const handleDeleteTable = async (tableName: string) => {
    if (!window.confirm(`确定删除表 "${tableName}"？此操作将同时从本地文件和 Neo4j 中移除，且不可撤销。`)) return;
    try {
      await deleteKnowledgeTable(tableName);
      // 如果当前选中的是被删除的表，清除选中
      if (selectedTable === tableName) {
        setSelectedTable("");
        setDetail(null);
      }
      await loadList();
      // 刷新图数据
      fetchRelationGraph()
        .then((res) => setGraphData(res.graph))
        .catch(() => {});
    } catch (e) {
      alert(`删除失败: ${e}`);
    }
  };

  // ── 关系管理辅助 ──
  const openAddRelation = () => {
    if (!detail) return;
    setRelationEditing(null);
    setRelationForm({
      from_table: detail.table_name,
      to_table: "",
      from_field: "",
      to_field: "",
      join_condition: "",
      join_type: "LEFT",
      description: "",
      confidence: "high",
      note: "",
    });
    setRelationModalOpen(true);
  };

  const openEditRelation = (edge: GraphEdge, direction: "out" | "in") => {
    if (!detail) return;
    const fromTable = direction === "out" ? detail.table_name : edge.to;
    const toTable = direction === "out" ? edge.to : detail.table_name;
    setRelationEditing(edge);
    setRelationForm({
      from_table: fromTable,
      to_table: toTable,
      from_field: edge.from_field,
      to_field: edge.to_field,
      join_condition: edge.join,
      join_type: edge.join_type || "LEFT",
      description: edge.desc,
      confidence: edge.confidence,
      note: edge.note,
    });
    setRelationModalOpen(true);
  };

  const saveRelation = async () => {
    setSavingRelation(true);
    try {
      await addGraphEdge(relationForm);
      setRelationModalOpen(false);
      // 刷新图数据和详情
      const graphRes = await fetchRelationGraph();
      setGraphData(graphRes.graph);
      if (selectedTable) await loadDetail(selectedTable);
    } catch (e) {
      alert(`保存关系失败: ${e}`);
    } finally {
      setSavingRelation(false);
    }
  };

  const deleteRelation = async (fromTable: string, toTable: string) => {
    if (!confirm(`确认删除 ${fromTable} → ${toTable} 的关系？`)) return;
    try {
      await deleteGraphEdgeByTables(fromTable, toTable);
      // 刷新图数据和详情
      const graphRes = await fetchRelationGraph();
      setGraphData(graphRes.graph);
      if (selectedTable) await loadDetail(selectedTable);
    } catch (e) {
      alert(`删除关系失败: ${e}`);
    }
  };

  // ── 添加表对话框辅助 ──
  const openAddTableModal = () => {
    setAddTableRawText("");
    setAddTableExtracted(null);
    setAddTableMessage("");
    setAddTableModalOpen(true);
  };

  const handleExtractTables = async () => {
    if (!addTableRawText.trim()) return;
    setAddTableExtracting(true);
    setAddTableMessage("");
    try {
      const result = await extractTableStructure(addTableRawText);
      setAddTableExtracted(result);
      if (result.tables.length === 0) {
        setAddTableMessage("未能从文本中抽取到表结构，请检查输入内容");
      }
    } catch (e) {
      setAddTableMessage(`抽取失败: ${e}`);
    } finally {
      setAddTableExtracting(false);
    }
  };

  const handleBatchAddTables = async () => {
    if (!addTableExtracted) return;
    setAddTableSaving(true);
    setAddTableMessage("");
    try {
      const result = await batchAddKnowledgeTables(
        addTableExtracted.tables,
        addTableExtracted.relations,
      );
      setAddTableMessage(result.message);
      // 刷新列表和图数据
      await loadList();
      const graphRes = await fetchRelationGraph();
      setGraphData(graphRes.graph);
      // 如果只添加了一张表，自动选中
      if (result.table_names.length === 1) {
        await loadDetail(result.table_names[0]);
      }
    } catch (e) {
      setAddTableMessage(`添加失败: ${e}`);
    } finally {
      setAddTableSaving(false);
    }
  };

  const updateExtractedField = (
    tableIdx: number,
    fieldIdx: number,
    key: keyof TableFieldInfo,
    value: string,
  ) => {
    if (!addTableExtracted) return;
    const newTables = [...addTableExtracted.tables];
    const fields = [...newTables[tableIdx].fields];
    fields[fieldIdx] = { ...fields[fieldIdx], [key]: value };
    newTables[tableIdx] = { ...newTables[tableIdx], fields };
    setAddTableExtracted({ ...addTableExtracted, tables: newTables });
  };

  const updateExtractedTableField = (
    tableIdx: number,
    key: keyof TableKnowledgeUpdate,
    value: string | string[],
  ) => {
    if (!addTableExtracted) return;
    const newTables = [...addTableExtracted.tables];
    newTables[tableIdx] = { ...newTables[tableIdx], [key]: value };
    setAddTableExtracted({ ...addTableExtracted, tables: newTables });
  };

  // ── 文本行编辑辅助 ──
  const updateTextLines = (key: "relations" | "scenarios", value: string) => {
    if (!editData) return;
    setEditData({
      ...editData,
      [key]: value.split("\n").filter((line) => line.trim()),
    });
  };

  // ── 过滤后的列表 ──
  const filteredTables = useMemo(() => {
    let result = tables;
    if (moduleFilter) {
      result = result.filter((t) => t.module === moduleFilter);
    }
    if (searchTerm) {
      const lower = searchTerm.toLowerCase();
      result = result.filter((t) => t.table_name.toLowerCase().includes(lower));
    }
    return result;
  }, [tables, moduleFilter, searchTerm]);

  // ── 计算邻居数 ──
  const neighborCount = useMemo(() => {
    if (!graphData || !selectedTable) return 0;
    const neighbors = new Set<string>();
    for (const edge of graphData[selectedTable] || []) {
      if (edge.desc.includes("(反向)")) continue;
      neighbors.add(edge.to);
    }
    for (const [fromTable, outEdges] of Object.entries(graphData)) {
      if (fromTable === selectedTable) continue;
      for (const edge of outEdges) {
        if (edge.desc.includes("(反向)")) continue;
        if (edge.to === selectedTable) neighbors.add(fromTable);
      }
    }
    return neighbors.size;
  }, [graphData, selectedTable]);

  return (
    <div className="flex h-screen flex-col bg-[var(--bg-default)]">
      {/* ── 主体 ── */}
      <div className="flex flex-1 overflow-hidden">
        {/* ── 左侧列表 ── */}
        <aside className="flex w-80 shrink-0 flex-col border-r border-[var(--border-default)]">
          <div className="space-y-2 border-b border-[var(--border-default)] p-3">
            {/* 搜索框 */}
            <div className="relative">
              <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-tertiary)]" />
              <input
                type="text"
                placeholder="搜索表名..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] py-1.5 pl-8 pr-2 text-xs text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent)] focus:outline-none"
              />
            </div>
            {/* 模块过滤 */}
            <select
              value={moduleFilter}
              onChange={(e) => setModuleFilter(e.target.value)}
              className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] py-1.5 px-2 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
            >
              <option value="">全部模块</option>
              {modules.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
            </select>
            {/* 添加表按钮 */}
            <button
              onClick={openAddTableModal}
              className="inline-flex w-full items-center justify-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90"
            >
              <Plus size={13} />
              添加表
            </button>
          </div>

          {/* 表列表 */}
          <div className="flex-1 overflow-y-auto">
            {loadingList ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 size={20} className="animate-spin text-[var(--text-tertiary)]" />
              </div>
            ) : errorList ? (
              <div className="p-4 text-xs text-[var(--error)]">{errorList}</div>
            ) : filteredTables.length === 0 ? (
              <Empty message={searchTerm || moduleFilter ? "无匹配结果" : "暂无数据"} />
            ) : (
              <ul className="divide-y divide-[var(--border-subtle)]">
                {filteredTables.map((t) => (
                  <li
                    key={t.table_name}
                    onClick={() => loadDetail(t.table_name)}
                    className={`cursor-pointer px-4 py-2.5 transition-colors hover:bg-[var(--bg-hover)] ${
                      selectedTable === t.table_name ? "bg-[var(--bg-raised)] border-l-2 border-l-[var(--accent)]" : ""
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-mono text-xs font-medium text-[var(--text-primary)] truncate">
                        {t.table_name}
                      </span>
                      <span
                        className={`shrink-0 rounded border px-1.5 py-0.5 text-[10px] font-medium ${getModuleColor(t.module)}`}
                      >
                        {t.module}
                      </span>
                    </div>
                    <div className="mt-0.5 flex items-center justify-between">
                      <div className="flex items-center gap-2 text-[11px] text-[var(--text-tertiary)]">
                        <span>{t.business_meaning || "无说明"}</span>
                        <span>{t.field_count} 个字段</span>
                      </div>
                      <button
                        onClick={(e) => { e.stopPropagation(); handleDeleteTable(t.table_name); }}
                        className="rounded p-0.5 text-[var(--text-tertiary)] hover:bg-red-50 hover:text-red-600"
                        title={`删除 ${t.table_name}`}
                      >
                        <Trash2 size={13} />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>

        {/* ── 右侧详情 ── */}
        <main className="flex-1 overflow-y-auto p-6">
          {!selectedTable ? (
            <Empty message="请从左侧选择一张表查看详情" />
          ) : loadingDetail ? (
            <div className="flex items-center justify-center py-20">
              <Loader2 size={24} className="animate-spin text-[var(--text-tertiary)]" />
            </div>
          ) : errorDetail ? (
            <div className="p-4 text-sm text-[var(--error)]">{errorDetail}</div>
          ) : detail ? (
            <div className="mx-auto max-w-4xl space-y-5">
              {/* ── 保存提示 ── */}
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

              {/* ── 关系图面板 ── */}
              {!editing && (
                <Panel title={`关联关系图（${neighborCount} 个关联表）`}>
                  <div
                    ref={graphContainerRef}
                    className="h-64 w-full rounded border border-[var(--border-default)] bg-[var(--bg-subtle)]"
                  />
                  <p className="mt-1.5 text-[10px] text-[var(--text-tertiary)]">
                    点击节点可跳转到对应表 | 拖拽/缩放可交互
                  </p>
                </Panel>
              )}

              <Panel
                title={editing ? "编辑表信息" : "表信息"}
                action={
                  editing ? (
                    <div className="flex items-center gap-2">
                      <button
                        onClick={saveEdit}
                        disabled={saving}
                        className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                      >
                        {saving ? (
                          <Loader2 size={13} className="animate-spin" />
                        ) : (
                          <Save size={13} />
                        )}
                        保存
                      </button>
                      <button
                        onClick={cancelEdit}
                        disabled={saving}
                        className="rounded px-2 py-1.5 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
                      >
                        取消
                      </button>
                    </div>
                  ) : (
                    <button
                      onClick={startEdit}
                      className="inline-flex items-center gap-1 rounded px-2.5 py-1.5 text-xs text-[var(--accent)] transition-colors hover:bg-[var(--bg-hover)]"
                    >
                      <Edit3 size={13} />
                      编辑
                    </button>
                  )
                }
              >
                {editing && editData ? (
                  /* ── 编辑模式 ── */
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-3">
                      <label className="space-y-1">
                        <span className="text-[11px] font-medium text-[var(--text-secondary)]">表名</span>
                        <input
                          type="text"
                          value={editData.table_name}
                          onChange={(e) => setEditData({ ...editData, table_name: e.target.value })}
                          className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 font-mono text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                        />
                      </label>
                      <label className="space-y-1">
                        <span className="text-[11px] font-medium text-[var(--text-secondary)]">模块</span>
                        <select
                          value={editData.module}
                          onChange={(e) => setEditData({ ...editData, module: e.target.value })}
                          className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                        >
                          {modules.map((m) => (
                            <option key={m} value={m}>{m}</option>
                          ))}
                        </select>
                      </label>
                    </div>
                    <label className="block space-y-1">
                      <span className="text-[11px] font-medium text-[var(--text-secondary)]">业务含义</span>
                      <input
                        type="text"
                        value={editData.business_meaning}
                        onChange={(e) => setEditData({ ...editData, business_meaning: e.target.value })}
                        className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                      />
                    </label>

                    {/* 字段表格 */}
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-medium text-[var(--text-secondary)]">关键字段</span>
                        <div className="flex items-center gap-2">
                          <button
                            onClick={syncFieldsFromDB}
                            disabled={syncingFields}
                            className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[11px] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--accent)] disabled:opacity-50"
                          >
                            {syncingFields ? <Loader2 size={12} className="animate-spin" /> : <Database size={12} />}
                            从DB同步
                          </button>
                          <button
                            onClick={addField}
                            className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[11px] text-[var(--accent)] hover:bg-[var(--bg-hover)]"
                          >
                            <Plus size={12} /> 添加
                          </button>
                        </div>
                      </div>
                      <div className="overflow-x-auto rounded border border-[var(--border-default)]">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-[var(--border-default)] bg-[var(--bg-raised)]">
                              <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">字段名</th>
                              <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">类型</th>
                              <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">说明</th>
                              <th className="w-10 px-3 py-2" />
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-[var(--border-subtle)]">
                            {editData.fields.map((f, idx) => (
                              <tr key={idx}>
                                <td className="px-3 py-1.5">
                                  <input
                                    type="text"
                                    value={f.name}
                                    onChange={(e) => updateField(idx, "name", e.target.value)}
                                    placeholder="字段名"
                                    className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 font-mono text-xs text-[var(--text-primary)] hover:border-[var(--border-default)] focus:border-[var(--accent)] focus:outline-none"
                                  />
                                </td>
                                <td className="px-3 py-1.5">
                                  <input
                                    type="text"
                                    value={f.type}
                                    onChange={(e) => updateField(idx, "type", e.target.value)}
                                    placeholder="varchar(40)"
                                    className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 font-mono text-xs text-[var(--text-primary)] hover:border-[var(--border-default)] focus:border-[var(--accent)] focus:outline-none"
                                  />
                                </td>
                                <td className="px-3 py-1.5">
                                  <input
                                    type="text"
                                    value={f.comment}
                                    onChange={(e) => updateField(idx, "comment", e.target.value)}
                                    placeholder="字段说明"
                                    className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-xs text-[var(--text-primary)] hover:border-[var(--border-default)] focus:border-[var(--accent)] focus:outline-none"
                                  />
                                </td>
                                <td className="px-3 py-1.5">
                                  <button
                                    onClick={() => removeField(idx)}
                                    className="rounded p-0.5 text-[var(--text-tertiary)] hover:bg-[var(--bg-hover)] hover:text-[var(--error)]"
                                  >
                                    <X size={13} />
                                  </button>
                                </td>
                              </tr>
                            ))}
                            {editData.fields.length === 0 && (
                              <tr>
                                <td colSpan={4} className="px-3 py-4 text-center text-[var(--text-tertiary)]">
                                  暂无字段，点击"添加"新增
                                </td>
                              </tr>
                            )}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    {/* 关联关系 - 结构化列表 */}
                    <div className="space-y-2">
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-medium text-[var(--text-secondary)]">关联关系</span>
                        <button
                          onClick={openAddRelation}
                          className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[11px] text-[var(--accent)] hover:bg-[var(--bg-hover)]"
                        >
                          <Plus size={12} /> 添加关系
                        </button>
                      </div>
                      {(() => {
                        const currentTable = editData.table_name;
                        const outEdges = graphData?.[currentTable] || [];
                        const inEdges: { from: string; edge: GraphEdge }[] = [];
                        if (graphData) {
                          for (const [fromTable, edges] of Object.entries(graphData)) {
                            if (fromTable === currentTable) continue;
                            for (const edge of edges) {
                              if (edge.to === currentTable) {
                                inEdges.push({ from: fromTable, edge });
                              }
                            }
                          }
                        }
                        // 双向正向边去重：若 A→B 和 B→A 都存在，仅保留 from < to 的方向
                        const outTargets = new Set(outEdges.map(e => e.to));
                        const filteredOutEdges = outEdges.filter(e => {
                          const hasReverse = inEdges.some(ie => ie.from === e.to);
                          return !(hasReverse && currentTable > e.to);
                        });
                        const filteredInEdges = inEdges.filter(ie => {
                          const hasReverse = outTargets.has(ie.from);
                          return !(hasReverse && ie.from > currentTable);
                        });
                        const allRelations = [
                          ...filteredOutEdges.map((e) => ({ direction: "out" as const, from: currentTable, to: e.to, edge: e })),
                          ...filteredInEdges.map(({ from, edge }) => ({ direction: "in" as const, from, to: currentTable, edge })),
                        ];
                        return allRelations.length > 0 ? (
                          <div className="space-y-1">
                            {allRelations.map((rel, idx) => (
                              <div
                                key={idx}
                                className="flex items-center gap-2 rounded border border-[var(--border-default)] px-2.5 py-1.5 text-[11px]"
                              >
                                <span className="font-mono text-[var(--text-primary)]">{rel.from}</span>
                                <span className="text-[var(--text-tertiary)]">→</span>
                                <span className="font-mono text-[var(--text-primary)]">{rel.to}</span>
                                {rel.edge.from_field && rel.edge.to_field && (
                                  <span className="text-[var(--text-tertiary)]">
                                    ({rel.edge.from_field}={rel.edge.to_field})
                                  </span>
                                )}
                                {rel.edge.desc && (
                                  <span className="text-[var(--text-secondary)]">{rel.edge.desc}</span>
                                )}
                                <div className="ml-auto flex items-center gap-1">
                                  <button
                                    onClick={() => openEditRelation(rel.edge, rel.direction)}
                                    className="rounded p-0.5 text-[var(--text-tertiary)] hover:bg-[var(--bg-hover)] hover:text-[var(--accent)]"
                                    title="编辑"
                                  >
                                    <Edit3 size={12} />
                                  </button>
                                  <button
                                    onClick={() => deleteRelation(rel.from, rel.to)}
                                    className="rounded p-0.5 text-[var(--text-tertiary)] hover:bg-[var(--bg-hover)] hover:text-[var(--error)]"
                                    title="删除"
                                  >
                                    <Trash2 size={12} />
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="text-[11px] text-[var(--text-tertiary)]">暂无关联关系，点击"添加关系"新增</p>
                        );
                      })()}
                    </div>

                    {/* 适用场景 */}
                    <label className="block space-y-1">
                      <span className="text-[11px] font-medium text-[var(--text-secondary)]">适用场景</span>
                      <textarea
                        value={(editData.scenarios || []).join("\n")}
                        onChange={(e) => updateTextLines("scenarios", e.target.value)}
                        rows={3}
                        className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 text-[11px] text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                      />
                    </label>
                  </div>
                ) : (
                  /* ── 查看模式 ── */
                  <div className="space-y-4">
                    <div className="grid grid-cols-2 gap-3">
                      <div>
                        <span className="text-[11px] font-medium text-[var(--text-tertiary)]">表名</span>
                        <p className="mt-0.5 font-mono text-sm text-[var(--text-primary)]">{detail.table_name}</p>
                      </div>
                      <div>
                        <span className="text-[11px] font-medium text-[var(--text-tertiary)]">模块</span>
                        <p className="mt-0.5">
                          <span className={`inline-block rounded border px-1.5 py-0.5 text-[11px] font-medium ${getModuleColor(detail.module)}`}>
                            {detail.module}
                          </span>
                        </p>
                      </div>
                    </div>
                    <div>
                      <span className="text-[11px] font-medium text-[var(--text-tertiary)]">业务含义</span>
                      <p className="mt-0.5 text-sm text-[var(--text-primary)]">{detail.business_meaning || "无"}</p>
                    </div>

                    {/* 字段表格 */}
                    <div>
                      <span className="text-[11px] font-medium text-[var(--text-tertiary)]">
                        关键字段（{detail.fields.length}）
                      </span>
                      <div className="mt-1.5 overflow-x-auto rounded border border-[var(--border-default)]">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-[var(--border-default)] bg-[var(--bg-raised)]">
                              <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">字段名</th>
                              <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">类型</th>
                              <th className="px-3 py-2 text-left font-medium text-[var(--text-secondary)]">说明</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-[var(--border-subtle)]">
                            {detail.fields.map((f, idx) => (
                              <tr key={idx} className="hover:bg-[var(--bg-hover)]">
                                <td className="px-3 py-1.5 font-mono text-[var(--text-primary)]">{f.name}</td>
                                <td className="px-3 py-1.5 font-mono text-[var(--text-tertiary)]">{f.type}</td>
                                <td className="px-3 py-1.5 text-[var(--text-secondary)]">{f.comment}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    {/* 关联关系 */}
                    <div>
                      <div className="flex items-center justify-between">
                        <span className="text-[11px] font-medium text-[var(--text-tertiary)]">关联关系</span>
                        <button
                          onClick={openAddRelation}
                          className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-[11px] text-[var(--accent)] hover:bg-[var(--bg-hover)]"
                        >
                          <Plus size={12} /> 添加关系
                        </button>
                      </div>
                      {(() => {
                        const currentTable = detail.table_name;
                        const outEdges = (graphData?.[currentTable] || []).filter(e => !e.desc?.includes("(反向)"));
                        const inEdges: { from: string; edge: GraphEdge }[] = [];
                        if (graphData) {
                          for (const [fromTable, edges] of Object.entries(graphData)) {
                            if (fromTable === currentTable) continue;
                            for (const edge of edges) {
                              if (edge.to === currentTable && !edge.desc?.includes("(反向)")) {
                                inEdges.push({ from: fromTable, edge });
                              }
                            }
                          }
                        }
                        // 双向正向边去重：若 A→B 和 B→A 都存在，仅保留 from < to 的方向
                        const outTargets = new Set(outEdges.map(e => e.to));
                        const filteredOutEdges = outEdges.filter(e => {
                          const hasReverse = inEdges.some(ie => ie.from === e.to);
                          return !(hasReverse && currentTable > e.to);
                        });
                        const filteredInEdges = inEdges.filter(ie => {
                          const hasReverse = outTargets.has(ie.from);
                          return !(hasReverse && ie.from > currentTable);
                        });
                        const allRels = [
                          ...filteredOutEdges.map((e) => ({ direction: "out" as const, from: currentTable, to: e.to, edge: e })),
                          ...filteredInEdges.map(({ from, edge }) => ({ direction: "in" as const, from, to: currentTable, edge })),
                        ];
                        return allRels.length > 0 ? (
                          <div className="mt-1.5 space-y-1">
                            {allRels.map((rel, idx) => (
                              <div
                                key={idx}
                                className="flex items-center gap-2 rounded border border-[var(--border-default)] px-2.5 py-1.5 text-[11px]"
                              >
                                <span className="font-mono text-[var(--text-primary)]">{rel.from}</span>
                                <span className="text-[var(--text-tertiary)]">→</span>
                                <span className="font-mono text-[var(--text-primary)]">{rel.to}</span>
                                {rel.edge.from_field && rel.edge.to_field && (
                                  <span className="text-[var(--text-tertiary)]">
                                    ({rel.edge.from_field}={rel.edge.to_field})
                                  </span>
                                )}
                                {rel.edge.desc && (
                                  <span className="text-[var(--text-secondary)]">{rel.edge.desc}</span>
                                )}
                                <div className="ml-auto flex items-center gap-1">
                                  <button
                                    onClick={() => openEditRelation(rel.edge, rel.direction)}
                                    className="rounded p-0.5 text-[var(--text-tertiary)] hover:bg-[var(--bg-hover)] hover:text-[var(--accent)]"
                                    title="编辑"
                                  >
                                    <Edit3 size={12} />
                                  </button>
                                  <button
                                    onClick={() => deleteRelation(rel.from, rel.to)}
                                    className="rounded p-0.5 text-[var(--text-tertiary)] hover:bg-[var(--bg-hover)] hover:text-[var(--error)]"
                                    title="删除"
                                  >
                                    <Trash2 size={12} />
                                  </button>
                                </div>
                              </div>
                            ))}
                          </div>
                        ) : (
                          <p className="mt-0.5 text-xs text-[var(--text-tertiary)]">无</p>
                        );
                      })()}
                    </div>

                    {/* 适用场景 */}
                    <div>
                      <span className="text-[11px] font-medium text-[var(--text-tertiary)]">适用场景</span>
                      {detail.scenarios.length > 0 ? (
                        <ul className="mt-1 list-inside list-disc space-y-0.5">
                          {detail.scenarios.map((s, idx) => (
                            <li key={idx} className="text-xs text-[var(--text-secondary)]">{s}</li>
                          ))}
                        </ul>
                      ) : (
                        <p className="mt-0.5 text-xs text-[var(--text-tertiary)]">无</p>
                      )}
                    </div>
                  </div>
                )}
              </Panel>
            </div>
          ) : null}
        </main>
      </div>

      {/* ── 关系编辑弹窗 ── */}
      {relationModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-[480px] overflow-visible rounded-lg border border-[var(--border-default)] bg-white backdrop-blur-sm p-5 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">
                {relationEditing ? "编辑关系" : "添加关系"}
              </h3>
              <button
                onClick={() => setRelationModalOpen(false)}
                className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--bg-hover)]"
              >
                <X size={16} />
              </button>
            </div>
            <div className="space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <label className="space-y-1">
                  <span className="text-[11px] font-medium text-[var(--text-secondary)]">源表</span>
                  <span className="block w-full rounded border border-[var(--border-default)] bg-[var(--bg-subtle)] px-2 py-1.5 font-mono text-xs text-[var(--text-primary)]">
                    {relationForm.from_table}
                  </span>
                </label>
                <label className="space-y-1">
                  <span className="text-[11px] font-medium text-[var(--text-secondary)]">目标表</span>
                  <SearchableSelect
                    options={tableOptions}
                    value={relationForm.to_table}
                    onChange={(v) => setRelationForm({ ...relationForm, to_table: v, to_field: "" })}
                    placeholder="搜索表名..."
                  />
                </label>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label className="space-y-1">
                  <span className="text-[11px] font-medium text-[var(--text-secondary)]">
                    源字段
                    {loadingFromFields && (
                      <span className="ml-1 inline-block h-2 w-2 animate-spin rounded-full border border-[var(--accent)] border-t-transparent" />
                    )}
                  </span>
                  <SearchableSelect
                    options={fromTableFields}
                    value={relationForm.from_field}
                    onChange={(v) => setRelationForm({ ...relationForm, from_field: v })}
                    placeholder={relationForm.from_table ? loadingFromFields ? "加载中..." : "搜索字段..." : "请先选择源表"}
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-[11px] font-medium text-[var(--text-secondary)]">
                    目标字段
                    {loadingToFields && (
                      <span className="ml-1 inline-block h-2 w-2 animate-spin rounded-full border border-[var(--accent)] border-t-transparent" />
                    )}
                  </span>
                  <SearchableSelect
                    options={toTableFields}
                    value={relationForm.to_field}
                    onChange={(v) => setRelationForm({ ...relationForm, to_field: v })}
                    placeholder={relationForm.to_table ? loadingToFields ? "加载中..." : "搜索字段..." : "请先选择目标表"}
                  />
                </label>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label className="space-y-1">
                  <span className="text-[11px] font-medium text-[var(--text-secondary)]">JOIN 条件</span>
                  <input
                    type="text"
                    value={relationForm.join_condition}
                    onChange={(e) => setRelationForm({ ...relationForm, join_condition: e.target.value })}
                    placeholder="a.work_order = b.work_order"
                    className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2 py-1.5 font-mono text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-[11px] font-medium text-[var(--text-secondary)]">JOIN 类型</span>
                  <select
                    value={relationForm.join_type}
                    onChange={(e) => setRelationForm({ ...relationForm, join_type: e.target.value })}
                    className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                  >
                    <option value="LEFT">LEFT JOIN</option>
                    <option value="INNER">INNER JOIN</option>
                    <option value="RIGHT">RIGHT JOIN</option>
                  </select>
                </label>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <label className="space-y-1">
                  <span className="text-[11px] font-medium text-[var(--text-secondary)]">描述</span>
                  <input
                    type="text"
                    value={relationForm.description}
                    onChange={(e) => setRelationForm({ ...relationForm, description: e.target.value })}
                    placeholder="工单→SN状态"
                    className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                  />
                </label>
                <label className="space-y-1">
                  <span className="text-[11px] font-medium text-[var(--text-secondary)]">置信度</span>
                  <select
                    value={relationForm.confidence}
                    onChange={(e) => setRelationForm({ ...relationForm, confidence: e.target.value })}
                    className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                  >
                    <option value="high">高</option>
                    <option value="medium">中</option>
                    <option value="low">低</option>
                  </select>
                </label>
              </div>
              <label className="space-y-1">
                <span className="text-[11px] font-medium text-[var(--text-secondary)]">备注</span>
                <input
                  type="text"
                  value={relationForm.note}
                  onChange={(e) => setRelationForm({ ...relationForm, note: e.target.value })}
                  placeholder="可选备注"
                  className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                />
              </label>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button
                onClick={() => setRelationModalOpen(false)}
                className="rounded px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
              >
                取消
              </button>
              <button
                onClick={saveRelation}
                disabled={savingRelation || !relationForm.from_table || !relationForm.to_table}
                className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
              >
                {savingRelation ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                保存
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── 添加表对话框 ── */}
      {addTableModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/20 backdrop-blur-sm">
          <div className="max-h-[90vh] w-[720px] overflow-y-auto rounded-lg border border-[var(--border-default)] bg-white p-5 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">添加表</h3>
              <button
                onClick={() => setAddTableModalOpen(false)}
                className="rounded-md p-1.5 text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]"
                title="关闭"
              >
                <X size={18} />
              </button>
            </div>

            {/* 消息提示 */}
            {addTableMessage && (
              <div
                className={`mb-3 rounded border px-3 py-2 text-xs ${
                  addTableMessage.includes("失败") || addTableMessage.includes("未能")
                    ? "border-red-300 bg-red-50 text-red-700"
                    : "border-green-300 bg-green-50 text-green-700"
                }`}
              >
                {addTableMessage}
              </div>
            )}

            {/* 步骤1：粘贴文本 */}
            {!addTableExtracted && (
              <div className="space-y-3">
                <div>
                  <span className="text-[11px] font-medium text-[var(--text-secondary)]">
                    粘贴表结构文本（DDL / CREATE TABLE / 任意格式）
                  </span>
                  <textarea
                    value={addTableRawText}
                    onChange={(e) => setAddTableRawText(e.target.value)}
                    rows={12}
                    placeholder={`示例：\nCREATE TABLE t_bd_part (\n  id varchar(40) NOT NULL,\n  part_no varchar(40) COMMENT '料号',\n  part_name varchar(2000) COMMENT '品名',\n  part_spec varchar(2000) COMMENT '规格',\n  PRIMARY KEY (id)\n) COMMENT='物料主表';`}
                    className="mt-1 w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 font-mono text-xs text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent)] focus:outline-none"
                  />
                </div>
                <div className="flex justify-end">
                  <button
                    onClick={handleExtractTables}
                    disabled={addTableExtracting || !addTableRawText.trim()}
                    className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
                  >
                    {addTableExtracting ? <Loader2 size={13} className="animate-spin" /> : <Search size={13} />}
                    智能抽取
                  </button>
                </div>
              </div>
            )}

            {/* 步骤2：预览和编辑抽取结果 */}
            {addTableExtracted && (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-[11px] font-medium text-[var(--text-secondary)]">
                    抽取结果：{addTableExtracted.tables.length} 张表
                    {addTableExtracted.relations.length > 0 &&
                      `、${addTableExtracted.relations.length} 条关联关系`}
                  </span>
                  <button
                    onClick={() => {
                      setAddTableExtracted(null);
                      setAddTableMessage("");
                    }}
                    className="text-[11px] text-[var(--accent)] hover:underline"
                  >
                    重新输入
                  </button>
                </div>

                {/* 表列表 */}
                {addTableExtracted.tables.map((table, tIdx) => (
                  <div
                    key={tIdx}
                    className="rounded border border-[var(--border-default)] p-3 space-y-2"
                  >
                    <div className="grid grid-cols-3 gap-2">
                      <label className="space-y-0.5">
                        <span className="text-[10px] font-medium text-[var(--text-tertiary)]">表名</span>
                        <input
                          type="text"
                          value={table.table_name}
                          onChange={(e) => updateExtractedTableField(tIdx, "table_name", e.target.value)}
                          className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2 py-1 font-mono text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                        />
                      </label>
                      <label className="space-y-0.5">
                        <span className="text-[10px] font-medium text-[var(--text-tertiary)]">模块</span>
                        <input
                          type="text"
                          value={table.module}
                          onChange={(e) => updateExtractedTableField(tIdx, "module", e.target.value)}
                          className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2 py-1 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                        />
                      </label>
                      <label className="space-y-0.5">
                        <span className="text-[10px] font-medium text-[var(--text-tertiary)]">业务含义</span>
                        <input
                          type="text"
                          value={table.business_meaning}
                          onChange={(e) => updateExtractedTableField(tIdx, "business_meaning", e.target.value)}
                          className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2 py-1 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                        />
                      </label>
                    </div>

                    {/* 字段表格 */}
                    <div>
                      <span className="text-[10px] font-medium text-[var(--text-tertiary)]">
                        字段（{table.fields.length}）
                      </span>
                      <div className="mt-0.5 max-h-40 overflow-y-auto rounded border border-[var(--border-default)]">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-[var(--border-default)] bg-[var(--bg-raised)]">
                              <th className="px-2 py-1 text-left font-medium text-[var(--text-secondary)]">字段名</th>
                              <th className="px-2 py-1 text-left font-medium text-[var(--text-secondary)]">类型</th>
                              <th className="px-2 py-1 text-left font-medium text-[var(--text-secondary)]">说明</th>
                            </tr>
                          </thead>
                          <tbody className="divide-y divide-[var(--border-subtle)]">
                            {table.fields.map((f, fIdx) => (
                              <tr key={fIdx}>
                                <td className="px-2 py-0.5">
                                  <input
                                    type="text"
                                    value={f.name}
                                    onChange={(e) => updateExtractedField(tIdx, fIdx, "name", e.target.value)}
                                    className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 font-mono text-xs text-[var(--text-primary)] hover:border-[var(--border-default)] focus:border-[var(--accent)] focus:outline-none"
                                  />
                                </td>
                                <td className="px-2 py-0.5">
                                  <input
                                    type="text"
                                    value={f.type}
                                    onChange={(e) => updateExtractedField(tIdx, fIdx, "type", e.target.value)}
                                    className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 font-mono text-xs text-[var(--text-primary)] hover:border-[var(--border-default)] focus:border-[var(--accent)] focus:outline-none"
                                  />
                                </td>
                                <td className="px-2 py-0.5">
                                  <input
                                    type="text"
                                    value={f.comment}
                                    onChange={(e) => updateExtractedField(tIdx, fIdx, "comment", e.target.value)}
                                    className="w-full rounded border border-transparent bg-transparent px-1 py-0.5 text-xs text-[var(--text-primary)] hover:border-[var(--border-default)] focus:border-[var(--accent)] focus:outline-none"
                                  />
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>

                    {/* 适用场景 */}
                    <label className="block space-y-0.5">
                      <span className="text-[10px] font-medium text-[var(--text-tertiary)]">适用场景</span>
                      <input
                        type="text"
                        value={(table.scenarios || []).join(", ")}
                        onChange={(e) =>
                          updateExtractedTableField(
                            tIdx,
                            "scenarios",
                            e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                          )
                        }
                        placeholder="场景1, 场景2"
                        className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2 py-1 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                      />
                    </label>
                  </div>
                ))}

                {/* 关联关系 */}
                {addTableExtracted.relations.length > 0 && (
                  <div>
                    <span className="text-[10px] font-medium text-[var(--text-tertiary)]">
                      关联关系（{addTableExtracted.relations.length}）
                    </span>
                    <div className="mt-0.5 space-y-1">
                      {addTableExtracted.relations.map((rel, rIdx) => (
                        <div
                          key={rIdx}
                          className="flex items-center gap-2 rounded border border-[var(--border-default)] px-2 py-1 text-[11px]"
                        >
                          <span className="font-mono text-[var(--text-primary)]">{rel.from_table}</span>
                          <span className="text-[var(--text-tertiary)]">→</span>
                          <span className="font-mono text-[var(--text-primary)]">{rel.to_table}</span>
                          {rel.from_field && rel.to_field && (
                            <span className="text-[var(--text-tertiary)]">
                              ({rel.from_field}={rel.to_field})
                            </span>
                          )}
                          {rel.description && (
                            <span className="text-[var(--text-secondary)]">{rel.description}</span>
                          )}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                <div className="flex justify-end gap-2 pt-2">
                  <button
                    onClick={() => setAddTableModalOpen(false)}
                    className="rounded px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
                  >
                    取消
                  </button>
                  <button
                    onClick={handleBatchAddTables}
                    disabled={addTableSaving || addTableExtracted.tables.length === 0}
                    className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
                  >
                    {addTableSaving ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
                    确认添加（{addTableExtracted.tables.length} 张表）
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
