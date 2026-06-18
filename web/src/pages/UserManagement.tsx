import { KeyRound, Loader2, Pencil, Plus, Search, Trash2, X } from "lucide-react";
import { useEffect, useState } from "react";

import { PaginationBar } from "@/components/PaginationBar";
import { Panel } from "@/components/Panel";
import { StatusBadge } from "@/components/StatusBadge";
import { useAuth } from "@/hooks/useAuth";
import type { AuthUser } from "@/lib/api";
import {
  createUser,
  deleteUser,
  fetchUsers,
  resetUserPassword,
  updateUser,
} from "@/lib/api";

const PAGE_SIZE = 10;

interface EditState {
  mode: "create" | "edit";
  user?: AuthUser;
}

export default function UserManagement() {
  const { user: currentUser } = useAuth();
  const [users, setUsers] = useState<AuthUser[]>([]);
  const [page, setPage] = useState(1);
  const [totalRows, setTotalRows] = useState(0);
  const [totalPages, setTotalPages] = useState(0);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(false);
  const [editState, setEditState] = useState<EditState | null>(null);
  const [resetTarget, setResetTarget] = useState<AuthUser | null>(null);

  async function loadUsers() {
    setLoading(true);
    try {
      const res = await fetchUsers(page, PAGE_SIZE, search);
      setUsers(res.items);
      setTotalRows(res.total_rows);
      setTotalPages(res.total_pages);
    } catch (err) {
      console.error("加载用户列表失败", err);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void loadUsers();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [page]);

  function handleSearch() {
    setPage(1);
    void loadUsers();
  }

  async function handleDelete(user: AuthUser) {
    if (!confirm(`确认删除用户 ${user.username}？此操作不可恢复。`)) return;
    try {
      await deleteUser(user.id);
      void loadUsers();
    } catch (err) {
      alert(err instanceof Error ? err.message : "删除失败");
    }
  }

  return (
    <div className="space-y-4">
      <Panel
        title="用户管理"
        subtitle={`共 ${totalRows} 个用户`}
        action={
          <button
            type="button"
            onClick={() => setEditState({ mode: "create" })}
            className="inline-flex items-center gap-1.5 rounded border border-[var(--border-accent)] bg-[var(--accent-surface)] px-3 py-1.5 font-mono text-[11px] text-[var(--accent)] transition-all hover:bg-[var(--accent-soft)]"
          >
            <Plus className="h-3.5 w-3.5" />
            新建用户
          </button>
        }
      >
        {/* 搜索栏 */}
        <div className="mb-4 flex items-center gap-2">
          <div className="relative flex-1 max-w-xs">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-[var(--text-tertiary)]" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && handleSearch()}
              placeholder="搜索用户名或显示名"
              className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-base)] py-1.5 pl-8 pr-3 text-[12px] text-[var(--text-primary)] outline-none placeholder:text-[var(--text-tertiary)] focus:border-[var(--accent)]"
            />
          </div>
          <button
            type="button"
            onClick={handleSearch}
            className="rounded border border-[var(--border-default)] bg-[var(--bg-subtle)] px-3 py-1.5 font-mono text-[11px] text-[var(--text-secondary)] hover:border-[var(--border-strong)] hover:text-[var(--text-primary)]"
          >
            搜索
          </button>
        </div>

        {/* 用户表格 */}
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left text-[12px]">
            <thead>
              <tr className="border-b border-[var(--border-default)] text-[var(--text-tertiary)]">
                <th className="py-2 pr-4 font-mono font-normal uppercase tracking-wider">用户名</th>
                <th className="py-2 pr-4 font-mono font-normal uppercase tracking-wider">显示名</th>
                <th className="py-2 pr-4 font-mono font-normal uppercase tracking-wider">角色</th>
                <th className="py-2 pr-4 font-mono font-normal uppercase tracking-wider">创建时间</th>
                <th className="py-2 pr-4 font-mono font-normal uppercase tracking-wider">最后登录</th>
                <th className="py-2 pr-4 font-mono font-normal uppercase tracking-wider text-right">操作</th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr
                  key={u.id}
                  className="border-b border-[var(--border-default)]/50 text-[var(--text-secondary)] hover:bg-[var(--bg-subtle)]"
                >
                  <td className="py-2.5 pr-4 font-mono text-[var(--text-primary)]">{u.username}</td>
                  <td className="py-2.5 pr-4">{u.display_name || "-"}</td>
                  <td className="py-2.5 pr-4">
                    <StatusBadge tone={u.role === "admin" ? "success" : "neutral"}>
                      {u.role}
                    </StatusBadge>
                  </td>
                  <td className="py-2.5 pr-4 font-mono text-[var(--text-tertiary)]">
                    {u.created_at ? new Date(u.created_at).toLocaleString() : "-"}
                  </td>
                  <td className="py-2.5 pr-4 font-mono text-[var(--text-tertiary)]">
                    {u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "-"}
                  </td>
                  <td className="py-2.5 pr-4">
                    <div className="flex items-center justify-end gap-1.5">
                      <button
                        type="button"
                        title="编辑"
                        onClick={() => setEditState({ mode: "edit", user: u })}
                        className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--accent-surface)] hover:text-[var(--accent)]"
                      >
                        <Pencil className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title="重置密码"
                        onClick={() => setResetTarget(u)}
                        className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--warning-glow)] hover:text-[var(--warning)]"
                      >
                        <KeyRound className="h-3.5 w-3.5" />
                      </button>
                      <button
                        type="button"
                        title="删除"
                        disabled={u.id === currentUser?.id}
                        onClick={() => void handleDelete(u)}
                        className="rounded p-1 text-[var(--text-tertiary)] hover:bg-[var(--error-glow)] hover:text-[var(--error)] disabled:cursor-not-allowed disabled:opacity-30"
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
              {users.length === 0 && !loading && (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-[var(--text-tertiary)]">
                    暂无用户数据
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {loading && (
          <div className="flex items-center justify-center py-4">
            <Loader2 className="h-4 w-4 animate-spin text-[var(--accent)]" />
          </div>
        )}

        <PaginationBar
          page={page}
          totalPages={totalPages}
          totalRows={totalRows}
          loading={loading}
          onPageChange={setPage}
        />
      </Panel>

      {/* 新建/编辑弹窗 */}
      {editState && (
        <UserEditDialog
          state={editState}
          onClose={() => setEditState(null)}
          onSuccess={() => {
            setEditState(null);
            void loadUsers();
          }}
        />
      )}

      {/* 重置密码弹窗 */}
      {resetTarget && (
        <ResetPasswordDialog
          user={resetTarget}
          onClose={() => setResetTarget(null)}
          onSuccess={() => setResetTarget(null)}
        />
      )}
    </div>
  );
}

// ── 新建/编辑用户弹窗 ──

function UserEditDialog({
  state,
  onClose,
  onSuccess,
}: {
  state: EditState;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const isCreate = state.mode === "create";
  const [username, setUsername] = useState(state.user?.username ?? "");
  const [password, setPassword] = useState("");
  const [displayName, setDisplayName] = useState(state.user?.display_name ?? "");
  const [role, setRole] = useState<"admin" | "user">(
    (state.user?.role as "admin" | "user") ?? "user",
  );
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError("");
    try {
      if (isCreate) {
        if (!username || !password) {
          setError("用户名和密码不能为空");
          setLoading(false);
          return;
        }
        await createUser({ username, password, display_name: displayName, role });
      } else if (state.user) {
        await updateUser(state.user.id, { display_name: displayName, role });
      }
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <ModalDialog title={isCreate ? "新建用户" : "编辑用户"} onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-3">
        <FormField label="用户名">
          <input
            type="text"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
            disabled={!isCreate}
            className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-base)] px-3 py-1.5 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)] disabled:opacity-50"
          />
        </FormField>

        {isCreate && (
          <FormField label="密码">
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="至少 6 位"
              className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-base)] px-3 py-1.5 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
            />
          </FormField>
        )}

        <FormField label="显示名">
          <input
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-base)] px-3 py-1.5 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
          />
        </FormField>

        <FormField label="角色">
          <select
            value={role}
            onChange={(e) => setRole(e.target.value as "admin" | "user")}
            className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-base)] px-3 py-1.5 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
          >
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
        </FormField>

        {error && (
          <div className="rounded border border-[var(--error)] bg-[var(--error-glow)] px-3 py-2 text-[12px] text-[var(--error)]">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-[var(--border-default)] px-3 py-1.5 font-mono text-[11px] text-[var(--text-secondary)] hover:border-[var(--border-strong)]"
          >
            取消
          </button>
          <button
            type="submit"
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded border border-[var(--border-accent)] bg-[var(--accent-surface)] px-3 py-1.5 font-mono text-[11px] text-[var(--accent)] hover:bg-[var(--accent-soft)] disabled:opacity-50"
          >
            {loading && <Loader2 className="h-3 w-3 animate-spin" />}
            {isCreate ? "创建" : "保存"}
          </button>
        </div>
      </form>
    </ModalDialog>
  );
}

// ── 重置密码弹窗 ──

function ResetPasswordDialog({
  user,
  onClose,
  onSuccess,
}: {
  user: AuthUser;
  onClose: () => void;
  onSuccess: () => void;
}) {
  const [newPassword, setNewPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (newPassword.length < 6) {
      setError("密码至少 6 位");
      return;
    }
    setLoading(true);
    setError("");
    try {
      await resetUserPassword(user.id, newPassword);
      onSuccess();
    } catch (err) {
      setError(err instanceof Error ? err.message : "重置失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <ModalDialog title={`重置密码 - ${user.username}`} onClose={onClose}>
      <form onSubmit={handleSubmit} className="space-y-3">
        <FormField label="新密码">
          <input
            type="password"
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            placeholder="至少 6 位"
            className="w-full rounded border border-[var(--border-default)] bg-[var(--bg-base)] px-3 py-1.5 text-sm text-[var(--text-primary)] outline-none focus:border-[var(--accent)]"
          />
        </FormField>

        {error && (
          <div className="rounded border border-[var(--error)] bg-[var(--error-glow)] px-3 py-2 text-[12px] text-[var(--error)]">
            {error}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded border border-[var(--border-default)] px-3 py-1.5 font-mono text-[11px] text-[var(--text-secondary)] hover:border-[var(--border-strong)]"
          >
            取消
          </button>
          <button
            type="submit"
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded border border-[var(--border-accent)] bg-[var(--accent-surface)] px-3 py-1.5 font-mono text-[11px] text-[var(--accent)] hover:bg-[var(--accent-soft)] disabled:opacity-50"
          >
            {loading && <Loader2 className="h-3 w-3 animate-spin" />}
            确认重置
          </button>
        </div>
      </form>
    </ModalDialog>
  );
}

// ── 通用组件 ──

function ModalDialog({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-md rounded-lg border border-[var(--border-default)] bg-[var(--bg-raised)] p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="font-display text-sm font-semibold uppercase tracking-wider text-[var(--text-primary)]">
            {title}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-[var(--text-tertiary)] hover:text-[var(--text-primary)]"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function FormField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="mb-1 block font-mono text-[11px] uppercase tracking-wider text-[var(--text-tertiary)]">
        {label}
      </label>
      {children}
    </div>
  );
}
