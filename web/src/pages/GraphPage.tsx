import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Network } from "vis-network";
import { DataSet } from "vis-data";
import { ArrowLeft, Edit3, Filter, Loader2, Plus, RefreshCw, Save, Search, Trash2, X, ZoomIn, ZoomOut } from "lucide-react";

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
          label: isReverse ? "" : edge.join,
          arrows: isBidirectional ? "to, from" : "to",
          title: `<b>${edge.desc}</b><br/>${edge.join}<br/>置信度: ${edge.confidence}${edge.note ? `<br/>⚠️ ${edge.note}` : ""}`,
        });
      }
    }

    const nodesDS = new DataSet(nodes);
    const edgesDS = new DataSet(edges);

    const network = new Network(containerRef.current, { nodes: nodesDS, edges: edgesDS }, {
      nodes: {
        shape: "dot",
        size: 14,
        font: {
          size: 11,
          face: "Geist, system-ui, sans-serif",
          color: "#e4e4e7",
          strokeWidth: 0,
        },
        borderWidth: 2,
        shadow: {
          enabled: true,
          size: 6,
        },
      },
      edges: {
        width: 1.2,
        color: { color: "rgba(255,255,255,0.12)", highlight: "#60a5fa" },
        font: {
          size: 9,
          face: "Geist, system-ui, sans-serif",
          color: "#71717a",
          strokeWidth: 0,
          align: "top",
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

    // 点击边显示详情
    network.on("selectEdge", (params) => {
      const edgeId = params.edges[0];
      if (!edgeId) return;
      const edgeData = edgesDS.get(edgeId) as unknown as { from: string; to: string; label: string; title: string } | null;
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
        label: edgeData.label,
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
  }, [graphData, loading, edgeRecords]);

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
      <div className="flex h-screen items-center justify-center bg-surface-base">
        <div className="flex flex-col items-center gap-3 text-text-secondary">
          <Loader2 className="h-8 w-8 animate-spin" />
          <span className="text-sm">正在加载关系图...</span>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-screen items-center justify-center bg-surface-base">
        <div className="flex flex-col items-center gap-3 text-red-400">
          <span className="text-sm">加载失败: {error}</span>
          <Link to="/" className="text-accent-400 text-sm hover:underline">返回首页</Link>
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
    <div className="relative flex h-screen flex-col bg-surface-base">
      {/* 顶部工具栏 */}
      <header className="flex items-center justify-between border-b border-border-subtle bg-surface-raised px-4 py-2.5">
        <div className="flex items-center gap-3">
          <Link to="/" className="flex items-center gap-1.5 text-text-secondary hover:text-text-primary transition-colors">
            <ArrowLeft className="h-4 w-4" />
            <span className="text-sm">返回</span>
          </Link>
          <div className="h-4 w-px bg-border-subtle" />
          <h1 className="text-sm font-semibold text-text-primary">MES 表关系图</h1>
          <span className="text-2xs text-text-tertiary">
            {nodeCount} 表 · {edgeCount} 关系
          </span>
          {saveMsg && (
            <span className={`text-2xs ${saveMsg.includes("失败") ? "text-red-400" : "text-green-400"}`}>
              {saveMsg}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* 编辑模式开关 */}
          <button
            onClick={() => setEditMode(!editMode)}
            className={`flex h-7 items-center gap-1 rounded-md border px-2 text-xs transition-colors ${
              editMode
                ? "border-accent-500 bg-accent-500/10 text-accent-400"
                : "border-border-muted bg-surface-overlay text-text-secondary hover:text-text-primary"
            }`}
          >
            <Edit3 className="h-3.5 w-3.5" />
            编辑
          </button>

          {editMode && (
            <>
              <button
                onClick={openAddEditor}
                className="flex h-7 items-center gap-1 rounded-md border border-border-muted bg-surface-overlay px-2 text-xs text-text-secondary hover:text-text-primary"
              >
                <Plus className="h-3.5 w-3.5" />
                新增边
              </button>
              <button
                onClick={handleSync}
                disabled={syncing}
                className="flex h-7 items-center gap-1 rounded-md border border-border-muted bg-surface-overlay px-2 text-xs text-text-secondary hover:text-text-primary"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${syncing ? "animate-spin" : ""}`} />
                同步
              </button>
              <div className="h-4 w-px bg-border-subtle" />
            </>
          )}

          {/* 搜索 */}
          <div className="flex items-center gap-1">
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder="搜索表名..."
              className="h-7 w-44 rounded-md border border-border-muted bg-surface-overlay px-2 text-xs text-text-primary placeholder:text-text-tertiary focus:border-accent-500 focus:outline-none"
            />
            <button
              onClick={handleSearch}
              className="flex h-7 w-7 items-center justify-center rounded-md border border-border-muted bg-surface-overlay text-text-secondary hover:text-text-primary"
            >
              <Search className="h-3.5 w-3.5" />
            </button>
          </div>

          <div className="h-4 w-px bg-border-subtle" />

          {/* 缩放 */}
          <button onClick={zoomIn} className="flex h-7 w-7 items-center justify-center rounded-md border border-border-muted bg-surface-overlay text-text-secondary hover:text-text-primary" title="放大">
            <ZoomIn className="h-3.5 w-3.5" />
          </button>
          <button onClick={zoomOut} className="flex h-7 w-7 items-center justify-center rounded-md border border-border-muted bg-surface-overlay text-text-secondary hover:text-text-primary" title="缩小">
            <ZoomOut className="h-3.5 w-3.5" />
          </button>
          <button onClick={fitAll} className="flex h-7 items-center rounded-md border border-border-muted bg-surface-overlay px-2 text-xs text-text-secondary hover:text-text-primary" title="适应视图">
            适应
          </button>
        </div>
      </header>

      {/* 主区域 */}
      <div className="flex flex-1 overflow-hidden">
        {/* 图区域 */}
        <div ref={containerRef} className="flex-1" />

        {/* 右侧面板 */}
        <div className="flex w-64 flex-col border-l border-border-subtle bg-surface-raised">
          {/* 域过滤 */}
          <div className="border-b border-border-subtle px-3 py-3">
            <div className="flex items-center gap-1.5 mb-2.5">
              <Filter className="h-3.5 w-3.5 text-text-tertiary" />
              <span className="text-xs font-medium text-text-secondary">域过滤</span>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {Object.entries(DOMAIN_CONFIG).map(([key, cfg]) => (
                <button
                  key={key}
                  onClick={() => toggleDomain(key)}
                  className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs transition-colors ${
                    domainFilter.size === 0 || domainFilter.has(key)
                      ? "text-white"
                      : "opacity-30 text-text-tertiary"
                  }`}
                  style={{
                    backgroundColor: domainFilter.size === 0 || domainFilter.has(key)
                      ? cfg.color + "30"
                      : "transparent",
                    border: `1px solid ${domainFilter.size === 0 || domainFilter.has(key) ? cfg.color : "rgba(255,255,255,0.1)"}`,
                  }}
                >
                  <span
                    className="h-2 w-2 rounded-full"
                    style={{ backgroundColor: cfg.color }}
                  />
                  {cfg.label}
                </button>
              ))}
            </div>
          </div>

          {/* 边详情 / 编辑模式下列表 */}
          <div className="flex-1 overflow-auto px-3 py-3">
            {editMode ? (
              <>
                <span className="text-xs font-medium text-text-secondary">
                  PG 边列表 ({edgeRecords.length})
                </span>
                <div className="mt-2 space-y-1.5">
                  {edgeRecords.map((r) => (
                    <div
                      key={r.id}
                      className="group rounded-md bg-surface-overlay px-2.5 py-2 hover:bg-surface-overlay/80 cursor-pointer"
                      onClick={() => openEditEditor(r)}
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-accent-400">{r.from_table}</span>
                        <span className="text-2xs text-text-tertiary">→</span>
                        <span className="text-xs text-accent-400">{r.to_table}</span>
                      </div>
                      <p className="text-2xs text-text-tertiary mt-1 truncate">{r.description}</p>
                      <div className="flex items-center gap-2 mt-1">
                        <span className={`text-2xs px-1 rounded ${
                          r.confidence === "high" ? "bg-green-500/20 text-green-400" :
                          r.confidence === "medium" ? "bg-yellow-500/20 text-yellow-400" :
                          "bg-red-500/20 text-red-400"
                        }`}>
                          {r.confidence}
                        </span>
                        <button
                          onClick={(e) => { e.stopPropagation(); handleDelete(r.id); }}
                          className="ml-auto text-text-tertiary hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
                        >
                          <Trash2 className="h-3 w-3" />
                        </button>
                      </div>
                    </div>
                  ))}
                  {edgeRecords.length === 0 && (
                    <p className="text-2xs text-text-tertiary">
                      PG 中暂无数据，请点击「同步」从 JSON 导入
                    </p>
                  )}
                </div>
              </>
            ) : (
              <>
                <span className="text-xs font-medium text-text-secondary">关系详情</span>
                {selectedEdge ? (
                  <div className="mt-2 space-y-2">
                    <div className="rounded-md bg-surface-overlay px-2.5 py-2">
                      <span className="text-2xs text-text-tertiary">描述</span>
                      <p className="text-xs text-text-primary mt-0.5">{selectedEdge.desc}</p>
                    </div>
                    <div className="rounded-md bg-surface-overlay px-2.5 py-2">
                      <span className="text-2xs text-text-tertiary">关联表</span>
                      <p className="text-xs text-text-primary mt-0.5">
                        <span className="text-accent-400">{selectedEdge.from}</span>
                        {" → "}
                        <span className="text-accent-400">{selectedEdge.to}</span>
                      </p>
                    </div>
                    <div className="rounded-md bg-surface-overlay px-2.5 py-2">
                      <span className="text-2xs text-text-tertiary">JOIN 条件</span>
                      <p className="text-xs text-text-primary mt-0.5 font-mono break-all">{selectedEdge.joinOn}</p>
                    </div>
                    <div className="rounded-md bg-surface-overlay px-2.5 py-2">
                      <span className="text-2xs text-text-tertiary">置信度</span>
                      <p className="text-xs mt-0.5">
                        <span className={`inline-block rounded px-1.5 py-0.5 text-2xs font-medium ${
                          selectedEdge.confidence === "high" ? "bg-green-500/20 text-green-400" :
                          selectedEdge.confidence === "medium" ? "bg-yellow-500/20 text-yellow-400" :
                          "bg-red-500/20 text-red-400"
                        }`}>
                          {selectedEdge.confidence}
                        </span>
                      </p>
                    </div>
                    {selectedEdge.note && (
                      <div className="rounded-md bg-yellow-500/10 px-2.5 py-2 border border-yellow-500/20">
                        <span className="text-2xs text-yellow-400">备注</span>
                        <p className="text-xs text-yellow-300 mt-0.5">{selectedEdge.note}</p>
                      </div>
                    )}
                  </div>
                ) : (
                  <p className="mt-2 text-2xs text-text-tertiary">
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
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="w-full max-w-md rounded-lg bg-surface-raised border border-border-subtle shadow-xl">
            <div className="flex items-center justify-between border-b border-border-subtle px-4 py-3">
              <h2 className="text-sm font-semibold text-text-primary">
                {editingEdge ? "编辑关系边" : "新增关系边"}
              </h2>
              <button onClick={closeEditor} className="text-text-tertiary hover:text-text-primary">
                <X className="h-4 w-4" />
              </button>
            </div>

            <div className="px-4 py-3 space-y-3 max-h-[60vh] overflow-auto">
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-2xs text-text-tertiary">源表名</label>
                  <input
                    value={form.from_table}
                    onChange={(e) => setForm({ ...form, from_table: e.target.value })}
                    className="mt-0.5 w-full h-7 rounded border border-border-muted bg-surface-base px-2 text-xs text-text-primary focus:border-accent-500 focus:outline-none"
                    placeholder="t_pd_wo"
                  />
                </div>
                <div>
                  <label className="text-2xs text-text-tertiary">目标表名</label>
                  <input
                    value={form.to_table}
                    onChange={(e) => setForm({ ...form, to_table: e.target.value })}
                    className="mt-0.5 w-full h-7 rounded border border-border-muted bg-surface-base px-2 text-xs text-text-primary focus:border-accent-500 focus:outline-none"
                    placeholder="t_bd_pdline"
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className="text-2xs text-text-tertiary">源字段</label>
                  <input
                    value={form.from_field}
                    onChange={(e) => setForm({ ...form, from_field: e.target.value })}
                    className="mt-0.5 w-full h-7 rounded border border-border-muted bg-surface-base px-2 text-xs text-text-primary focus:border-accent-500 focus:outline-none"
                    placeholder="pdline_id"
                  />
                </div>
                <div>
                  <label className="text-2xs text-text-tertiary">目标字段</label>
                  <input
                    value={form.to_field}
                    onChange={(e) => setForm({ ...form, to_field: e.target.value })}
                    className="mt-0.5 w-full h-7 rounded border border-border-muted bg-surface-base px-2 text-xs text-text-primary focus:border-accent-500 focus:outline-none"
                    placeholder="id"
                  />
                </div>
              </div>
              <div>
                <label className="text-2xs text-text-tertiary">JOIN 条件</label>
                <input
                  value={form.join_condition}
                  onChange={(e) => setForm({ ...form, join_condition: e.target.value })}
                  className="mt-0.5 w-full h-7 rounded border border-border-muted bg-surface-base px-2 text-xs text-text-primary font-mono focus:border-accent-500 focus:outline-none"
                  placeholder="t_pd_wo.pdline_id = t_bd_pdline.id"
                />
              </div>
              <div className="grid grid-cols-3 gap-2">
                <div>
                  <label className="text-2xs text-text-tertiary">JOIN 类型</label>
                  <select
                    value={form.join_type}
                    onChange={(e) => setForm({ ...form, join_type: e.target.value })}
                    className="mt-0.5 w-full h-7 rounded border border-border-muted bg-surface-base px-2 text-xs text-text-primary focus:border-accent-500 focus:outline-none"
                  >
                    <option value="JOIN">JOIN</option>
                    <option value="LEFT JOIN">LEFT JOIN</option>
                    <option value="RIGHT JOIN">RIGHT JOIN</option>
                    <option value="INNER JOIN">INNER JOIN</option>
                  </select>
                </div>
                <div>
                  <label className="text-2xs text-text-tertiary">置信度</label>
                  <select
                    value={form.confidence}
                    onChange={(e) => setForm({ ...form, confidence: e.target.value })}
                    className="mt-0.5 w-full h-7 rounded border border-border-muted bg-surface-base px-2 text-xs text-text-primary focus:border-accent-500 focus:outline-none"
                  >
                    <option value="high">high</option>
                    <option value="medium">medium</option>
                    <option value="low">low</option>
                  </select>
                </div>
                <div>
                  <label className="text-2xs text-text-tertiary">描述</label>
                  <input
                    value={form.description}
                    onChange={(e) => setForm({ ...form, description: e.target.value })}
                    className="mt-0.5 w-full h-7 rounded border border-border-muted bg-surface-base px-2 text-xs text-text-primary focus:border-accent-500 focus:outline-none"
                    placeholder="关系描述"
                  />
                </div>
              </div>
              <div>
                <label className="text-2xs text-text-tertiary">备注</label>
                <input
                  value={form.note}
                  onChange={(e) => setForm({ ...form, note: e.target.value })}
                  className="mt-0.5 w-full h-7 rounded border border-border-muted bg-surface-base px-2 text-xs text-text-primary focus:border-accent-500 focus:outline-none"
                  placeholder="可选备注"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-2 border-t border-border-subtle px-4 py-3">
              <button
                onClick={closeEditor}
                className="h-7 rounded-md border border-border-muted bg-surface-overlay px-3 text-xs text-text-secondary hover:text-text-primary"
              >
                取消
              </button>
              <button
                onClick={handleSave}
                disabled={saving}
                className="flex h-7 items-center gap-1.5 rounded-md bg-accent-500 px-3 text-xs text-white hover:bg-accent-600 disabled:opacity-50"
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