import { useEffect, useState } from "react";

export function useTheme() {
  const [dark, setDark] = useState(() => {
    try { const stored = localStorage.getItem("theme"); if (stored) return stored === "dark"; } catch { /* ignore */ }
    return window.matchMedia("(prefers-color-scheme: dark)").matches;
  });
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
    try { localStorage.setItem("theme", dark ? "dark" : "light"); } catch { /* ignore */ }
  }, [dark]);
  return { dark, toggle: () => setDark((isDark) => !isDark) };
}
