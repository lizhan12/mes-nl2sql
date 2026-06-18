import {
  Database,
  GitBranch,
  Layers,
  LogOut,
  Moon,
  Network,
  ScrollText,
  ShieldCheck,
  Sun,
  Users,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";
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
      { to: "/trace", label: "链路追踪", icon: <ScrollText className="h-4 w-4" /> },
    ],
  },
  {
    title: "知识库",
    items: [
      { to: "/", label: "表知识库", icon: <Database className="h-4 w-4" /> },
      { to: "/few-shot", label: "FewShot", icon: <Layers className="h-4 w-4" /> },
      { to: "/rule", label: "运行时规则", icon: <GitBranch className="h-4 w-4" /> },
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
                title="退出"
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
