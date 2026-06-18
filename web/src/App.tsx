import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";

import { AppLayout } from "@/components/AppLayout";
import { useAuth } from "@/hooks/useAuth";
import FewShotManagement from "@/pages/FewShotManagement";
import GraphPage from "@/pages/GraphPage";
import Harness from "@/pages/Harness";
import KnowledgePage from "@/pages/KnowledgePage";
import LoginPage from "@/pages/LoginPage";
import RuleManagement from "@/pages/RuleManagement";
import TracePage from "@/pages/TracePage";
import UserManagement from "@/pages/UserManagement";

/** 未登录时重定向到登录页 */
function RequireAuth({ children }: { children: ReactNode }) {
  const { isAuthenticated } = useAuth();
  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }
  return <>{children}</>;
}

/** 非 admin 重定向到首页 */
function RequireAdmin({ children }: { children: ReactNode }) {
  const { isAdmin } = useAuth();
  if (!isAdmin) {
    return <Navigate to="/" replace />;
  }
  return <>{children}</>;
}

export default function App() {
  return (
    <BrowserRouter basename="/console">
      <Routes>
        {/* 登录页（无布局） */}
        <Route path="/login" element={<LoginPage />} />

        {/* 受保护路由（带侧边栏布局） */}
        <Route
          element={
            <RequireAuth>
              <AppLayout />
            </RequireAuth>
          }
        >
          <Route path="/" element={<KnowledgePage />} />
          <Route path="/graph" element={<GraphPage />} />
          <Route path="/trace" element={<TracePage />} />
          <Route path="/knowledge" element={<KnowledgePage />} />
          <Route path="/few-shot" element={<FewShotManagement />} />
          <Route path="/rule" element={<RuleManagement />} />
          <Route
            path="/harness"
            element={
              <RequireAdmin>
                <Harness />
              </RequireAdmin>
            }
          />
          <Route
            path="/users"
            element={
              <RequireAdmin>
                <UserManagement />
              </RequireAdmin>
            }
          />
        </Route>

        {/* 兜底：未知路由重定向到首页 */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
