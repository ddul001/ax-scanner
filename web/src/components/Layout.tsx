import { Link, NavLink, Outlet } from "react-router-dom";
import { Moon, ScanSearch, Sun } from "lucide-react";
import { useTheme } from "@/lib/theme";
import { Button } from "@/components/ui/button";

function navClass({ isActive }: { isActive: boolean }) {
  return `rounded-md px-2 py-1.5 sm:px-3 ${isActive ? "bg-muted font-medium" : "text-muted-foreground hover:text-foreground"}`;
}

export default function Layout() {
  const { dark, toggle } = useTheme();
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-10 border-b bg-background/85 backdrop-blur">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between px-4 sm:px-6">
          <Link to="/" aria-label="AX Scanner home" className="flex shrink-0 items-center gap-2 font-semibold tracking-tight">
            <span className="grid size-7 place-items-center rounded-md bg-primary text-primary-foreground"><ScanSearch className="size-4" /></span>
            <span className="hidden sm:inline">AX Scanner</span>
          </Link>
          <nav className="flex min-w-0 items-center gap-0.5 text-sm sm:gap-1">
            <NavLink to="/" end className={navClass}>Scan</NavLink>
            <NavLink to="/history" className={navClass}>History</NavLink>
            <NavLink to="/leaderboard" className={navClass}>Leaderboard</NavLink>
            <Button variant="ghost" size="icon" onClick={toggle} aria-label={dark ? "Switch to light theme" : "Switch to dark theme"}>
              {dark ? <Sun /> : <Moon />}
            </Button>
          </nav>
        </div>
      </header>
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6"><Outlet /></main>
      <footer className="border-t py-6 text-center text-xs text-muted-foreground">
        <p>
          Built with Meta Model API · Muse Spark by{" "}
          <a href="https://aivexia.ro" target="_blank" rel="noopener" className="font-medium underline underline-offset-2 hover:text-foreground">Aivexia Tech</a>
          {" "}· v0.1
        </p>
      </footer>
    </div>
  );
}
