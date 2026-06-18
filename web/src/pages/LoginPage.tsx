import { Loader2, Lock, Moon, Sun, User } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "@/hooks/useAuth";
import { useTheme } from "@/hooks/useTheme";

export default function LoginPage() {
  const navigate = useNavigate();
  const { login } = useAuth();
  const { theme, toggleTheme } = useTheme();

  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!username || !password) {
      setError("请输入用户名和密码");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await login(username, password);
      navigate("/", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "登录失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--bg-base)] px-4">
      {/* 主题切换 */}
      <button
        type="button"
        onClick={toggleTheme}
        className="absolute right-6 top-6 inline-flex items-center gap-1.5 rounded border border-[var(--border-default)] bg-[var(--bg-subtle)] px-2.5 py-1.5 font-mono text-[11px] text-[var(--text-secondary)] transition-all hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
      >
        {theme === "dark" ? <Sun className="h-3.5 w-3.5" /> : <Moon className="h-3.5 w-3.5" />}
        {theme === "dark" ? "亮色" : "暗色"}
      </button>

      <div className="w-full max-w-sm">
        {/* Logo / 标题 */}
        <div className="mb-8 text-center">
          <div className="mb-3 inline-flex h-12 w-12 items-center justify-center rounded-lg border border-[var(--border-accent)] bg-[var(--accent-surface)]">
            <span className="font-display text-xl font-bold text-[var(--accent)]">M</span>
          </div>
          <h1 className="font-display text-2xl font-bold tracking-wide text-[var(--text-primary)]">
            知识库管理平台
          </h1>
          <p className="mt-1 text-[12px] text-[var(--text-tertiary)]">
            MES 自然语言查询控制台
          </p>
        </div>

        {/* 登录卡片 */}
        <form
          onSubmit={handleSubmit}
          className="relative rounded-lg border border-[var(--border-default)] bg-[var(--bg-raised)] p-6"
        >
          <div
            className="pointer-events-none absolute inset-0 rounded-lg opacity-[0.06]"
            style={{
              border: "1px solid transparent",
              borderImage: `linear-gradient(135deg, var(--accent) 0%, transparent 40%, transparent 60%, var(--accent) 100%) 1`,
            }}
          />

          <div className="relative z-10 space-y-4">
            {/* 用户名 */}
            <div>
              <label className="mb-1.5 block font-mono text-[11px] uppercase tracking-wider text-[var(--text-tertiary)]">
                用户名
              </label>
              <div className="relative">
                <User className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-tertiary)]" />
                <input
                  type="text"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  disabled={loading}
                  autoFocus
                  placeholder="请输入用户名"
                  className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-base)] py-2 pl-9 pr-3 text-sm text-[var(--text-primary)] outline-none transition-colors placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent)]"
                />
              </div>
            </div>

            {/* 密码 */}
            <div>
              <label className="mb-1.5 block font-mono text-[11px] uppercase tracking-wider text-[var(--text-tertiary)]">
                密码
              </label>
              <div className="relative">
                <Lock className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-[var(--text-tertiary)]" />
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={loading}
                  placeholder="请输入密码"
                  className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-base)] py-2 pl-9 pr-3 text-sm text-[var(--text-primary)] outline-none transition-colors placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent)]"
                />
              </div>
            </div>

            {/* 错误提示 */}
            {error && (
              <div className="rounded border border-[var(--error)] bg-[var(--error-glow)] px-3 py-2 text-[12px] text-[var(--error)]">
                {error}
              </div>
            )}

            {/* 登录按钮 */}
            <button
              type="submit"
              disabled={loading}
              className="inline-flex w-full items-center justify-center gap-2 rounded border border-[var(--border-accent)] bg-[var(--accent-surface)] py-2.5 font-display text-sm font-semibold uppercase tracking-wider text-[var(--accent)] transition-all hover:bg-[var(--accent-soft)] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {loading && <Loader2 className="h-4 w-4 animate-spin" />}
              {loading ? "登录中..." : "登录"}
            </button>
          </div>
        </form>

        <p className="mt-4 text-center text-[11px] text-[var(--text-tertiary)]">
          首次使用请以默认账号 admin / admin123 登录
        </p>
      </div>
    </div>
  );
}
