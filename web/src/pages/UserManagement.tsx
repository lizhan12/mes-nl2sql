import { RefreshCw, Search, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { deleteUser, fetchUsers, resetUserPassword, createUser, type AuthUser } from "@/lib/api";

export default function UserManagement() {
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [totalRows, setTotalRows] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [showCreate, setShowCreate] = useState(false);
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newDisplayName, setNewDisplayName] = useState("");
  const [createError, setCreateError] = useState("");
  const [creating, setCreating] = useState(false);

  const [resetUserId, setResetUserId] = useState<number | null>(null);
  const [resetPassword, setResetPassword] = useState("");
  const [resetError, setResetError] = useState("");
  const [resetting, setResetting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const res = await fetchUsers(page, 20, search);
      setUsers(res.items);
      setTotalRows(res.total_rows);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载失败");
    } finally {
      setLoading(false);
    }
  }, [page, search]);

  useEffect(() => { load(); }, [load]);

  function handleSearch() {
    setSearch(searchInput);
    setPage(1);
  }

  async function handleCreate() {
    if (!newUsername.trim() || !newPassword) {
      setCreateError("用户名和密码必填");
      return;
    }
    setCreateError("");
    setCreating(true);
    try {
      await createUser({
        username: newUsername.trim(),
        password: newPassword,
        display_name: newDisplayName.trim() || undefined,
      });
      setShowCreate(false);
      setNewUsername("");
      setNewPassword("");
      setNewDisplayName("");
      await load();
    } catch (err) {
      setCreateError(err instanceof Error ? err.message : "创建失败");
    } finally {
      setCreating(false);
    }
  }

  async function handleResetPassword(userId: number) {
    if (!resetPassword) {
      setResetError("请输入新密码");
      return;
    }
    setResetError("");
    setResetting(true);
    try {
      await resetUserPassword(userId, resetPassword);
      setResetUserId(null);
      setResetPassword("");
    } catch (err) {
      setResetError(err instanceof Error ? err.message : "重置失败");
    } finally {
      setResetting(false);
    }
  }

  async function handleDelete(userId: number, username: string) {
    if (!confirm(`确定删除用户 "${username}" 吗？此操作不可撤销。`)) return;
    try {
      await deleteUser(userId);
      await load();
    } catch (err) {
      alert(err instanceof Error ? err.message : "删除失败");
    }
  }

  const totalPages = Math.ceil(totalRows / 20);

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-[var(--border-default)] px-4 py-3">
        <h2 className="font-display text-sm font-semibold text-[var(--text-primary)]">用户管理</h2>
        <button
          type="button"
          onClick={() => setShowCreate((v) => !v)}
          className="inline-flex items-center gap-1 rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90"
        >
          新增用户
        </button>
      </div>

      {error && (
        <div className="mx-4 mt-3 rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700 dark:border-red-800 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      )}

      {/* 新建表单 */}
      {showCreate && (
        <div className="mx-4 mt-3 rounded border border-[var(--border-default)] bg-[var(--bg-default)] p-4">
          <h3 className="mb-3 text-xs font-semibold text-[var(--text-primary)]">新建用户</h3>
          <div className="space-y-3">
            <div>
              <label className="mb-1 block text-[11px] text-[var(--text-secondary)]">用户名</label>
              <input type="text" value={newUsername} onChange={(e) => setNewUsername(e.target.value)} className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-input)] px-2 py-1.5 text-xs focus:border-[var(--accent)] focus:outline-none" />
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-[var(--text-secondary)]">密码</label>
              <input type="password" value={newPassword} onChange={(e) => setNewPassword(e.target.value)} className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-input)] px-2 py-1.5 text-xs focus:border-[var(--accent)] focus:outline-none" />
            </div>
            <div>
              <label className="mb-1 block text-[11px] text-[var(--text-secondary)]">显示名称（可选）</label>
              <input type="text" value={newDisplayName} onChange={(e) => setNewDisplayName(e.target.value)} className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-input)] px-2 py-1.5 text-xs focus:border-[var(--accent)] focus:outline-none" />
            </div>
            {createError && <div className="rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700">{createError}</div>}
            <button type="button" disabled={creating} onClick={handleCreate} className="rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60">
              {creating ? "创建中..." : "创建"}
            </button>
          </div>
        </div>
      )}

      {/* 搜索 */}
      <div className="flex items-center gap-2 px-4 py-3">
        <input
          type="text"
          value={searchInput}
          onChange={(e) => setSearchInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleSearch()}
          placeholder="搜索用户..."
          className="w-48 rounded border border-[var(--border-default)] bg-[var(--bg-input)] px-2 py-1.5 text-xs focus:border-[var(--accent)] focus:outline-none"
        />
        <button type="button" onClick={handleSearch} className="rounded border border-[var(--border-default)] bg-[var(--bg-subtle)] p-1.5 text-[var(--text-secondary)] hover:text-[var(--accent)]">
          <Search className="h-3.5 w-3.5" />
        </button>
      </div>

      {/* 列表 */}
      <div className="flex-1 overflow-auto px-4">
        {loading ? (
          <div className="py-8 text-center text-xs text-[var(--text-tertiary)]">加载中...</div>
        ) : (
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-[var(--border-default)] text-[var(--text-tertiary)]">
                <th className="py-2 font-medium">用户名</th>
                <th className="py-2 font-medium">显示名称</th>
                <th className="py-2 font-medium">角色</th>
                <th className="py-2 font-medium">最后登录</th>
                <th className="py-2 text-right font-medium">操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b border-[var(--border-default)] hover:bg-[var(--bg-subtle)]">
                  <td className="py-2 text-[var(--text-primary)]">{u.username}</td>
                  <td className="py-2 text-[var(--text-secondary)]">{u.display_name || "-"}</td>
                  <td className="py-2">
                    <span className={`rounded px-1.5 py-0.5 font-mono text-[10px] ${u.role === "admin" ? "bg-[var(--accent-surface)] text-[var(--accent)]" : "bg-[var(--bg-subtle)] text-[var(--text-tertiary)]"}`}>
                      {u.role}
                    </span>
                  </td>
                  <td className="py-2 text-[var(--text-tertiary)]">{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "-"}</td>
                  <td className="py-2 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button type="button" onClick={() => setResetUserId(u.id)} className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--bg-subtle)] hover:text-[var(--accent)]" title="重置密码">
                        <RefreshCw className="h-3.5 w-3.5" />
                      </button>
                      <button type="button" onClick={() => handleDelete(u.id, u.username)} className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--error-glow)] hover:text-[var(--error)]" title="删除">
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        {totalPages > 1 && (
          <div className="flex items-center justify-center gap-2 py-4">
            <button type="button" disabled={page <= 1} onClick={() => setPage((p) => p - 1)} className="rounded border border-[var(--border-default)] px-2 py-1 text-xs disabled:opacity-30">上一页</button>
            <span className="text-xs text-[var(--text-tertiary)]">第 {page} / {totalPages} 页</span>
            <button type="button" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)} className="rounded border border-[var(--border-default)] px-2 py-1 text-xs disabled:opacity-30">下一页</button>
          </div>
        )}
      </div>

      {/* 重置密码弹窗 */}
      {resetUserId !== null && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
          <div className="w-80 rounded border border-[var(--border-default)] bg-[var(--bg-raised)] p-4 shadow-xl">
            <h3 className="mb-3 text-xs font-semibold text-[var(--text-primary)]">重置密码</h3>
            <input type="password" value={resetPassword} onChange={(e) => setResetPassword(e.target.value)} placeholder="新密码" className="mb-3 w-full rounded border border-[var(--border-default)] bg-[var(--bg-input)] px-2 py-1.5 text-xs focus:border-[var(--accent)] focus:outline-none" />
            {resetError && <div className="mb-3 rounded border border-red-300 bg-red-50 px-3 py-2 text-xs text-red-700">{resetError}</div>}
            <div className="flex gap-2">
              <button type="button" disabled={resetting} onClick={() => handleResetPassword(resetUserId)} className="rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white disabled:opacity-60">{resetting ? "重置中..." : "确认"}</button>
              <button type="button" onClick={() => { setResetUserId(null); setResetPassword(""); setResetError(""); }} className="rounded border border-[var(--border-default)] px-3 py-1.5 text-xs text-[var(--text-secondary)]">取消</button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
