import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Network } from "vis-network";
import { DataSet } from "vis-data";
import { ArrowLeft, Edit3, Filter, Loader2, Moon, Plus, RefreshCw, Save, Search, Sun, Trash2, X, ZoomIn, ZoomOut } from "lucide-react";

import {
  addGraphEdge,
  deleteGraphEdge,
  fetchRelationGraph,
  listGraphEdges,
  syncGraphFromJson,
  updateGraphEdge,
  type GraphEdge,
  type GraphEdgeCreate,
  type GraphEdgeRecord,
} from "@/lib/api";
import { useTheme } from "@/hooks/useTheme";

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

// ── 类型 ──────────────────────────────────────────────────────────
interface EdgeInfo {
  from: string;
  to: string;
  label: string;
  joinOn: string;
  desc: string;
  confidence: string;
  note: string;
  joinType: string;
  fromField: string;
  toField: string;
  edgeId?: number;
}

// ── 组件 ──────────────────────────────────────────────────────────
export default function GraphPage() {
  const containerRef = useRef<HTMLDivElement>(null);
  const networkRef = useRef<Network | null>(null);
  const { isDark, toggleTheme } = useTheme();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [selectedEdge, setSelectedEdge] = useState<EdgeInfo | null>(null);
  const [domainFilter, setDomainFilter] = useState<Set<string>>(new Set());
  const [graphData, setGraphData] = useState<Record<string, GraphEdge[]> | null>(null);

  // 编辑模式
  const [editMode, setEditMode] = useState(false);
  const [edgeRecords, setEdgeRecords] = useState<GraphEdgeRecord[]>([]);
  const [showEditor, setShowEditor] = useState(false);
  const [editingEdge, setEditingEdge] = useState<GraphEdgeRecord | null>(null);
  const [saving, setSaving] = useState(false);
  const [syncing, setSyncing] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");

  // 表单
  const [form, setForm] = useState<GraphEdgeCreate>({
    from_table: "",
    to_table: "",
    from_field: "",
    to_field: "",
    join_condition: "",
    join_type: "JOIN",
    description: "",
    confidence: "high",
    note: "",
  });

  // 加载图数据
  useEffect(() => {
    fetchRelationGraph()
      .then((data) => {
        setGraphData(data.graph);
        setLoading(false);
      })
      .catch((err) => {
        setError(err.message || "加载图数据失败");
        setLoading(false);
      });
  }, []);

  // 进入编辑模式时加载边记录
  useEffect(() => {
    if (editMode && edgeRecords.length === 0) {
      listGraphEdges().then((res) => setEdgeRecords(res.edges)).catch(() => {});
    }
  }, [editMode]);

  // 构建并渲染图
  useEffect(() => {
    if (!graphData || !containerRef.current || loading) return;

    const allTables = Object.keys(graphData);
    const edgeSet = new Set<string>();
    const nodes: { id: string; label: string; group: string; title: string }[] = [];
    const edges: { id: string; from: string; to: string; label: string; arrows: string; title: string }[] = [];

    // 构建节点
    for (const table of allTables) {
      const domain = getDomain(table);
      nodes.push({
        id: table,
        label: table,
        group: domain,
        title: `<b>${table}</b><br/>域: ${DOMAIN_CONFIG[domain]?.label || "其他"}`,
      });
    }

    // 构建边（去重）
    for (const [fromTable, outEdges] of Object.entries(graphData)) {
      for (const edge of outEdges) {
        const toTable = edge.to;
        const key = [fromTable, toTable].sort().join("|||");
        if (edgeSet.has(key)) continue;
        edgeSet.add(key);

        const isBidirectional = (graphData[toTable] || []).some((e: GraphEdge) => e.to === fromTable);
        const isReverse = edge.desc.includes("反向");

        edges.push({
          id: key,
          from: fromTable,
          to: toTable,
          label: "",
          arrows: isBidirectional ? "to, from" : "to",
          title: `<b>${edge.desc}</b><br/>${edge.join}<br/>置信度: ${edge.confidence}${edge.note ? `<br/>⚠️ ${edge.note}` : ""}`,
        });
      }
    }

    const nodesDS = new DataSet(nodes);
    const edgesDS = new DataSet(edges);

    const nodeFontColor = isDark ? "#e8edf2" : "#111822";
    const edgeColor = isDark ? "rgba(255,255,255,0.08)" : "rgba(0,0,0,0.10)";
    const edgeFontColor = isDark ? "#556677" : "#8899aa";

    const network = new Network(containerRef.current, { nodes: nodesDS, edges: edgesDS }, {
      nodes: {
        shape: "dot",
        size: 14,
        font: {
          size: 10,
          face: "'JetBrains Mono', monospace",
          color: nodeFontColor,
          strokeWidth: 0,
        },
        borderWidth: 2,
        shadow: {
          enabled: true,
          size: 6,
        },
      },
      edges: {
        width: 1,
        color: { color: edgeColor, highlight: "#00c2ff" },
        font: {
          size: 8,
          face: "'JetBrains Mono', monospace",
          color: "#000",
          strokeWidth: 2,
          strokeColor: "#fff",
          align: "middle",
        },
        smooth: {
          enabled: true,
          type: "continuous",
          roundness: 0.5,
        },
        arrows: {
          to: { scaleFactor: 0.6 },
          from: { scaleFactor: 0.6 },
        },
        labelHighlightBold: true,
      },
      physics: {
        enabled: true,
        solver: "forceAtlas2Based",
        forceAtlas2Based: {
          gravitationalConstant: -50,
          centralGravity: 0.005,
          springLength: 180,
          springConstant: 0.04,
          damping: 0.6,
          avoidOverlap: 0.8,
        },
        stabilization: {
          enabled: true,
          iterations: 200,
          updateInterval: 25,
        },
      },
      layout: {
        improvedLayout: true,
      },
      interaction: {
        hover: true,
        tooltipDelay: 300,
        zoomView: true,
        dragView: true,
        navigationButtons: false,
        keyboard: {
          enabled: true,
          bindToWindow: false,
        },
      },
      groups: Object.fromEntries(
        Object.entries(DOMAIN_CONFIG).map(([key, cfg]) => [
          key,
          {
            color: {
              background: cfg.color,
              border: cfg.borderColor,
              highlight: { background: cfg.color, border: cfg.borderColor },
              hover: { background: cfg.color, border: cfg.borderColor },
            },
          },
        ])
      ),
    });

    networkRef.current = network;

    // 鼠标悬停边时显示 label，移出时隐藏
    network.on("hoverEdge", (params) => {
      const edgeId = params.edge;
      if (!edgeId) return;
      const edgeData = edgesDS.get(edgeId) as any;
      if (!edgeData) return;
      
      const { from, to } = edgeData;
      const rawEdge = (graphData[from] || []).find((e: GraphEdge) => e.to === to)
        || (graphData[to] || []).find((e: GraphEdge) => e.to === from);
      
      if (rawEdge?.join) {
        edgesDS.update({ id: edgeId, label: rawEdge.join });
      }
    });

    network.on("blurEdge", (params) => {
      const edgeId = params.edge;
      if (!edgeId) return;
      edgesDS.update({ id: edgeId, label: "" });
    });

    // 点击边显示详情
    network.on("selectEdge", (params) => {
      const edgeId = params.edges[0];
      if (!edgeId) return;
      const edgeData = edgesDS.get(edgeId) as any;
      if (!edgeData) return;

      const [from, to] = [edgeData.from, edgeData.to];
      const rawEdge = (graphData[from] || []).find((e: GraphEdge) => e.to === to)
        || (graphData[to] || []).find((e: GraphEdge) => e.to === from);

      // 尝试匹配 PG 中的边记录
      const record = edgeRecords.find(
        (r) => (r.from_table === from && r.to_table === to) || (r.from_table === to && r.to_table === from)
      );

      setSelectedEdge({
        from: edgeData.from,
        to: edgeData.to,
        label: rawEdge?.join || "",
        joinOn: rawEdge?.join || "",
        desc: rawEdge?.desc || "",
        confidence: rawEdge?.confidence || "",
        note: rawEdge?.note || "",
        joinType: rawEdge?.join_type || "",
        fromField: rawEdge?.from_field || "",
        toField: rawEdge?.to_field || "",
        edgeId: record?.id,
      });
    });

    network.on("deselectEdge", () => {
      setSelectedEdge(null);
    });

    return () => {
      network.destroy();
      networkRef.current = null;
    };
  }, [graphData, loading, edgeRecords, isDark]);

  // 搜索节点
  const handleSearch = useCallback(() => {
    if (!networkRef.current || !searchTerm.trim()) return;
    networkRef.current.selectNodes([searchTerm.trim()], true);
    networkRef.current.focus(searchTerm.trim(), { scale: 1.5, animation: true });
  }, [searchTerm]);

  // 缩放
  const zoomIn = () => networkRef.current?.moveTo({ scale: (networkRef.current as any).getScale() * 1.3 });
  const zoomOut = () => networkRef.current?.moveTo({ scale: (networkRef.current as any).getScale() * 0.7 });
  const fitAll = () => networkRef.current?.fit({ animation: true });

  // 域过滤
  const toggleDomain = (domain: string) => {
    const next = new Set(domainFilter);
    if (next.has(domain)) {
      next.delete(domain);
    } else {
      next.add(domain);
    }
    setDomainFilter(next);
  };

  useEffect(() => {
    if (!networkRef.current || !graphData) return;
    const nodesDS = (networkRef.current as any).body.data.nodes;

    if (domainFilter.size === 0) {
      nodesDS.forEach((node: { id: string }) => {
        nodesDS.update({ id: node.id, hidden: false });
      });
      const edgesDS = (networkRef.current as any).body.data.edges;
      edgesDS.forEach((edge: { id: string }) => {
        edgesDS.update({ id: edge.id, hidden: false });
      });
    } else {
      const visibleNodes = new Set<string>();
      nodesDS.forEach((node: { id: string; group: string }) => {
        const visible = domainFilter.has(node.group);
        nodesDS.update({ id: node.id, hidden: !visible });
        if (visible) visibleNodes.add(node.id);
      });
      const edgesDS = (networkRef.current as any).body.data.edges;
      edgesDS.forEach((edge: { id: string; from: string; to: string }) => {
        edgesDS.update({ id: edge.id, hidden: !visibleNodes.has(edge.from) || !visibleNodes.has(edge.to) });
      });
    }
  }, [domainFilter, graphData]);

  // ── 编辑模式操作 ────────────────────────────────────────────────

  const openAddEditor = () => {
    setEditingEdge(null);
    setForm({
      from_table: "",
      to_table: "",
      from_field: "",
      to_field: "",
      join_condition: "",
      join_type: "JOIN",
      description: "",
      confidence: "high",
      note: "",
    });
    setShowEditor(true);
  };

  const openEditEditor = (record: GraphEdgeRecord) => {
    setEditingEdge(record);
    setForm({
      from_table: record.from_table,
      to_table: record.to_table,
      from_field: record.from_field,
      to_field: record.to_field,
      join_condition: record.join_condition,
      join_type: record.join_type,
      description: record.description,
      confidence: record.confidence,
      note: record.note,
    });
    setShowEditor(true);
  };

  const handleSave = async () => {
    setSaving(true);
    setSaveMsg("");
    try {
      if (editingEdge) {
        await updateGraphEdge(editingEdge.id, form);
      } else {
        await addGraphEdge(form);
      }
      // 刷新
      const [graphRes, edgesRes] = await Promise.all([fetchRelationGraph(), listGraphEdges()]);
      setGraphData(graphRes.graph);
      setEdgeRecords(edgesRes.edges);
      setShowEditor(false);
      setSaveMsg("保存成功");
      setTimeout(() => setSaveMsg(""), 3000);
    } catch (err: any) {
      setSaveMsg("保存失败: " + (err.message || "未知错误"));
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (edgeId: number) => {
    if (!confirm("确定删除这条关系边？")) return;
    try {
      await deleteGraphEdge(edgeId);
      const [graphRes, edgesRes] = await Promise.all([fetchRelationGraph(), listGraphEdges()]);
      setGraphData(graphRes.graph);
      setEdgeRecords(edgesRes.edges);
      setSelectedEdge(null);
      setSaveMsg("删除成功");
      setTimeout(() => setSaveMsg(""), 3000);
    } catch (err: any) {
      setSaveMsg("删除失败: " + (err.message || "未知错误"));
    }
  };

  const handleSync = async () => {
    if (!confirm("从 JSON 文件全量同步到 PG？这会覆盖 PG 中所有现有边。")) return;
    setSyncing(true);
    try {
      const res = await syncGraphFromJson();
      const [graphRes, edgesRes] = await Promise.all([fetchRelationGraph(), listGraphEdges()]);
      setGraphData(graphRes.graph);
      setEdgeRecords(edgesRes.edges);
      setSaveMsg(`同步完成: ${res.count} 条边, 版本 ${res.version}`);
      setTimeout(() => setSaveMsg(""), 5000);
    } catch (err: any) {
      setSaveMsg("同步失败: " + (err.message || "未知错误"));
    } finally {
      setSyncing(false);
    }
  };

  const closeEditor = () => setShowEditor(false);

  if (loading) {
    return (
      <div className="flex h-screen items-center justify-center bg-[var(--bg-base)]">
        <div className="flex flex-col items-center gap-3 text-[var(--text-secondary)]">
          <Loader2 className="h-8 w-8 animate-spin text-[var(--accent)]" />
          <span className="font-mono text-xs uppercase tracking-[0.06em]">正在加载关系图...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-screen items-center justify-center bg-[var(--bg-base)]">
        <div className="flex flex-col items-center gap-3">
          <span className="font-mono text-xs text-[var(--error)]">加载失败: {error}</span>
          <Link to="/" className="font-mono text-[11px] uppercase tracking-[0.04em] text-[var(--accent)] transition-colors hover:underline">
            返回首页
          </Link>
        </div>
      </div>
    );
  }

  const nodeCount = graphData ? Object.keys(graphData).length : 0;
  const edgeCount = graphData
    ? new Set(
        Object.entries(graphData).flatMap(([from, edges]) =>
          edges.map((e) => [from, e.to].sort().join("|||"))
        )
      ).size
    : 0;

  return (
    <div className="relative flex h-screen flex-col bg-[var(--bg-base)]">
      {/* 主区域 */}
      <div className="flex flex-1 overflow-hidden">
        {/* 图区域 */}
        <div ref={containerRef} className="flex-1" />

        {/* 右侧面板 */}
        <div className="flex w-64 flex-col border-l border-[var(--border-default)] bg-[var(--bg-raised)]">
          <div className="flex-1 overflow-auto px-3 py-3">
            {/* ── 头部工具栏（合并自原 header） ── */}
            <div className="mb-2.5 flex items-center gap-1.5">
              <Link
                to="/"
                className="flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.04em] text-[var(--text-tertiary)] transition-colors hover:text-[var(--accent)]"
              >
                <ArrowLeft className="h-3.5 w-3.5" />
                返回
              </Link>
              <div className="h-3 w-px bg-[var(--border-default)]" />
              <h1 className="font-display text-sm font-semibold uppercase tracking-[0.06em] text-[var(--text-primary)]">
                MES 表关系图
              </h1>
              <span className="font-mono text-[10px] text-[var(--text-tertiary)] tabular-nums">
                {nodeCount} 表 <span className="opacity-40">|</span> {edgeCount} 关系
              </span>
            </div>

            {/* 工具按钮：主题切换、编辑模式、缩放 */}
            <div className="mb-2.5 flex flex-wrap items-center gap-1">
              {/* 主题切换 */}
              <button
                type="button"
                onClick={toggleTheme}
                title={isDark ? "切换到亮色模式" : "切换到暗色模式"}
                className="flex h-7 items-center gap-1 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-1.5 font-mono text-[10px] uppercase text-[var(--text-secondary)] transition-all hover:border-[var(--border-accent)] hover:text-[var(--accent)]"
              >
                {isDark ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
              </button>

              {/* 编辑模式开关 */}
              <button
                onClick={() => setEditMode(!editMode)}
                className="flex h-7 items-center gap-1 rounded-[var(--radius-sm)] border px-1.5 font-mono text-[10px] uppercase transition-all"
                style={{
                  borderColor: editMode ? "var(--accent)" : "var(--border-default)",
                  backgroundColor: editMode ? "var(--accent-surface)" : "var(--bg-subtle)",
                  color: editMode ? "var(--accent)" : "var(--text-secondary)",
                }}
              >
                <Edit3 className="h-3.5 w-3.5" />
                编辑
              </button>

              {editMode && (
                <>
                  <button
                    onClick={openAddEditor}
                    className="flex h-7 items-center gap-1 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-1.5 font-mono text-[10px] uppercase text-[var(--text-secondary)] transition-all hover:text-[var(--text-primary)]"
                  >
                    <Plus className="h-3.5 w-3.5" />
                    新增边
                  </button>
                  <button
                    onClick={handleSync}
                    disabled={syncing}
                    className="flex h-7 items-center gap-1 rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-1.5 font-mono text-[10px] uppercase text-[var(--text-secondary)] transition-all hover:text-[var(--text-primary)] disabled:opacity-30"
                  >
                    <RefreshCw className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
                    同步
                  </button>
                </>
              )}

              {/* 缩放 */}
              <div className="ml-auto flex items-center gap-1">
                <button
                  onClick={zoomIn}
                  className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] text-[var(--text-secondary)] transition-all hover:text-[var(--accent)]"
                  title="放大"
                >
                  <ZoomIn className="h-3.5 w-3.5" />
                </button>
                <button
                  onClick={zoomOut}
                  className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] text-[var(--text-secondary)] transition-all hover:text-[var(--accent)]"
                  title="缩小"
                >
                  <ZoomOut className="h-3.5 w-3.5" />
                </button>
                <button
                  onClick={fitAll}
                  className="flex h-7 items-center justify-center rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-1.5 font-mono text-[10px] uppercase text-[var(--text-secondary)] transition-all hover:text-[var(--accent)]"
                  title="适应视图"
                >
                  适应
                </button>
              </div>
            </div>

            {/* 搜索 */}
            <div className="mb-2.5 flex items-center gap-1">
              <input
                type="text"
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && handleSearch()}
                placeholder="搜索表名..."
                className="w-full rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-overlay)] px-2 font-mono text-[11px] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent)] focus:outline-none"
                style={{ height: "28px" }}
              />
              <button
                onClick={handleSearch}
                className="flex h-7 w-7 items-center justify-center rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] text-[var(--text-secondary)] transition-all hover:text-[var(--accent)]"
                style={{ height: "28px", width: "28px" }}
              >
                <Search className="h-3.5 w-3.5" />
              </button>
            </div>

            {saveMsg && (
              <div
                className="mb-2.5 font-mono text-[10px]"
                style={{ color: saveMsg.includes("失败") ? "var(--error)" : "var(--success)" }}
              >
                {saveMsg}
              </div>
            )}

            {/* 域过滤 */}
            <div className="mb-2.5 flex items-center gap-1.5">
              <Filter className="h-3.5 w-3.5 text-[var(--text-tertiary)]" />
              <span className="font-mono text-[10px] font-medium uppercase tracking-[0.06em] text-[var(--text-secondary)]">
                域过滤
              </span>
            </div>
            <div className="mb-2.5 flex flex-wrap gap-1.5">
              {Object.entries(DOMAIN_CONFIG).map(([key, cfg]) => (
                <button
                  key={key}
                  onClick={() => toggleDomain(key)}
                  className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 font-mono text-[10px] transition-all"
                  style={{
                    backgroundColor:
                      domainFilter.size === 0 || domainFilter.has(key)
                        ? cfg.color + "30"
                        : "transparent",
                    border: `1px solid ${domainFilter.size === 0 || domainFilter.has(key) ? cfg.color : "var(--border-default)"}`,
                    color: domainFilter.size === 0 || domainFilter.has(key) ? "#fff" : "var(--text-tertiary)",
                    opacity: domainFilter.size === 0 || domainFilter.has(key) ? 1 : 0.3,
                  }}
                >
                  <span className="h-2 w-2 rounded-full" style={{ backgroundColor: cfg.color }} />
                  {cfg.label}
                </button>
              ))}
            </div>

            {/* 分隔线：工具栏与详情区分隔 */}
            <div className="mb-2.5 border-b border-[var(--border-default)]" />

            {/* ── 边详情 / 编辑模式下列表 ── */}
            {editMode ? (
              <>
                <span className="font-mono text-[10px] font-medium uppercase tracking-[0.04em] text-[var(--text-secondary)]">
                  PG 边列表 ({edgeRecords.length})
                </span>
                <div className="mt-2 space-y-1">
                  {edgeRecords.map((r) => (
                    <div
                      key={r.id}
                      className="group cursor-pointer rounded-[var(--radius-sm)] bg-[var(--bg-overlay)] px-2.5 py-2 transition-colors hover:bg-[var(--accent-surface)]"
                      onClick={() => openEditEditor(r)}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-[11px] text-[var(--accent)]">{r.from_table}</span>
                        <span className="font-mono text-[10px] text-[var(--text-tertiary)]">→</span>
                        <span className="font-mono text-[11px] text-[var(--accent)]">{r.to_table}</span>
                      </div>
                      <p className="mt-1 truncate font-mono text-[10px] text-[var(--text-tertiary)]">{r.description}</p>
                      <div className="mt-1 flex items-center gap-2">
                        <span
                          className="rounded px-1 font-mono text-[10px] uppercase"
                          style={{
                            backgroundColor:
                              r.confidence === "high"
                                ? "color-mix(in srgb, var(--success) 20%, transparent)"
                                : r.confidence === "medium"
                                  ? "color-mix(in srgb, var(--warning) 20%, transparent)"
                                  : "color-mix(in srgb, var(--error) 20%, transparent)",
                            color:
                              r.confidence === "high"
                                ? "var(--success)"
                                : r.confidence === "medium"
                                  ? "var(--warning)"
                                  : "var(--error)",
                          }}
                        >
                          {r.confidence}
                        </span>
                        <button
                          onClick={(e) => {
                            e.stopPropagation();
                            handleDelete(r.id);
                          }}
                          className="ml-auto text-[var(--text-tertiary)] opacity-0 transition-all hover:text-[var(--error)] group-hover:opacity-100"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                    </div>
                  ))}
                  {edgeRecords.length === 0 && (
                    <p className="font-mono text-[10px] text-[var(--text-tertiary)]">
                      PG 中暂无数据，请点击「同步」从 JSON 导入
                    </p>
                  )}
                </div>
              </>
            ) : (
              <>
                <span className="font-mono text-[10px] font-medium uppercase tracking-[0.04em] text-[var(--text-secondary)]">
                  关系详情
                </span>
                {selectedEdge ? (
                  <div className="mt-2 space-y-2">
                    <div className="rounded-[var(--radius-sm)] bg-[var(--bg-overlay)] px-2.5 py-2">
                      <span className="font-mono text-[10px] uppercase text-[var(--text-tertiary)]">描述</span>
                      <p className="mt-0.5 text-[11px] text-[var(--text-primary)]">{selectedEdge.desc}</p>
                    </div>
                    <div className="rounded-[var(--radius-sm)] bg-[var(--bg-overlay)] px-2.5 py-2">
                      <span className="font-mono text-[10px] uppercase text-[var(--text-tertiary)]">关联表</span>
                      <p className="mt-0.5 text-[11px] text-[var(--text-primary)]">
                        <span className="text-[var(--accent)]">{selectedEdge.from}</span>
                        {" → "}
                        <span className="text-[var(--accent)]">{selectedEdge.to}</span>
                      </p>
                    </div>
                    <div className="rounded-[var(--radius-sm)] bg-[var(--bg-overlay)] px-2.5 py-2">
                      <span className="font-mono text-[10px] uppercase text-[var(--text-tertiary)]">JOIN 条件</span>
                      <p className="mt-0.5 break-all font-mono text-[11px] text-[var(--text-primary)]">
                        {selectedEdge.joinOn}
                      </p>
                    </div>
                    <div className="rounded-[var(--radius-sm)] bg-[var(--bg-overlay)] px-2.5 py-2">
                      <span className="font-mono text-[10px] uppercase text-[var(--text-tertiary)]">置信度</span>
                      <p className="mt-0.5">
                        <span
                          className="inline-block rounded px-1.5 py-0.5 font-mono text-[10px] uppercase"
                          style={{
                            backgroundColor:
                              selectedEdge.confidence === "high"
                                ? "color-mix(in srgb, var(--success) 20%, transparent)"
                                : selectedEdge.confidence === "medium"
                                  ? "color-mix(in srgb, var(--warning) 20%, transparent)"
                                  : "color-mix(in srgb, var(--error) 20%, transparent)",
                            color:
                              selectedEdge.confidence === "high"
                                ? "var(--success)"
                                : selectedEdge.confidence === "medium"
                                  ? "var(--warning)"
                                  : "var(--error)",
                          }}
                        >
                          {selectedEdge.confidence}
                        </span>
                      </p>
                    </div>
                    {selectedEdge.note && (
                      <div
                        className="rounded-[var(--radius-sm)] px-2.5 py-2"
                        style={{
                          backgroundColor: "color-mix(in srgb, var(--warning) 10%, transparent)",
                          border: "1px solid color-mix(in srgb, var(--warning) 20%, transparent)",
                        }}
                      >
                        <span className="font-mono text-[10px] uppercase" style={{ color: "var(--warning)" }}>
                          备注
                        </span>
                        <p className="mt-0.5 text-[11px]" style={{ color: "var(--warning)" }}>
                          {selectedEdge.note}
                        </p>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="mt-2 font-mono text-[10px] text-[var(--text-tertiary)]">
                    点击图中的连线查看关系详情
                  </p>
                )}
              </>
            )}
          </div>
        </div>
      </div>

      {/* 编辑弹窗 */}
      {showEditor && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-sm">
          <div className="w-full max-w-md rounded-[var(--radius-lg)] border border-[var(--border-strong)] bg-[var(--bg-raised)] shadow-[var(--shadow-md)]">
            <div className="flex items-center justify-between border-b border-[var(--border-default)] px-4 py-3">
              <h2 className="font-mono text-xs font-medium uppercase tracking-[0.04em] text-[var(--text-primary)]">
                {editingEdge ? "编辑关系边" : "新增关系边"}
              </h2>
              <button onClick={closeEditor} className="text-[var(--text-tertiary)] transition-colors hover:text-[var(--text-primary)]">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="max-h-[60vh] space-y-3 overflow-auto px-4 py-3">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="font-mono text-[10px] uppercase text-[var(--text-tertiary)]">源表名</label>
                  <input
                    value={form.from_table}
                    onChange={(e) => setForm({ ...form, from_table: e.target.value })}
                    className="mt-0.5 w-full rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-base)] px-2 font-mono text-[11px] text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                    style={{ height: "28px" }}
                    placeholder="t_pd_wo"
                  />
                </div>
                <div>
                  <label className="font-mono text-[10px] uppercase text-[var(--text-tertiary)]">目标表名</label>
                  <input
                    value={form.to_table}
                    onChange={(e) => setForm({ ...form, to_table: e.target.value })}
                    className="mt-0.5 w-full rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-base)] px-2 font-mono text-[11px] text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                    style={{ height: "28px" }}
                    placeholder="t_bd_pdline"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="font-mono text-[10px] uppercase text-[var(--text-tertiary)]">源字段</label>
                  <input
                    value={form.from_field}
                    onChange={(e) => setForm({ ...form, from_field: e.target.value })}
                    className="mt-0.5 w-full rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-base)] px-2 font-mono text-[11px] text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                    style={{ height: "28px" }}
                    placeholder="pdline_id"
                  />
                </div>
                <div>
                  <label className="font-mono text-[10px] uppercase text-[var(--text-tertiary)]">目标字段</label>
                  <input
                    value={form.to_field}
                    onChange={(e) => setForm({ ...form, to_field: e.target.value })}
                    className="mt-0.5 w-full rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-base)] px-2 font-mono text-[11px] text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                    style={{ height: "28px" }}
                    placeholder="id"
                  />
                </div>
              </div>
              <div>
                <label className="font-mono text-[10px] uppercase text-[var(--text-tertiary)]">JOIN 条件</label>
                <input
                  value={form.join_condition}
                  onChange={(e) => setForm({ ...form, join_condition: e.target.value })}
                  className="mt-0.5 w-full rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-base)] px-2 font-mono text-[11px] text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                  style={{ height: "28px" }}
                  placeholder="t_pd_wo.pdline_id = t_bd_pdline.id"
                />
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="font-mono text-[10px] uppercase text-[var(--text-tertiary)]">JOIN 类型</label>
                  <select
                    value={form.join_type}
                    onChange={(e) => setForm({ ...form, join_type: e.target.value })}
                    className="mt-0.5 w-full rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-base)] px-2 font-mono text-[11px] text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                    style={{ height: "28px" }}
                  >
                    <option value="JOIN">JOIN</option>
                    <option value="LEFT JOIN">LEFT JOIN</option>
                    <option value="RIGHT JOIN">RIGHT JOIN</option>
                    <option value="INNER JOIN">INNER JOIN</option>
                  </select>
                </div>
                <div>
                  <label className="font-mono text-[10px] uppercase text-[var(--text-tertiary)]">置信度</label>
                  <select
                    value={form.confidence}
                    onChange={(e) => setForm({ ...form, confidence: e.target.value })}
                    className="mt-0.5 w-full rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-base)] px-2 font-mono text-[11px] text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                    style={{ height: "28px" }}
                  >
                    <option value="high">high</option>
                    <option value="medium">medium</option>
                    <option value="low">low</option>
                  </select>
                </div>
                <div>
                  <label className="font-mono text-[10px] uppercase text-[var(--text-tertiary)]">描述</label>
                  <input
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                    className="mt-0.5 w-full rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-base)] px-2 font-mono text-[11px] text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                    style={{ height: "28px" }}
                    placeholder="关系描述"
                  />
                </div>
              </div>
              <div>
                <label className="font-mono text-[10px] uppercase text-[var(--text-tertiary)]">备注</label>
                <input
                  value={form.note}
                  onChange={(e) => setForm({ ...form, note: e.target.value })}
                  className="mt-0.5 w-full rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-base)] px-2 font-mono text-[11px] text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                  style={{ height: "28px" }}
                  placeholder="可选备注"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-[var(--border-default)] px-4 py-3">
              <button
                onClick={closeEditor}
                className="rounded-[var(--radius-sm)] border border-[var(--border-default)] bg-[var(--bg-subtle)] px-3 font-mono text-[10px] uppercase text-[var(--text-secondary)] transition-all hover:text-[var(--text-primary)]"
                style={{ height: "28px" }}
              >
                取消
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex items-center gap-1.5 rounded-[var(--radius-sm)] bg-[var(--accent)] px-3 font-mono text-[10px] font-medium uppercase text-black transition-all hover:shadow-[var(--shadow-glow)] disabled:opacity-40"
                style={{ height: "28px" }}
              >
                <Save className="h-3.5 w-3.5" />
                {saving ? "保存中..." : "保存"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
