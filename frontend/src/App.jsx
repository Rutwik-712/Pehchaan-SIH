import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArchiveTrayIcon,
  Bell,
  CaretDown,
  CheckCircle,
  ClockCounterClockwise,
  FileText,
  FolderOpen,
  Graph,
  ListMagnifyingGlass,
  MapPin,
  MagnifyingGlass,
  Scan,
  ShieldCheck,
  SignIn,
  SignOut,
  SpinnerGap,
  UserCircle,
  Warning,
} from "@phosphor-icons/react";
import { clearStoredSession, getCases, getCurrentUser, hasStoredSession, login, logout } from "./api.js";
import { EvidenceIntake, ExtractionReview, Overview, PatternAlerts, TimelineView } from "./LiveScreens.jsx";
import { CaseBrief, EvidenceAssistant } from "./Phase8Screens.jsx";
import { can, LoadingPanel, SectionHeader, StatusPill } from "./ui.jsx";

const GraphWorkspace = lazy(() => import("./GraphWorkspace.jsx"));

const workflow = [
  { id: "overview", index: "00", label: "Case overview", icon: FolderOpen },
  { id: "intake", index: "01", label: "Evidence intake", icon: ArchiveTrayIcon },
  { id: "review", index: "02", label: "Extraction review", icon: Scan, permission: "entity:review" },
  { id: "graph", index: "03", label: "Network graph", icon: Graph },
  { id: "timeline", index: "04", label: "Event timeline", icon: ClockCounterClockwise },
  { id: "alerts", index: "05", label: "Pattern alerts", icon: Warning, permission: "analytics:run" },
  { id: "assistant", index: "06", label: "Evidence assistant", icon: ListMagnifyingGlass, permission: "assistant:query" },
  { id: "brief", index: "07", label: "Case brief", icon: FileText, permission: "brief:draft" },
];

const roleLabels = { constable: "Constable", investigator: "Investigator", sp: "SP-level" };

function canOpenView(user, view) {
  return !view.permission || can(user, view.permission);
}

function LoginScreen({ onLogin, busy, error }) {
  const [username, setUsername] = useState("investigator.demo");
  const [password, setPassword] = useState("");
  return <main className="login-shell"><section className="login-brand-panel"><div className="brand-block login-brand"><span className="brand-mark"><Graph size={24} weight="bold" /></span><div><strong>PEHCHAAN</strong><small>CONNECTING CLUES</small></div></div><div className="login-brand-copy"><p className="eyebrow">Restricted investigation system</p><h1>Source-backed network analysis, protected by case-level access.</h1><p>Phase 8 connects the complete offline workflow, including the cited evidence assistant, immutable case briefs, Celery visibility, PostgreSQL, MinIO, Splink and Neo4j.</p></div><div className="login-security-note"><ShieldCheck size={20} weight="duotone" /><span><strong>Backend-enforced access</strong><small>Rotating sessions · role permissions · assigned cases · audited actions</small></span></div></section><section className="login-form-panel"><form className="login-card" onSubmit={(event) => { event.preventDefault(); onLogin(username, password); }}><div className="login-card-icon"><ShieldCheck size={28} weight="duotone" /></div><p className="eyebrow">Authorized personnel only</p><h2>Sign in to the live workspace</h2><label><span>Username</span><input autoComplete="username" value={username} onChange={(event) => setUsername(event.target.value)} /></label><label><span>Password</span><input autoComplete="current-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} /></label>{error && <div className="login-error" role="alert"><Warning size={16} /> {error}</div>}<button className="button button--yellow button--wide" type="submit" disabled={busy || !username || !password}>{busy ? <><SpinnerGap className="spin" size={18} /> Verifying credentials…</> : <><SignIn size={18} /> Sign in securely</>}</button><div className="demo-accounts"><span>Local demo accounts</span>{["constable.demo", "investigator.demo", "sp.demo"].map((account) => <button type="button" key={account} onClick={() => setUsername(account)}>{account}</button>)}<small>Common demo password: <code>SIH1@2026</code></small></div></form></section></main>;
}

function SessionLoading() {
  return <main className="session-loading"><SpinnerGap className="spin" size={28} /><strong>Verifying protected session…</strong></main>;
}

function CasePicker({ cases, activeCase, onSelect }) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const pickerRef = useRef(null);
  const normalizedQuery = query.trim().toLowerCase();
  const filteredCases = useMemo(() => cases.filter((item) => !normalizedQuery || [item.id, item.title, item.jurisdiction].some((value) => String(value || "").toLowerCase().includes(normalizedQuery))), [cases, normalizedQuery]);

  useEffect(() => {
    const closeOnOutsideClick = (event) => { if (!pickerRef.current?.contains(event.target)) setOpen(false); };
    document.addEventListener("mousedown", closeOnOutsideClick);
    return () => document.removeEventListener("mousedown", closeOnOutsideClick);
  }, []);

  const choose = (caseId) => {
    onSelect(caseId);
    setQuery("");
    setOpen(false);
  };

  return <div className={`case-picker ${open ? "case-picker--open" : ""}`} ref={pickerRef}>
    <div className="case-picker__search">
      <MagnifyingGlass size={14} />
      <input
        aria-label="Search and select active case"
        aria-controls="authorized-case-options"
        aria-expanded={open}
        autoComplete="off"
        placeholder={`Search · ${activeCase.id}`}
        value={query}
        onFocus={() => setOpen(true)}
        onChange={(event) => { setQuery(event.target.value); setOpen(true); }}
        onKeyDown={(event) => {
          if (event.key === "Escape") setOpen(false);
          if (event.key === "Enter" && filteredCases.length) { event.preventDefault(); choose(filteredCases[0].id); }
        }}
      />
      <button type="button" aria-label={open ? "Close case options" : "Open case options"} onClick={() => setOpen((value) => !value)}><CaretDown size={13} /></button>
    </div>
    {open && <div className="case-picker__options" id="authorized-case-options" role="listbox" aria-label="Authorized cases">
      {filteredCases.length ? filteredCases.map((item) => <button type="button" role="option" aria-selected={item.id === activeCase.id} className={item.id === activeCase.id ? "active" : ""} key={item.id} onClick={() => choose(item.id)}><strong>{item.id}</strong><span>{item.title}</span><small>{item.jurisdiction}</small></button>) : <p>No authorized case matches “{query}”.</p>}
    </div>}
  </div>;
}

export function App() {
  const [activeView, setActiveView] = useState("overview");
  const [toast, setToast] = useState(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [authState, setAuthState] = useState({ status: "loading", user: null, error: "" });
  const [authorizedCases, setAuthorizedCases] = useState([]);
  const [activeCaseId, setActiveCaseId] = useState("");
  const [dataRevision, setDataRevision] = useState(0);
  const [lastSync, setLastSync] = useState(new Date());
  const activeStep = useMemo(() => workflow.find((step) => step.id === activeView), [activeView]);
  const activeCase = useMemo(() => authorizedCases.find((item) => item.id === activeCaseId) || authorizedCases[0], [authorizedCases, activeCaseId]);

  const establishSession = useCallback((user, cases) => {
    setAuthorizedCases(cases);
    setActiveCaseId((current) => cases.some((item) => item.id === current) ? current : cases[0]?.id || "");
    setAuthState({ status: "signed-in", user, error: "" });
  }, []);

  useEffect(() => {
    if (!hasStoredSession()) { setAuthState({ status: "signed-out", user: null, error: "" }); return; }
    Promise.all([getCurrentUser(), getCases()]).then(([user, cases]) => establishSession(user, cases)).catch(() => { clearStoredSession(); setAuthState({ status: "signed-out", user: null, error: "Your session expired. Please sign in again." }); });
  }, [establishSession]);

  const showToast = useCallback((message, tone = "success") => {
    setToast({ message, tone });
    window.setTimeout(() => setToast(null), 3600);
  }, []);
  const dataChanged = useCallback(() => { setDataRevision((value) => value + 1); setLastSync(new Date()); }, []);

  const navigate = (id) => {
    const target = workflow.find((step) => step.id === id);
    if (!target || !canOpenView(authState.user, target)) { showToast(`${roleLabels[authState.user.role]} access does not include ${target?.label.toLowerCase() || "this view"}.`, "error"); return; }
    setActiveView(id); setSidebarOpen(false); window.scrollTo({ top: 0, behavior: "smooth" });
  };

  const handleLogin = async (username, password) => {
    setAuthState({ status: "authenticating", user: null, error: "" });
    try { const user = await login(username.trim().toLowerCase(), password); const cases = await getCases(); establishSession(user, cases); }
    catch (error) { clearStoredSession(); setAuthState({ status: "signed-out", user: null, error: error.message || "Sign-in failed" }); }
  };
  const handleLogout = async () => { await logout(); setActiveView("overview"); setAuthorizedCases([]); setActiveCaseId(""); setAuthState({ status: "signed-out", user: null, error: "" }); };
  const selectCase = (caseId) => { setActiveCaseId(caseId); setActiveView("overview"); setDataRevision((value) => value + 1); };

  if (authState.status === "loading") return <SessionLoading />;
  if (authState.status !== "signed-in") return <LoginScreen onLogin={handleLogin} busy={authState.status === "authenticating"} error={authState.error} />;
  if (!activeCase) return <main className="session-loading"><Warning size={28} /><strong>No authorized active case is assigned to this account.</strong><button className="button button--dark" onClick={handleLogout}>Sign out</button></main>;

  const common = { caseRecord: activeCase, user: authState.user, showToast, onDataChanged: dataChanged };
  const screens = {
    overview: <Overview {...common} onNavigate={navigate} refreshToken={dataRevision} />,
    intake: <EvidenceIntake {...common} />,
    review: <ExtractionReview {...common} />,
    graph: <Suspense fallback={<LoadingPanel label="Loading the graph workspace…" />}><GraphWorkspace {...common} /></Suspense>,
    timeline: <TimelineView {...common} />,
    alerts: <PatternAlerts {...common} />,
    assistant: <EvidenceAssistant {...common} />,
    brief: <CaseBrief {...common} />,
  };

  return <div className="app-shell"><aside id="workflow-sidebar" className={`sidebar ${sidebarOpen ? "sidebar--open" : ""}`}><div className="brand-block"><span className="brand-mark"><Graph size={24} weight="bold" /></span><div><strong>PEHCHAAN</strong><small>CONNECTING CLUES</small></div></div><div className="case-mini-card"><span className="case-mini-label">ACTIVE AUTHORIZED CASE</span>{authorizedCases.length > 1 ? <CasePicker cases={authorizedCases} activeCase={activeCase} onSelect={selectCase} /> : <strong>{activeCase.id}</strong>}<p>{activeCase.title}</p><span><MapPin size={13} /> {activeCase.jurisdiction}</span></div><nav className="workflow-nav" aria-label="Investigation workflow"><p>LIVE WORKFLOW</p>{workflow.filter((step) => canOpenView(authState.user, step)).map((step) => { const Icon = step.icon; return <button key={step.id} className={activeView === step.id ? "active" : ""} onClick={() => navigate(step.id)}><span className="nav-index">{step.index}</span><Icon size={18} /><span>{step.label}{step.preview && <small>PHASE 8</small>}</span>{activeView === step.id && <i />}</button>; })}</nav><div className="sidebar-footer"><ShieldCheck size={20} weight="duotone" /><div><strong>{roleLabels[authState.user.role]} access</strong><span>{authorizedCases.length} authorized case{authorizedCases.length === 1 ? "" : "s"}</span></div></div></aside><div className="app-main"><header className="topbar"><button className="mobile-menu" onClick={() => setSidebarOpen((value) => !value)} aria-label="Toggle navigation" aria-controls="workflow-sidebar" aria-expanded={sidebarOpen}><span /><span /><span /></button><div className="breadcrumb"><span>{activeStep?.index}</span><strong>{activeStep?.label}</strong></div><div className="topbar-status"><span className="classification"><ShieldCheck size={14} /> {activeCase.classification}</span><span className="last-updated">Live sync {lastSync.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}</span></div><div className="topbar-actions"><button className="top-search" onClick={() => navigate("graph")}><MagnifyingGlass size={16} /><span>Search reviewed graph</span></button><button className="icon-button" aria-label="Open pattern alerts" title="Open pattern alerts" onClick={() => navigate(can(authState.user, "analytics:run") ? "alerts" : "overview")}><Bell size={18} /></button><button className="user-button" onClick={handleLogout} aria-label={`Sign out ${authState.user.full_name}`} title="Sign out"><UserCircle size={23} /><span><strong>{authState.user.full_name}</strong><small>{roleLabels[authState.user.role]}</small></span><SignOut size={15} /></button></div></header><main className="content" key={`${activeCase.id}-${activeView}`}>{screens[activeView]}</main></div>{toast && <div className={`toast toast--${toast.tone}`}>{toast.tone === "error" ? <Warning size={19} weight="fill" /> : <CheckCircle size={19} weight="fill" />}<span>{toast.message}</span></div>}{sidebarOpen && <button className="sidebar-scrim" aria-label="Close navigation" onClick={() => setSidebarOpen(false)} />}</div>;
}
