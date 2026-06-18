import { useCallback, useEffect, useState } from "react";

import { fetchCurrentUser, login as apiLogin, logout as apiLogout } from "@/lib/api";

export interface AuthUser {
  id: number;
  username: string;
  display_name: string;
  role: string;
  created_at?: string;
  last_login_at?: string;
}

const TOKEN_KEY = "nl2sql_auth_token";
const USER_KEY = "nl2sql_user_info";

function loadUser(): AuthUser | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

export function useAuth() {
  const [token, setToken] = useState<string>(() => localStorage.getItem(TOKEN_KEY) ?? "");
  const [user, setUser] = useState<AuthUser | null>(() => loadUser());

  const isAuthenticated = !!token && !!user;
  const isAdmin = user?.role === "admin";

  /** 登录：成功后保存 token 和用户信息 */
  const login = useCallback(async (username: string, password: string) => {
    const res = await apiLogin(username, password);
    localStorage.setItem(TOKEN_KEY, res.token);
    localStorage.setItem(USER_KEY, JSON.stringify(res.user));
    setToken(res.token);
    setUser(res.user);
    return res.user;
  }, []);

  /** 登出：清除本地状态并通知后端 */
  const logout = useCallback(async () => {
    try {
      await apiLogout();
    } catch {
      // 忽略后端错误，本地强制清除
    }
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem(USER_KEY);
    setToken("");
    setUser(null);
  }, []);

  /** 刷新当前用户信息（用于校验 token 是否仍有效） */
  const refreshUser = useCallback(async () => {
    if (!token) return null;
    try {
      const me = await fetchCurrentUser();
      localStorage.setItem(USER_KEY, JSON.stringify(me));
      setUser(me);
      return me;
    } catch {
      // token 失效，清除本地状态
      localStorage.removeItem(TOKEN_KEY);
      localStorage.removeItem(USER_KEY);
      setToken("");
      setUser(null);
      return null;
    }
  }, [token]);

  // 启动时若有 token，校验一次（静默失败则清除）
  useEffect(() => {
    if (token && !user) {
      void refreshUser();
    }
  }, [token, user, refreshUser]);

  return {
    token,
    user,
    isAuthenticated,
    isAdmin,
    login,
    logout,
    refreshUser,
  };
}
