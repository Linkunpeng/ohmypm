import { FolderGit2, LayoutDashboard, Menu, Monitor, Moon, Search, Sun, UserRound, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { NavLink, useMatch, useNavigate } from "react-router";

import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { useAuthor, useProjects } from "@/lib/hooks";
import { useTheme, type ThemeChoice } from "@/lib/theme";
import { cn } from "@/lib/utils";

function ThemeSwitch() {
  const { choice, setChoice } = useTheme();
  const options: { value: ThemeChoice; label: string; icon: ReactNode }[] = [
    { value: "light", label: "Light", icon: <Sun className="size-3.5" /> },
    { value: "dark", label: "Dark", icon: <Moon className="size-3.5" /> },
    { value: "system", label: "System", icon: <Monitor className="size-3.5" /> },
  ];
  return (
    <div role="radiogroup" aria-label="Color theme" className="flex rounded-md border border-sidebar-border p-0.5">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={choice === o.value}
          title={o.label}
          onClick={() => setChoice(o.value)}
          className={cn(
            "flex flex-1 items-center justify-center gap-1 rounded px-2 py-1 text-xs text-muted-foreground",
            choice === o.value && "bg-card text-foreground shadow-xs",
          )}
        >
          {o.icon}
          <span className="sr-only sm:not-sr-only">{o.label}</span>
        </button>
      ))}
    </div>
  );
}

function AuthorSetting() {
  const [author, setAuthor] = useAuthor();
  const [draft, setDraft] = useState(author);
  return (
    <Popover onOpenChange={(open) => open && setDraft(author)}>
      <PopoverTrigger className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs text-muted-foreground hover:bg-sidebar-accent">
        <UserRound className="size-3.5" aria-hidden />
        <span className="truncate">
          Recording as <span className="text-foreground">{author}</span>
        </span>
      </PopoverTrigger>
      <PopoverContent side="top" align="start" className="w-64">
        <form
          onSubmit={(e) => {
            e.preventDefault();
            if (draft.trim()) setAuthor(draft.trim());
          }}
          className="space-y-2"
        >
          <label htmlFor="author-name" className="text-sm font-medium">
            Your name on new records
          </label>
          <Input id="author-name" value={draft} onChange={(e) => setDraft(e.target.value)} maxLength={200} />
          <p className="text-xs text-muted-foreground">Saved in this browser only.</p>
        </form>
      </PopoverContent>
    </Popover>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { data: projects, isLoading } = useProjects();
  const projectId = useMatch("/projects/:projectId/*")?.params.projectId;
  const navigate = useNavigate();
  const [query, setQuery] = useState("");

  const navClass = ({ isActive }: { isActive: boolean }) =>
    cn(
      "flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-sidebar-foreground/80 hover:bg-sidebar-accent",
      isActive && "bg-sidebar-accent font-medium text-sidebar-foreground",
    );

  return (
    <div className="flex h-full flex-col gap-4 p-3">
      <NavLink to="/" onClick={onNavigate} className="flex items-center gap-2 px-2 pt-1">
        <img src="/favicon.svg" alt="" className="size-6" />
        <span className="text-[1.05rem] font-semibold tracking-tight">ohmypm</span>
      </NavLink>

      <form
        role="search"
        onSubmit={(e) => {
          e.preventDefault();
          if (!query.trim()) return;
          navigate(`/search?q=${encodeURIComponent(query.trim())}${projectId ? `&project=${projectId}` : ""}`);
          onNavigate?.();
        }}
      >
        <label htmlFor="sidebar-search" className="sr-only">
          Search records
        </label>
        <div className="relative">
          <Search className="pointer-events-none absolute top-1/2 left-2.5 size-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            id="sidebar-search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder={projectId ? "Search this project" : "Search all records"}
            className="h-8 bg-card pl-8 text-sm"
          />
        </div>
      </form>

      <nav className="space-y-0.5" aria-label="Main">
        <NavLink to="/" end className={navClass} onClick={onNavigate}>
          <LayoutDashboard className="size-4" aria-hidden /> Overview
        </NavLink>
        <NavLink to="/search" className={navClass} onClick={onNavigate}>
          <Search className="size-4" aria-hidden /> Search
        </NavLink>
      </nav>

      <div className="min-h-0 flex-1 overflow-y-auto">
        <h2 className="px-2 pb-1 text-xs font-medium text-muted-foreground">Projects</h2>
        {isLoading && <p className="px-2 text-sm text-muted-foreground">Loading…</p>}
        {projects?.length === 0 && (
          <p className="px-2 text-sm text-muted-foreground">
            Register one with <code className="font-mono text-xs">ohmypm register</code>.
          </p>
        )}
        <ul className="space-y-0.5">
          {projects?.map((p) => (
            <li key={p.id}>
              <NavLink to={`/projects/${p.id}`} className={navClass} onClick={onNavigate} title={p.root_path}>
                <FolderGit2 className="size-4 shrink-0 text-muted-foreground" aria-hidden />
                <span className="min-w-0 flex-1 truncate">{p.name}</span>
                <span className="tabular text-xs text-muted-foreground">{p.entry_count}</span>
              </NavLink>
            </li>
          ))}
        </ul>
      </div>

      <div className="space-y-2 border-t border-sidebar-border pt-3">
        <AuthorSetting />
        <ThemeSwitch />
      </div>
    </div>
  );
}

export function AppShell({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="flex min-h-svh">
      <aside className="sticky top-0 hidden h-svh w-64 shrink-0 border-r border-sidebar-border bg-sidebar md:block">
        <Sidebar />
      </aside>
      {open && (
        <div className="fixed inset-0 z-40 md:hidden" role="dialog" aria-modal="true" aria-label="Navigation">
          <div className="absolute inset-0 bg-black/30" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-72 bg-sidebar shadow-lg">
            <button
              type="button"
              className="absolute top-3 right-3 rounded p-1 hover:bg-sidebar-accent"
              onClick={() => setOpen(false)}
              aria-label="Close navigation"
            >
              <X className="size-4" />
            </button>
            <Sidebar onNavigate={() => setOpen(false)} />
          </aside>
        </div>
      )}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-2 border-b border-border px-4 py-2 md:hidden">
          <button
            type="button"
            onClick={() => setOpen(true)}
            className="rounded p-1.5 hover:bg-accent"
            aria-label="Open navigation"
          >
            <Menu className="size-5" />
          </button>
          <span className="font-semibold">ohmypm</span>
        </header>
        <main className="flex-1 px-4 py-6 sm:px-8 lg:px-12">{children}</main>
      </div>
    </div>
  );
}
