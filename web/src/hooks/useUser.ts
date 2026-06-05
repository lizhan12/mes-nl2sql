import { useState } from "react";

function generateUserId(): string {
  return Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
}

export function useUser() {
  const [userId] = useState<string>(() => {
    const stored = localStorage.getItem("nl2sql_user_id");
    if (stored) return stored;
    const newId = generateUserId();
    localStorage.setItem("nl2sql_user_id", newId);
    return newId;
  });
  return { userId };
}
