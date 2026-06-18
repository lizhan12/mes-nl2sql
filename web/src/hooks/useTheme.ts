import { useCallback, useEffect, useState } from "react";

const KEY = "nl2sql_theme";

function getStored(): "light" | "dark" {
  const v = localStorage.getItem(KEY);
  if (v === "dark") return "dark";
  return "light";
}

function apply(theme: "light" | "dark") {
  const root = document.documentElement;
  if (theme === "dark") {
    root.classList.add("dark");
    root.setAttribute("data-theme", "dark");
  } else {
    root.classList.remove("dark");
    root.removeAttribute("data-theme");
  }
}

let current: "light" | "dark" = getStored();
apply(current);
let listeners: Array<() => void> = [];

function notify() {
  for (const fn of listeners) fn();
}

export function useTheme() {
  const [theme, setTheme] = useState<"light" | "dark">(current);

  useEffect(() => {
    const fn = () => setTheme(current);
    listeners.push(fn);
    return () => {
      listeners = listeners.filter((l) => l !== fn);
    };
  }, []);

  const toggleTheme = useCallback(() => {
    current = current === "light" ? "dark" : "light";
    localStorage.setItem(KEY, current);
    apply(current);
    notify();
  }, []);

  return {
    theme,
    isDark: theme === "dark",
    toggleTheme,
  };
}
