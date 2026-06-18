/** 知识库同步状态共享（AppLayout 侧边栏触发，KnowledgePage 实际执行）。 */

import { create } from "zustand";

interface KnowledgeSyncState {
  /** 是否正在同步（驱动 sidebar 按钮的 spinner 与 disabled） */
  syncing: boolean;
  /** KnowledgePage 注册的同步执行函数 */
  triggerSync: (() => void) | null;
  setSyncing: (syncing: boolean) => void;
  setTriggerSync: (fn: (() => void) | null) => void;
  /** 侧边栏按钮调用：派发到 KnowledgePage 注册的函数 */
  handleSync: () => void;
}

export const useKnowledgeSyncStore = create<KnowledgeSyncState>((set, get) => ({
  syncing: false,
  triggerSync: null,
  setSyncing: (syncing) => set({ syncing }),
  setTriggerSync: (fn) => set({ triggerSync: fn }),
  handleSync: () => {
    const fn = get().triggerSync;
    if (fn) fn();
  },
}));
