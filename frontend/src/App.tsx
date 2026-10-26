import { lazy, Suspense, useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";
import * as Dropdown from "@radix-ui/react-dropdown-menu";
import {
  Activity,
  ArrowDownLeft,
  ArrowRight,
  Bell,
  BookOpen,
  Check,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Command,
  Inbox,
  LayoutDashboard,
  Menu,
  Monitor,
  Moon,
  PanelLeftClose,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  Sun,
  Unplug,
  X,
  Zap,
} from "lucide-react";
import { api, configureSession, post, selectWorkspace } from "./lib/api";
import {
  previewActions,
  previewConnections,
  previewDocuments,
  previewRuns,
  previewSession,
  previewTickets,
} from "./lib/fixtures";
import type {
  Action,
  Connection,
  Document,
  Page,
  Run,
  Session,
  Ticket,
} from "./lib/types";
import { WorkspaceContext } from "./lib/workspace";
import { useCollection } from "./lib/useCollection";
import { Avatar, Loading, Logo, Modal } from "./components/ui";
import { useTheme } from "./components/ThemeProvider";
import Overview from "./features/Overview";

const InboxPage = lazy(() => import("./features/InboxPage"));
const ChatPage = lazy(() => import("./features/ChatPage"));
const KnowledgePage = lazy(() => import("./features/KnowledgePage"));
const ConnectionsPage = lazy(() => import("./features/ConnectionsPage"));
const ApprovalsPage = lazy(() => import("./features/ApprovalsPage"));
const RunsPage = lazy(() => import("./features/RunsPage"));
const SettingsPage = lazy(() => import("./features/SettingsPage"));
const Login = lazy(() => import("./features/Login"));

const nav = [
  { path: "", label: "Overview", icon: LayoutDashboard },
  { path: "/inbox", label: "Inbox", icon: Inbox },
  { path: "/chat", label: "Agent chat", icon: Sparkles },
  { path: "/knowledge", label: "Knowledge base", icon: BookOpen },
  { path: "/connections", label: "Connections", icon: Unplug },
  { path: "/approvals", label: "Approvals", icon: ShieldCheck },
  { path: "/runs", label: "Activity & runs", icon: Activity },
];

export default function App() {
  const preview = useLocation().pathname.startsWith("/preview");
  const query = useQuery({
    queryKey: ["session"],
    queryFn: () => api<Session>("/auth/me"),
    enabled: !preview,
    retry: false,
  });
  if (preview) return <Workspace session={previewSession} preview />;
  if (query.isPending) return <Loading />;
  if (!query.data)
    return (
      <Suspense fallback={<Loading />}>
        <Login />
      </Suspense>
    );
  configureSession(query.data.csrf_token);
  return <Workspace session={query.data} preview={false} />;
}

function Workspace({
  session,
  preview,
}: {
  session: Session;
  preview: boolean;
}) {
  const { theme, resolved, setTheme } = useTheme();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const location = useLocation();
  const base = preview ? "/preview" : "";
  const [collapsed, setCollapsed] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);
  const [searchTerm, setSearchTerm] = useState("");
  const [toast, setToast] = useState<{ message: string; kind: string } | null>(
    null,
  );
  const [graphics, setGraphicsState] = useState(
    () => localStorage.getItem("sp-graphics") !== "false",
  );
  const [localActions, setLocalActions] = useState(previewActions);
  const [localRuns, setLocalRuns] = useState(previewRuns);
  const [workspaceId, setWorkspaceId] = useState(() => {
    const stored = localStorage.getItem("sp-workspace");
    const valid =
      session.workspaces.find((w) => w.id === stored)?.id ||
      session.workspaces[0]?.id ||
      "";
    if (!preview) selectWorkspace(valid);
    return valid;
  });
  const workspace =
    session.workspaces.find((w) => w.id === workspaceId) ||
    session.workspaces[0];
  const ticketsQ = useCollection<Ticket>(
    "tickets",
    workspaceId,
    !preview,
    15000,
  );
  const runsQ = useCollection<Run>("runs", workspaceId, !preview, 5000);
  const actionsQ = useCollection<Action>(
    "approvals",
    workspaceId,
    !preview,
    5000,
  );
  const docsQ = useCollection<Document>(
    "documents",
    workspaceId,
    !preview,
    10000,
  );
  const connectionsQ = useQuery({
    queryKey: ["connections", workspaceId],
    queryFn: () => api<Page<Connection>>("/connections"),
    enabled: !preview,
  });
  const tickets = preview ? previewTickets : ticketsQ.data?.items || [];
  const runs = preview ? localRuns : runsQ.data?.items || [];
  const actions = preview ? localActions : actionsQ.data?.items || [];
  const documents = preview ? previewDocuments : docsQ.data?.items || [];
  const connections = preview
    ? previewConnections
    : connectionsQ.data?.items || [];
  const pending = actions.filter((a) => a.status === "pending").length;
  const collections = {
    tickets: ticketsQ,
    runs: runsQ,
    approvals: actionsQ,
    documents: docsQ,
  };
  const pagination = Object.fromEntries(
    Object.entries(collections).map(([key, query]) => [
      key,
      {
        more: !preview && !!query.hasNextPage,
        loading: query.isFetchingNextPage,
        load: () => {
          void query.fetchNextPage();
        },
      },
    ]),
  ) as import("./lib/workspace").WorkspaceData["pagination"];
  const page =
    nav.find((n) => n.path && location.pathname.startsWith(base + n.path))
      ?.label ||
    (location.pathname.endsWith("/settings") ? "Settings" : "Overview");
  const notify = (message: string, kind = "success") =>
    setToast({ message, kind });
  const refresh = () => {
    void queryClient.invalidateQueries({
      predicate: (q) => q.queryKey[0] !== "session",
    });
  };
  useEffect(() => {
    if (!toast) return;
    const timeout = setTimeout(() => setToast(null), 5000);
    return () => clearTimeout(timeout);
  }, [toast]);
  useEffect(() => {
    setMobileNav(false);
  }, [location.pathname]);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
      if (
        e.key === "n" &&
        !(e.target instanceof HTMLInputElement) &&
        !(e.target instanceof HTMLTextAreaElement)
      )
        navigate(base + "/chat");
    };
    document.addEventListener("keydown", handler);
    return () => document.removeEventListener("keydown", handler);
  }, [base, navigate]);
  const setGraphics = (value: boolean) => {
    localStorage.setItem("sp-graphics", String(value));
    setGraphicsState(value);
  };
  const decide = async (
    action: Action,
    decision: "approve" | "reject" | "edit",
    args?: Record<string, string | number>,
  ) => {
    if (preview) {
      setLocalActions((previous) =>
        previous.map((a) =>
          a.id === action.id
            ? {
                ...a,
                status:
                  decision === "edit"
                    ? "pending"
                    : decision === "approve"
                      ? "approved"
                      : "rejected",
                version: decision === "edit" ? a.version + 1 : a.version,
                arguments: args || a.arguments,
              }
            : a,
        ),
      );
      notify(
        `Preview: ${decision === "edit" ? "draft updated" : decision === "approve" ? "action approved" : "action rejected"}. No external action was performed.`,
      );
    } else {
      await post("/approvals/" + action.id + "/decide", {
        decision,
        version: action.version,
        arguments: args,
      });
      refresh();
      notify(
        decision === "approve"
          ? "Approved. Your pilot will revalidate before executing."
          : decision === "edit"
            ? "Revised draft saved. Review and approve the new version."
            : "Action rejected. Nothing will be sent.",
      );
    }
  };
  const startRun = async (prompt: string, ticketId?: string): Promise<Run> => {
    if (preview) {
      const run: Run = {
        id: crypto.randomUUID(),
        prompt,
        status: "completed",
        current_node: "summarize",
        result:
          "This is the interactive frontend preview. In the connected application, your agent searches your workspace knowledge and prepares actions for your approval. No provider was called.",
        error: null,
        citations: [],
        created_at: Date.now() / 1000,
        updated_at: Date.now() / 1000,
        ticket_id: ticketId || null,
      };
      setLocalRuns((previous) => [run, ...previous]);
      return run;
    }
    const run = await post<Run>(
      "/runs",
      { prompt, ticket_id: ticketId || null },
      crypto.randomUUID(),
    );
    refresh();
    return run;
  };
  const error =
    [ticketsQ, runsQ, docsQ, actionsQ, connectionsQ].find((q) => q.isError)
      ?.error?.message || "";
  return (
    <WorkspaceContext.Provider
      value={{
        session,
        preview,
        role: workspace?.role || "agent",
        tickets,
        runs,
        actions,
        documents,
        connections,
        pagination,
        loading: !preview && ticketsQ.isPending,
        error,
        graphics,
        setGraphics,
        refresh,
        notify,
        decide,
        startRun,
      }}
    >
      <a className="skip-link" href="#main-content">
        Skip to main content
      </a>
      <div
        className={`app-shell ${collapsed ? "sidebar-collapsed" : ""} ${mobileNav ? "nav-open" : ""}`}
      >
        {mobileNav && (
          <button
            className="sidebar-scrim"
            aria-label="Close navigation"
            onClick={() => setMobileNav(false)}
          />
        )}
        <aside className="sidebar">
          <div className="sidebar-brand">
            <Link to={base || "/"} aria-label="SupportPilot home">
              <Logo small={collapsed} />
            </Link>
            <button
              className="icon-button sidebar-collapse"
              aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
              onClick={() => setCollapsed((v) => !v)}
            >
              <PanelLeftClose size={16} />
            </button>
          </div>
          <Dropdown.Root>
            <Dropdown.Trigger
              className="workspace-switcher"
              aria-label={`Current workspace: ${workspace?.name}`}
            >
              <span className="workspace-avatar">
                {workspace?.name.slice(0, 1)}
              </span>
              <span className="workspace-name">
                <strong>{workspace?.name}</strong>
                <small>Team workspace</small>
              </span>
              <ChevronDown size={14} />
            </Dropdown.Trigger>
            <Dropdown.Portal>
              <Dropdown.Content className="dropdown" sideOffset={6}>
                {session.workspaces.map((w) => (
                  <Dropdown.Item
                    className="dropdown-item"
                    key={w.id}
                    onSelect={() => {
                      setWorkspaceId(w.id);
                      selectWorkspace(w.id);
                      queryClient.clear();
                      navigate(base || "/");
                    }}
                  >
                    {w.name}
                    {w.id === workspaceId && <Check size={14} />}
                  </Dropdown.Item>
                ))}
              </Dropdown.Content>
            </Dropdown.Portal>
          </Dropdown.Root>
          <div className="nav-section-label">WORKSPACE</div>
          <nav aria-label="Main navigation">
            {nav.map(({ path, label, icon: Icon }) => (
              <NavLink
                key={path}
                to={base + path || "/"}
                end={!path}
                aria-label={label}
                className={({ isActive }) =>
                  `nav-item ${isActive ? "active" : ""}`
                }
                title={collapsed ? label : undefined}
              >
                <Icon size={18} />
                <span>{label}</span>
                {path === "/approvals" && pending > 0 && (
                  <span className="nav-count">{pending}</span>
                )}
                {path === "/chat" && <span className="nav-spark">✦</span>}
              </NavLink>
            ))}
          </nav>
          <div className="sidebar-bottom">
            <div className="pilot-status-card">
              <div className="pilot-status-title">
                <span className="pilot-status-icon">
                  <Zap size={14} />
                </span>
                <strong>Your pilot is on standby</strong>
                <span className="small-live-dot" />
              </div>
              <p>
                Less on your plate.
                <br />
                More room for what matters.
              </p>
              <button onClick={() => navigate(base + "/chat")}>
                Put your pilot to work
                <ArrowUpRightIcon />
              </button>
            </div>
            <NavLink
              className="nav-item"
              to={base + "/settings"}
              aria-label="Settings"
            >
              <Settings2 size={18} />
              <span>Settings</span>
            </NavLink>
            <button
              className="nav-item nav-help"
              aria-label="Help and getting started"
              onClick={() =>
                notify(
                  "Start in Connections, add product documents in Knowledge, then create a task. The repository FILE_GUIDE.md explains the complete architecture.",
                )
              }
            >
              <CircleHelp size={18} />
              <span>Help & getting started</span>
              <ArrowDownLeft size={13} />
            </button>
            <div className="sidebar-user">
              <Avatar name={session.user.name} />
              <span>
                <strong>{session.user.name}</strong>
                <small>
                  {workspace?.role === "owner"
                    ? "Workspace owner"
                    : "Support agent"}
                </small>
              </span>
              <Dropdown.Root>
                <Dropdown.Trigger
                  className="icon-button"
                  aria-label="Account menu"
                >
                  <ChevronDown size={14} />
                </Dropdown.Trigger>
                <Dropdown.Portal>
                  <Dropdown.Content className="dropdown" sideOffset={8}>
                    <Dropdown.Item
                      className="dropdown-item"
                      onSelect={() => navigate(base + "/settings")}
                    >
                      Account settings
                    </Dropdown.Item>
                    <Dropdown.Item
                      className="dropdown-item"
                      onSelect={async () => {
                        if (preview) {
                          navigate("/");
                          return;
                        }
                        await post("/auth/logout", {});
                        queryClient.clear();
                        window.location.assign("/");
                      }}
                    >
                      Sign out
                    </Dropdown.Item>
                  </Dropdown.Content>
                </Dropdown.Portal>
              </Dropdown.Root>
            </div>
          </div>
        </aside>
        <div className="app-body">
          <header className="topbar">
            <div className="breadcrumbs">
              <button
                className="icon-button mobile-menu"
                onClick={() => setMobileNav(true)}
                aria-label="Open navigation"
              >
                <Menu size={19} />
              </button>
              <LayoutDashboard size={14} />
              <span>Workspace</span>
              <ChevronRight size={12} />
              <strong>{page}</strong>
            </div>
            <div className="topbar-right">
              <button
                className="search-trigger"
                aria-label="Search workspace"
                onClick={() => setSearchOpen(true)}
              >
                <Search size={14} />
                <span>Search anything…</span>
                <kbd>
                  <Command size={10} /> K
                </kbd>
              </button>
              <div className="topbar-divider" />
              <Dropdown.Root>
                <Dropdown.Trigger
                  className="icon-button theme-toggle"
                  aria-label="Change theme"
                >
                  {resolved === "dark" ? <Moon size={17} /> : <Sun size={17} />}
                </Dropdown.Trigger>
                <Dropdown.Portal>
                  <Dropdown.Content
                    className="dropdown"
                    align="end"
                    sideOffset={8}
                  >
                    {(
                      [
                        { id: "light", label: "Light theme", icon: Sun },
                        { id: "dark", label: "Dark theme", icon: Moon },
                        {
                          id: "system",
                          label: "Use system theme",
                          icon: Monitor,
                        },
                      ] as const
                    ).map((t) => (
                      <Dropdown.Item
                        className="dropdown-item"
                        key={t.id}
                        onSelect={() => setTheme(t.id)}
                      >
                        <t.icon size={15} />
                        {t.label}
                        {theme === t.id && <Check size={14} />}
                      </Dropdown.Item>
                    ))}
                  </Dropdown.Content>
                </Dropdown.Portal>
              </Dropdown.Root>
              <button
                className="icon-button notification-button"
                aria-label={`${pending} pending approvals`}
                onClick={() => navigate(base + "/approvals")}
              >
                <Bell size={17} />
                {pending > 0 && <i />}
              </button>
              <Avatar name={session.user.name} size="small" />
            </div>
          </header>
          {(preview || session.demo_mode) && (
            <div className="demo-ribbon">
              <span>
                <span className="demo-pill">
                  {preview ? "DESIGN PREVIEW" : "DEMO MODE"}
                </span>
                {preview
                  ? "Explore both themes, the 3D scene, and every screen. All data is illustrative."
                  : "Local sample workspace. Provider actions and embeddings are simulated."}
              </span>
              <button
                onClick={() => setTheme(resolved === "dark" ? "light" : "dark")}
              >
                {resolved === "dark" ? <Sun size={12} /> : <Moon size={12} />}
                Try {resolved === "dark" ? "light" : "dark"} theme
                <ArrowRight size={12} />
              </button>
            </div>
          )}
          <main id="main-content" className="main-content">
            {error && (
              <div className="error-banner">
                {error}
                <button onClick={refresh}>Retry</button>
              </div>
            )}
            <Suspense fallback={<Loading />}>
              <Routes>
                <Route path={base || "/"} element={<Overview />} />
                <Route path={base + "/inbox"} element={<InboxPage />} />
                <Route path={base + "/chat"} element={<ChatPage />} />
                <Route path={base + "/knowledge"} element={<KnowledgePage />} />
                <Route
                  path={base + "/connections"}
                  element={<ConnectionsPage />}
                />
                <Route path={base + "/approvals"} element={<ApprovalsPage />} />
                <Route path={base + "/runs"} element={<RunsPage />} />
                <Route path={base + "/runs/:runId"} element={<RunsPage />} />
                <Route path={base + "/settings"} element={<SettingsPage />} />
                <Route path="*" element={<Overview />} />
              </Routes>
            </Suspense>
          </main>
        </div>
      </div>
      <Modal
        open={searchOpen}
        onOpenChange={setSearchOpen}
        title="Find your next step"
        description="Search workspace tickets, tasks, and documents."
      >
        <div className="search-input-wrap">
          <Search size={18} />
          <input
            autoFocus
            placeholder="Search tickets, tasks, documents…"
            value={searchTerm}
            onChange={(e) => setSearchTerm(e.target.value)}
          />
        </div>
        <div className="search-results">
          {[
            ...tickets.map((t) => ({
              label: t.subject,
              type: "Ticket",
              path: "/inbox?ticket=" + t.id,
            })),
            ...runs.map((r) => ({
              label: r.prompt,
              type: "Run",
              path: "/runs/" + r.id,
            })),
            ...documents.map((d) => ({
              label: d.name,
              type: "Document",
              path: "/knowledge",
            })),
          ]
            .filter((item) =>
              item.label.toLowerCase().includes(searchTerm.toLowerCase()),
            )
            .slice(0, 8)
            .map((item, i) => (
              <button
                key={i}
                onClick={() => {
                  navigate(base + item.path);
                  setSearchOpen(false);
                }}
              >
                <Search size={14} />
                <span>
                  {item.label}
                  <small>{item.type}</small>
                </span>
                <ArrowRight size={15} />
              </button>
            ))}
        </div>
      </Modal>
      {toast && (
        <div
          className={`toast ${toast.kind === "error" ? "toast-error" : ""}`}
          role="status"
        >
          <span className="toast-icon">
            {toast.kind === "error" ? <X size={17} /> : <Check size={17} />}
          </span>
          <span>{toast.message}</span>
          <button
            className="icon-button"
            onClick={() => setToast(null)}
            aria-label="Dismiss notification"
          >
            <X size={14} />
          </button>
        </div>
      )}
    </WorkspaceContext.Provider>
  );
}
function ArrowUpRightIcon() {
  return (
    <svg width="13" height="13" viewBox="0 0 20 20" fill="none">
      <path d="M5 15 15 5M5 5h10v10" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}
