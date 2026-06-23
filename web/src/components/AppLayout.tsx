import {
  BookOpen,
  Database,
  GitBranch,
  Layers,
  Loader2,
  LogOut,
  Moon,
  Network,
  Plus,
  Save,
  ScrollText,
  Search,
  ShieldCheck,
  Sun,
  Trash2,
  Users,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";
import { createGenericKB, deleteGenericKB, downloadSyncedFiles, listGenericKBs, syncKnowledgeFromNeo4j } from "@/lib/api";
import type { GenericKBSummary } from "@/types";
import { cn } from "@/lib/utils";

interface NavItem {
  to: string;
  label: string;
  icon: ReactNode;
  adminOnly?: boolean;
}

interface NavGroup {
  title: string;
  items: NavItem[];
}

const STATIC_NAV_GROUPS: NavGroup[] = [
  {
    title: "监控",
    items: [
      { to: "/graph", label: "表关系图", icon: <Network className="h-4 w-4" /> },
      { to: "/trace", label: "追踪追踪", icon: <ScrollText className="h-4 w-4" /> },
    ],
  },
  {
    title: "知识库",
    items: [
      { to: "/knowledge", label: "表知识库", icon: <Database className="h-4 w-4" /> },
      { to: "/few-shot", label: "FewShot", icon: <Layers className="h-4 w-4" /> },
      { to: "/rule", label: "运行时规则", icon: <GitBranch className="h-4 w-4" /> },
      { to: "/knowledge-search", label: "检索查询", icon: <Search className="h-4 w-4" /> },
    ],
  },
  {
    title: "管理",
    items: [
      { to: "/users", label: "用户管理", icon: <Users className="h-4 w-4" />, adminOnly: true },
      { to: "/harness", label: "数据飞轮", icon: <ShieldCheck className="h-4 w-4" />, adminOnly: true },
    ],
  },
];

export function AppLayout() {
  const { user, isAdmin, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const [collapsed, setCollapsed] = useState(false);
  const [syncingToLocal, setSyncingToLocal] = useState(false);
  const [syncMessage, setSyncMessage] = useState("");
  const [genericKBs, setGenericKBs] = useState<GenericKBSummary[]>([]);
  const [showCreateKB, setShowCreateKB] = useState(false);
  const [newKbName, setNewKbName] = useState("");
  const [newKbLabel, setNewKbLabel] = useState("");
  const [creatingKB, setCreatingKB] = useState(false);
  const [showDeleteKB, setShowDeleteKB] = useState(false);
  const [deletingKB, setDeletingKB] = useState<string | null>(null);

  const refreshKBs = () => {
    listGenericKBs()
      .then(setGenericKBs)
      .catch(() => setGenericKBs([]));
  };

  // 加载通用知识库列表
  useEffect(() => { refreshKBs(); }, []);

  async function handleCreateKB() {
    if (!newKbName.trim()) return;
    setCreatingKB(true);
    try {
      await createGenericKB(newKbName.trim(), newKbLabel.trim());
      setShowCreateKB(false);
      setNewKbName("");
      setNewKbLabel("");
      await refreshKBs();
      navigate(`/knowledge/generic/${encodeURIComponent(newKbName.trim())}`);
    } catch (e) {
      alert(`创建失败: ${e}`);
    } finally {
      setCreatingKB(false);
    }
  }

  async function handleDeleteKB(kbName: string) {
    if (!window.confirm(`确认删除知识库 “${kbName}” 及其下所有条目？此操作不可恢复。`)) return;
    setDeletingKB(kbName);
    try {
      await deleteGenericKB(kbName);
      if (window.location.pathname.startsWith(`/console/knowledge/generic/${encodeURIComponent(kbName)}`)) {
        navigate("/console/knowledge");
      }
      await refreshKBs();
      setShowDeleteKB(false);
    } catch (e) {
      alert(`删除失败: ${e}`);
    } finally {
      setDeletingKB(null);
    }
  }

  // 构建动态导航
  const navGroups = useMemo(() => {
    const groups = STATIC_NAV_GROUPS.map((g) => ({ ...g, items: [...g.items] }));
    // 在知识库分组末尾追加动态知识库
    const kbGroup = groups.find((g) => g.title === "知识库");
    if (kbGroup && genericKBs.length > 0) {
      for (const kb of genericKBs) {
        kbGroup.items.push({
          to: `/knowledge/generic/${encodeURIComponent(kb.kb_name)}`,
          label: kb.label || kb.kb_name,
          icon: <BookOpen className="h-4 w-4" />,
        });
      }
    }
    return groups;
  }, [genericKBs]);

  async function handleSyncToLocal() {
    if (!window.confirm("将 Neo4j 数据同步到本地文件，覆盖 mes_knowledge_base.txt、dify_few_shot.txt、mes_relation_graph.json。确认？")) return;
    setSyncingToLocal(true);
    setSyncMessage("");
    try {
      const result = await syncKnowledgeFromNeo4j();
      const fileList = result.synced_files?.map((f: string) => `  - ${f}`).join("\n") || "";
      setSyncMessage(`同步完成：${result.table_count} 张表, ${result.few_shot_count} 条SQL示例, ${result.relation_count} 条关系边\n\n已同步文件：\n${fileList}`);

      try {
        const { files } = await downloadSyncedFiles();
        for (const [name, content] of Object.entries(files)) {
          const blob = new Blob([content], { type: "text/plain;charset=utf-8" });
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url;
          a.download = name;
          document.body.appendChild(a);
          a.click();
          document.body.removeChild(a);
          URL.revokeObjectURL(url);
        }
      } catch {
        // 下载文件失败不影响同步结果
      }
    } catch (e) {
      setSyncMessage(`同步失败: ${e}`);
    } finally {
      setSyncingToLocal(false);
    }
  }

  async function handleLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="flex h-screen overflow-hidden bg-[var(--bg-base)]">
      {/* 侧边栏 */}
      <aside
        className={cn(
          "flex flex-col border-r border-[var(--border-default)] bg-[var(--bg-raised)] transition-all duration-200",
          collapsed ? "w-14" : "w-52",
        )}
      >
        {/* Logo */}
        <div className="flex h-12 items-center gap-2 border-b border-[var(--border-default)] px-4">
          <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded border border-[var(--border-accent)] bg-[var(--accent-surface)]">
            <span className="font-display text-sm font-bold text-[var(--accent)]">M</span>
          </div>
          {!collapsed && (
            <span className="font-display text-sm font-semibold tracking-wide text-[var(--text-primary)]">
              MES NL2SQL
            </span>
          )}
        </div>

        {/* 导航分组 */}
        <nav className="flex-1 overflow-y-auto py-3">
          {navGroups.map((group) => {
            const visibleItems = group.items.filter((item) => !item.adminOnly || isAdmin);
            if (visibleItems.length === 0) return null;
            return (
              <div key={group.title} className="mb-4">
                {!collapsed && (
                  <div className="px-4 py-1 font-mono text-[10px] uppercase tracking-[0.1em] text-[var(--text-tertiary)]">
                    {group.title}
                  </div>
                )}
                {visibleItems.map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === "/"}
                    className={({ isActive }) =>
                      cn(
                        "flex items-center gap-2.5 px-4 py-2 text-[12px] transition-colors",
                        collapsed && "justify-center",
                        isActive
                          ? "border-l-2 border-[var(--accent)] bg-[var(--accent-surface)] text-[var(--accent)]"
                          : "border-l-2 border-transparent text-[var(--text-secondary)] hover:bg-[var(--bg-subtle)] hover:text-[var(--text-primary)]",
                      )
                    }
                    title={collapsed ? item.label : undefined}
                  >
                    {item.icon}
                    {!collapsed && <span>{item.label}</span>}
                  </NavLink>
                ))}
                {/* 知识库分组底部：新增/删除知识库按钮 */}
                {group.title === "知识库" && !collapsed && (
                  <div className="flex items-center">
                    <button
                      type="button"
                      onClick={() => setShowCreateKB(true)}
                      className="flex flex-1 items-center gap-2.5 px-4 py-1.5 text-[11px] text-[var(--text-tertiary)] transition-colors hover:bg-[var(--bg-subtle)] hover:text-[var(--accent)]"
                    >
                      <Plus size={14} />
                      <span>新增知识库</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setShowDeleteKB(true)}
                      disabled={genericKBs.length === 0}
                      className="flex items-center gap-1.5 px-3 py-1.5 text-[11px] text-[var(--text-tertiary)] transition-colors hover:bg-[var(--bg-subtle)] hover:text-[var(--error)] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:bg-transparent disabled:hover:text-[var(--text-tertiary)]"
                      title={genericKBs.length === 0 ? "暂无可删除的知识库" : "删除知识库"}
                    >
                      <Trash2 size={14} />
                      <span>删除</span>
                    </button>
                  </div>
                )}
              </div>
            );
          })}
        </nav>

        {/* 同步到本地 */}
        {!collapsed && (
          <div className="border-t border-[var(--border-default)] px-3 py-2 space-y-1.5">
            <button
              type="button"
              onClick={handleSyncToLocal}
              disabled={syncingToLocal}
              className="inline-flex w-full items-center justify-center gap-1 rounded border border-[var(--border-default)] px-2 py-1.5 text-[11px] font-medium text-[var(--text-secondary)] transition-colors hover:bg-[var(--bg-hover)] disabled:opacity-50"
              title="将 Neo4j 数据同步到本地文件"
            >
              {syncingToLocal ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
              同步到本地
            </button>
            {syncMessage && (
              <div className={`rounded border px-2 py-1 text-[10px] whitespace-pre-line ${
                syncMessage.startsWith("同步失败")
                  ? "border-red-300 bg-red-50 text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300"
                  : "border-green-300 bg-green-50 text-green-700 dark:border-green-800 dark:bg-green-950 dark:text-green-300"
              }`}>
                <div className="flex items-start justify-between gap-1">
                  <span className="line-clamp-3">{syncMessage}</span>
                  <button onClick={() => setSyncMessage("")} className="shrink-0 text-current opacity-60 hover:opacity-100">
                    <X size={12} />
                  </button>
                </div>
              </div>
            )}
          </div>
        )}

        {/* 折叠按钮 */}
        <button
          type="button"
          onClick={() => setCollapsed((v) => !v)}
          className="border-t border-[var(--border-default)] py-2 text-center font-mono text-[10px] text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
        >
          {collapsed ? "▶" : "◀ 折叠"}
        </button>
      </aside>

      {/* 主区域 */}
      <div className="flex flex-1 flex-col overflow-hidden">
        {/* 顶部栏 */}
        <header className="flex h-12 shrink-0 items-center justify-between border-b border-[var(--border-default)] bg-[var(--bg-raised)] px-4">
          <div className="font-mono text-[11px] text-[var(--text-tertiary)]">
            MES 自然语言查询控制台
          </div>
          <div className="flex items-center gap-3">
            {/* 主题切换 */}
            <button
              type="button"
              onClick={toggleTheme}
              className="rounded p-1.5 text-[var(--text-tertiary)] hover:bg-[var(--bg-subtle)] hover:text-[var(--text-primary)]"
              title="切换主题"
            >
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>

            {/* 用户信息 */}
            <div className="flex items-center gap-2 border-l border-[var(--border-default)] pl-3">
              <div className="text-right">
                <div className="text-[12px] text-[var(--text-primary)]">
                  {user?.display_name || user?.username || "未知"}
                </div>
                <div className="font-mono text-[10px] text-[var(--text-tertiary)]">
                  {user?.role ?? "user"}
                </div>
              </div>
              <button
                type="button"
                onClick={handleLogout}
                className="rounded p-1.5 text-[var(--text-tertiary)] hover:bg-[var(--error-glow)] hover:text-[var(--error)]"
                title="登出"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          </div>
        </header>

        {/* 页面内容 */}
        <main className="flex-1 overflow-auto">
          <Outlet />
        </main>
      </div>

      {/* 新增知识库对话框 */}
      {showCreateKB && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-[380px] rounded-lg border border-[var(--border-default)] bg-white p-5 shadow-xl">
            <div className="mb-4 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">新增知识库</h3>
              <button onClick={() => setShowCreateKB(false)} className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--bg-hover)]">
                <X size={16} />
              </button>
            </div>
            <div className="space-y-3">
              <label className="block space-y-1">
                <span className="text-[11px] font-medium text-[var(--text-secondary)]">
                  知识库名称 <span className="text-[var(--error)]">*</span>
                </span>
                <input
                  type="text"
                  value={newKbName}
                  onChange={(e) => setNewKbName(e.target.value)}
                  placeholder="如: Person"
                  className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                  autoFocus
                />
              </label>
              <label className="block space-y-1">
                <span className="text-[11px] font-medium text-[var(--text-secondary)]">显示名称</span>
                <input
                  type="text"
                  value={newKbLabel}
                  onChange={(e) => setNewKbLabel(e.target.value)}
                  placeholder="默认为知识库名称"
                  className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-default)] px-2.5 py-1.5 text-xs text-[var(--text-primary)] focus:border-[var(--accent)] focus:outline-none"
                />
              </label>
            </div>
            <div className="mt-5 flex justify-end gap-2">
              <button onClick={() => setShowCreateKB(false)} className="rounded px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]">取消</button>
              <button
                onClick={handleCreateKB}
                disabled={creatingKB || !newKbName.trim()}
                className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
              >
                {creatingKB ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
                创建
              </button>
            </div>
          </div>
        </div>
      )}

      {/* 删除知识库对话框 */}
      {showDeleteKB && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-[420px] max-h-[80vh] flex flex-col rounded-lg border border-[var(--border-default)] bg-white p-5 shadow-xl">
            <div className="mb-3 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-[var(--text-primary)]">删除知识库</h3>
              <button onClick={() => setShowDeleteKB(false)} className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--bg-hover)]">
                <X size={16} />
              </button>
            </div>
            <p className="mb-3 text-[11px] text-[var(--text-tertiary)]">
              选择要删除的知识库，该知识库下的所有条目将被一并删除，操作不可恢复。
            </p>
            <div className="flex-1 overflow-y-auto rounded border border-[var(--border-default)]">
              {genericKBs.length === 0 ? (
                <div className="px-3 py-6 text-center text-[11px] text-[var(--text-tertiary)]">
                  暂无可删除的知识库
                </div>
              ) : (
                genericKBs.map((kb) => {
                  const isDeleting = deletingKB === kb.kb_name;
                  return (
                    <div
                      key={kb.kb_name}
                      className="flex items-center justify-between border-b border-[var(--border-default)] px-3 py-2 last:border-b-0 hover:bg-[var(--bg-hover)]"
                    >
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-xs font-medium text-[var(--text-primary)]">
                          {kb.label || kb.kb_name}
                        </div>
                        <div className="truncate font-mono text-[10px] text-[var(--text-tertiary)]">
                          {kb.kb_name} · {kb.item_count} 条
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => handleDeleteKB(kb.kb_name)}
                        disabled={deletingKB !== null}
                        className="ml-2 inline-flex items-center gap-1 rounded border border-[var(--error)] px-2 py-1 text-[11px] text-[var(--error)] transition-colors hover:bg-[var(--error-glow)] disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {isDeleting ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
                        删除
                      </button>
                    </div>
                  );
                })
              )}
            </div>
            <div className="mt-4 flex justify-end">
              <button onClick={() => setShowDeleteKB(false)} className="rounded px-3 py-1.5 text-xs text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]">关闭</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
