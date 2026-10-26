import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import type { Theme } from "../lib/types";

const Context = createContext({
  theme: "system" as Theme,
  resolved: "dark" as "light" | "dark",
  setTheme: (_theme: Theme) => {},
});
export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setTheme] = useState<Theme>(
    () => (localStorage.getItem("sp-theme") as Theme) || "system",
  );
  const [system, setSystem] = useState<"light" | "dark">(() =>
    matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light",
  );
  const resolved = theme === "system" ? system : theme;
  useEffect(() => {
    const media = matchMedia("(prefers-color-scheme: dark)");
    const handler = () => setSystem(media.matches ? "dark" : "light");
    media.addEventListener("change", handler);
    return () => media.removeEventListener("change", handler);
  }, []);
  useEffect(() => {
    localStorage.setItem("sp-theme", theme);
    document.documentElement.dataset.theme = resolved;
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", resolved === "dark" ? "#0c1118" : "#f7f8fa");
  }, [theme, resolved]);
  return (
    <Context.Provider value={{ theme, resolved, setTheme }}>
      {children}
    </Context.Provider>
  );
}
export const useTheme = () => useContext(Context);
