import {
  Database,
  GitBranch,
  Layers,
  Loader2,
  LogOut,
  Moon,
  Network,
  Save,
  ScrollText,
  Search,
  ShieldCheck,
  Sun,
  Users,
  X,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";
import { downloadSyncedFiles, syncKnowledgeFromNeo4j } from "@/lib/api";
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

const NAV_GROUPS: NavGroup[] = [
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
          {NAV_GROUPS.map((group) => {
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
        <main className="flex-1 overflow-auto p-4">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
