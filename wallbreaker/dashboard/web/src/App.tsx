import { useEffect, useState } from "react";
import { api, type ConfigInfo, type Overview as OverviewT } from "./api";
import { Agent } from "./components/Agent";
import { Overview } from "./components/Overview";
import { Console } from "./components/Console";
import { Findings } from "./components/Findings";
import { Runs } from "./components/Runs";
import { Arsenal } from "./components/Arsenal";
import { Settings } from "./components/Settings";
import { Profiles } from "./components/Profiles";
import { Workflow } from "./components/Workflow";

type MainTab = "workspace" | "library" | "connections";
type AdvancedTab = "agent" | "overview" | "console" | "findings" | "runs";
type Tab = MainTab | AdvancedTab;

const MAIN: { id: MainTab; label: string; short: string }[] = [
  { id: "workspace", label: "Workspace", short: "WS" },
  { id: "library", label: "Prompt library", short: "PL" },
  { id: "connections", label: "Connections", short: "CN" },
];
const ADVANCED: { id: AdvancedTab; label: string; short: string }[] = [
  { id: "agent", label: "Agent terminal", short: "AG" },
  { id: "overview", label: "Legacy overview", short: "OV" },
  { id: "console", label: "Attack console", short: "AC" },
  { id: "findings", label: "Legacy findings", short: "FN" },
  { id: "runs", label: "Legacy run logs", short: "RL" },
];
const NAV = [...MAIN, ...ADVANCED];

function tabFromHash(): Tab {
  const hash = window.location.hash.replace("#", "");
  if (hash === "arsenal") return "library";
  if (hash === "settings" || hash === "profiles") return "connections";
  return (NAV.some((item) => item.id === hash) ? hash : "workspace") as Tab;
}

export function App() {
  const [tab, setTabState] = useState<Tab>(tabFromHash());
  const [advanced, setAdvanced] = useState(() => ADVANCED.some((item) => item.id === tabFromHash()));
  const [railCollapsed, setRailCollapsed] = useState(
    () => window.innerWidth < 700 || window.localStorage.getItem("wallbreaker.railCollapsed") === "true",
  );
  const [cfg, setCfg] = useState<ConfigInfo | null>(null);
  const [ov, setOv] = useState<OverviewT | null>(null);
  const [connectionsReady, setConnectionsReady] = useState<boolean | null>(null);
  const refresh = () => {
    api.config().then(setCfg).catch(() => setCfg(null));
    api.overview().then(setOv).catch(() => setOv(null));
    Promise.all([api.roles(), api.agentProfiles()]).then(([roles, profiles]) => {
      setConnectionsReady((["attacker", "target", "judge"] as const).every((role) => !!roles[role] && !!profiles.roles[role]?.active && Array.isArray(profiles.roles[role]?.profiles)));
    }).catch(() => setConnectionsReady(false));
  };
  useEffect(refresh, [tab]);
  useEffect(() => {
    const onHash = () => {
      const next = tabFromHash();
      setTabState(next);
      if (ADVANCED.some((item) => item.id === next)) setAdvanced(true);
    };
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const setTab = (next: Tab) => { setTabState(next); window.location.hash = next; };
  const toggleRail = () => {
    setRailCollapsed((current) => {
      window.localStorage.setItem("wallbreaker.railCollapsed", String(!current));
      return !current;
    });
  };
  const item = (nav: { id: Tab; label: string; short: string }) => <button
    type="button" key={nav.id} className={`nav-item ${tab === nav.id ? "active" : ""}`}
    onClick={() => setTab(nav.id)} title={railCollapsed ? nav.label : undefined}
    aria-current={tab === nav.id ? "page" : undefined}
  ><span className="dot" /><span className="nav-label">{railCollapsed ? nav.short : nav.label}</span></button>;

  return <div className={`app workflow-app ${railCollapsed ? "rail-collapsed" : ""}`}>
    <aside className="rail" aria-label="Primary navigation">
      <div className="brand"><span className="mark">◆</span><span className="word">{railCollapsed ? "RA" : <>ROOT<b>ACCESS</b></>}</span>
        <button type="button" className="rail-toggle" onClick={toggleRail}
          title={railCollapsed ? "Expand sidebar" : "Collapse sidebar"}
          aria-label={railCollapsed ? "Expand sidebar" : "Collapse sidebar"} aria-expanded={!railCollapsed}
        >{railCollapsed ? "›" : "‹"}</button>
      </div>
      {MAIN.map(item)}
      <button type="button" className={`nav-item workflow-advanced-toggle ${advanced ? "active" : ""}`}
        onClick={() => setAdvanced(!advanced)} aria-expanded={advanced} aria-controls="advanced-navigation"
      ><span className="dot" /><span className="nav-label">{railCollapsed ? "AD" : "Advanced"}</span><span className="workflow-chevron">{advanced ? "−" : "+"}</span></button>
      {advanced && <div id="advanced-navigation" className="workflow-advanced-nav">{ADVANCED.map(item)}</div>}
      <div className="spacer" /><div className="foot">One target. One candidate.<br />Evidence from every test.</div>
    </aside>
    <div className="main">
      <div className="topbar"><div className="title">{NAV.find((nav) => nav.id === tab)?.label}</div>
        <div className="meta"><span className="pill">Model safety testing</span></div>
      </div>
      <div className="content">
        {tab === "workspace" && <Workflow onOpenConnections={() => setTab("connections")} />}
        {tab === "library" && <Arsenal />}
        {tab === "connections" && <div className="workflow-connections">
          <div className="workflow-page-heading"><h1>Connections and model roles</h1><p>Connect your providers, then assign the attacker, API target, and evaluator.</p></div>
          {connectionsReady === null ? <div className="card muted">Loading model connections…</div> : connectionsReady ? <>
            <Settings onSaved={refresh} />
            <details className="card workflow-profile-details"><summary>Reusable model profiles</summary><Profiles onSaved={refresh} /></details>
          </> : <div className="card"><h2>No model configuration loaded</h2><p className="muted">Load a Wallbreaker configuration to manage providers and model profiles. You can evaluate a web target through manual relay without configured models.</p><button type="button" className="mini-btn" onClick={() => setTab("workspace")}>Open workspace</button></div>}
        </div>}
        {tab === "agent" && <Agent hasTarget={!!cfg?.has_target} />}
        {tab === "overview" && <Overview ov={ov} />}
        {tab === "console" && <Console hasTarget={!!cfg?.has_target} />}
        {tab === "findings" && <Findings />}
        {tab === "runs" && <Runs />}
      </div>
    </div>
  </div>;
}
