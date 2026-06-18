import { useCallback, useEffect, useState } from "react";
import type { AuthUser, LoginResponse } from "@/lib/api";
import { fetchCurrentUser, login as apiLogin, logout as apiLogout } from "@/lib/api";

interface AuthState {
  user: AuthUser | null;
  isAuthenticated: boolean;
  isAdmin: boolean;
  loading: boolean;
  login: (username: string, password: string) => Promise<LoginResponse>;
  logout: () => Promise<void>;
}

let globalUser: AuthUser | null = null;
let listeners: Array<() => void> = [];

function notify() {
  for (const fn of listeners) fn();
}

export function useAuth(): AuthState {
  const [, setTick] = useState(0);

  useEffect(() => {
    const fn = () => setTick((n) => n + 1);
    listeners.push(fn);
    return () => {
      listeners = listeners.filter((l) => l !== fn);
    };
  }, []);

  useEffect(() => {
    if (!globalUser) {
      fetchCurrentUser()
        .then((u) => {
          globalUser = u;
          notify();
        })
        .catch(() => {
          globalUser = null;
          notify();
        });
    }
  }, []);

  const login = useCallback(async (username: string, password: string) => {
    const res = await apiLogin(username, password);
    localStorage.setItem("nl2sql_auth_token", res.token);
    localStorage.setItem("nl2sql_user_info", JSON.stringify(res.user));
    globalUser = res.user;
    notify();
    return res;
  }, []);

  const logout = useCallback(async () => {
    await apiLogout().catch(() => {});
    localStorage.removeItem("nl2sql_auth_token");
    localStorage.removeItem("nl2sql_user_info");
    globalUser = null;
    notify();
  }, []);

  return {
    user: globalUser,
    isAuthenticated: !!globalUser,
    isAdmin: globalUser?.role === "admin",
    loading: false,
    login,
    logout,
  };
}
