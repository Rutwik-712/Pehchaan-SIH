import { useCallback, useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import {
  ArrowClockwise,
  ArrowsIn,
  ArrowsOut,
  BookOpenText,
  CheckCircle,
  Fingerprint,
  Graph,
  Info,
  MagnifyingGlass,
  Path,
  ShieldCheck,
  SpinnerGap,
  X,
} from "@phosphor-icons/react";
import { getEvidencePath, getGraph, getGraphAnalytics, rebuildGraph, runGraphAnalytics } from "./api.js";
import { NetworkCanvas } from "./NetworkCanvas.jsx";
import { can, EmptyPanel, ErrorPanel, formatDate, LiveBadge, LoadingPanel, SectionHeader, shortId, StatusPill } from "./ui.jsx";

function graphType(entityType = "") {
  const type = entityType.toLowerCase();
  if (type.includes("phone")) return "phone";
  if (type.includes("account") || type.includes("amount")) return "account";
  if (type.includes("vehicle")) return "vehicle";
  if (type.includes("location")) return "location";
  if (type.includes("organization")) return "organization";
  if (type.includes("email")) return "email";
  if (type.includes("person")) return "person";
  return "other";
}

function relationLabel(relation = "") {
  const labels = {
    CALLED: "Called",
    MET_WITH: "Met with",
    TRANSFERRED_TO: "Transferred to",
    ASSOCIATED_WITH: "Associated with",
    LOCATED_AT: "Located at",
    USED_PHONE: "Used phone",
    USED_VEHICLE: "Used vehicle",
    CO_OCCURS_WITH: "Appears with",
  };
  return labels[relation] || relation.replaceAll("_", " ").toLowerCase();
}

export default function GraphWorkspace({ caseRecord, user, showToast, onDataChanged }) {
  const [state, setState] = useState({ loading: true, graph: null, analytics: null, error: null });
  const [filter, setFilter] = useState("all");
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState(null);
  const [building, setBuilding] = useState(false);
  const [centralityActive, setCentralityActive] = useState(false);
  const [sourceId, setSourceId] = useState("");
  const [targetId, setTargetId] = useState("");
  const [pathResult, setPathResult] = useState(null);
  const [pathBusy, setPathBusy] = useState(false);
  const [showEdgeLabels, setShowEdgeLabels] = useState(false);
  const [layoutVersion, setLayoutVersion] = useState(0);
  const [graphExpanded, setGraphExpanded] = useState(false);

  const load = useCallback(async () => {
    setState((current) => ({ ...current, loading: true, error: null }));
    try {
      const [graphResult, analyticsResult] = await Promise.allSettled([getGraph(caseRecord.id), getGraphAnalytics(caseRecord.id)]);
      if (graphResult.status === "rejected") throw graphResult.reason;
      setState({ loading: false, graph: graphResult.value, analytics: analyticsResult.status === "fulfilled" ? analyticsResult.value : null, error: null });
    } catch (error) { setState((current) => ({ ...current, loading: false, error })); }
  }, [caseRecord.id]);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!graphExpanded) return undefined;
    const previousOverflow = document.body.style.overflow;
    const closeOnEscape = (event) => { if (event.key === "Escape") setGraphExpanded(false); };
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", closeOnEscape);
    return () => { document.body.style.overflow = previousOverflow; window.removeEventListener("keydown", closeOnEscape); };
  }, [graphExpanded]);

  const elements = useMemo(() => {
    if (!state.graph) return [];
    return [
      ...state.graph.nodes.map((node) => ({ data: { ...node, type: graphType(node.entity_type), subtitle: `${node.entity_type} · ${node.evidence_count} evidence sources`, evidence: node.evidence_count, history: [`${node.mention_count} reviewed mentions`, `Degree ${node.degree} · community ${node.community_id ?? "not assigned"}`, `Priority level ${node.priority_level} · structural score ${node.priority_score.toFixed(3)}`] } })),
      ...state.graph.edges.map((edge) => ({ data: { ...edge, relation: relationLabel(edge.relation_type), confidence: edge.confidence_percent, evidence: edge.evidence_id, status: "confirmed" } })),
    ];
  }, [state.graph]);
  const types = useMemo(() => [...new Set((state.graph?.nodes || []).map((node) => graphType(node.entity_type)))].sort(), [state.graph]);
  const labels = useMemo(() => new Map((state.graph?.nodes || []).map((node) => [node.id, node.label])), [state.graph]);

  const rebuild = async () => {
    setBuilding(true);
    try {
      const snapshot = await rebuildGraph(caseRecord.id);
      const analytics = await runGraphAnalytics(caseRecord.id);
      await load(); onDataChanged();
      showToast(`Reviewed graph rebuilt: ${snapshot.node_count} nodes, ${snapshot.edge_count} links, ${analytics.alerts.length} alerts.`);
    } catch (error) { showToast(error.message, "error"); }
    finally { setBuilding(false); }
  };

  const findPath = async () => {
    if (!sourceId || !targetId || sourceId === targetId) return;
    setPathBusy(true);
    try {
      const result = await getEvidencePath(caseRecord.id, sourceId, targetId);
      setPathResult(result);
      showToast(result.found ? `Reviewed evidence path found in ${result.hop_count} hops.` : "No reviewed evidence path connects those entities.");
    } catch (error) { showToast(error.message, "error"); }
    finally { setPathBusy(false); }
  };

  if (state.loading && !state.graph) return <LoadingPanel label="Loading the reviewed Neo4j projection…" />;
  if (state.error) return <ErrorPanel error={state.error} onRetry={load} />;
  const graph = state.graph;
  const rankings = state.analytics?.rankings || [];
  const pathNodes = pathResult?.found ? pathResult.node_ids : [];
  const pathEdges = pathResult?.found ? pathResult.edges.map((edge) => edge.id) : [];
  const selectedConnections = selected?.group === "node" ? graph.edges.filter((edge) => edge.source === selected.id || edge.target === selected.id).map((edge) => ({ ...edge, otherId: edge.source === selected.id ? edge.target : edge.source })).sort((left, right) => relationLabel(left.relation_type).localeCompare(relationLabel(right.relation_type))) : [];
  const inspectEdge = (edge) => setSelected({ group: "edge", ...edge, relation: relationLabel(edge.relation_type), confidence: edge.confidence_percent, evidence: edge.evidence_id, status: "confirmed" });

  return (
    <div className="screen screen--graph">
      <SectionHeader eyebrow="Step 03 · Reviewed connection exploration" title="Evidence network" description="Explore only confirmed or corrected relationships. Structural metrics describe graph position—not guilt, intent, or criminal responsibility." action={<div className="header-actions"><button className="button button--dark" onClick={load}><ArrowClockwise size={17} /> Refresh</button>{can(user, "analytics:run") && <button className="button button--yellow" onClick={rebuild} disabled={building}>{building ? <><SpinnerGap className="spin" size={17} /> Rebuilding & analyzing…</> : <><Graph size={17} /> Rebuild reviewed graph</>}</button>}</div>} />
      {!graph.nodes.length ? <EmptyPanel title="The reviewed graph is empty" detail="Confirm extracted mentions and relationships in the review queue, then rebuild this case graph." /> : <div className="graph-shell">
        <div className="graph-toolbar"><div className="graph-search"><MagnifyingGlass size={17} /><input aria-label="Search graph" placeholder="Search reviewed entity" value={search} onChange={(event) => setSearch(event.target.value)} /></div><div className="filter-chips">{["all", ...types].map((type) => <button key={type} className={filter === type ? "active" : ""} onClick={() => setFilter(type)}>{type === "all" ? "All entities" : type}</button>)}</div><div className="graph-view-controls"><button className={showEdgeLabels ? "active" : ""} onClick={() => setShowEdgeLabels((value) => !value)}>{showEdgeLabels ? "Hide link labels" : "Show link labels"}</button><button onClick={() => { setSelected(null); setLayoutVersion((value) => value + 1); }}>Tidy layout</button></div><span className="mono-note">{graph.nodes.length} nodes · {graph.edges.length} links</span></div>
        <div className="path-controls"><div><Path size={17} /><select aria-label="Path source" value={sourceId} onChange={(event) => setSourceId(event.target.value)}><option value="">Path source…</option>{graph.nodes.map((node) => <option key={node.id} value={node.id}>{node.label}</option>)}</select><span>to</span><select aria-label="Path target" value={targetId} onChange={(event) => setTargetId(event.target.value)}><option value="">Path target…</option>{graph.nodes.map((node) => <option key={node.id} value={node.id}>{node.label}</option>)}</select><button className="button button--dark" onClick={findPath} disabled={pathBusy || !sourceId || !targetId || sourceId === targetId}>{pathBusy ? <SpinnerGap className="spin" size={16} /> : <Path size={16} />} Find reviewed path</button>{pathResult && <button className="icon-button" title="Clear path" onClick={() => setPathResult(null)}><X size={15} /></button>}</div><button className={`button button--dark ${centralityActive ? "is-active" : ""}`} onClick={() => setCentralityActive((value) => !value)} disabled={!rankings.length}><Graph size={16} /> {centralityActive ? "Clear prominence" : "Show prominence"}</button></div>
        <div className="graph-main"><div className="graph-stage"><NetworkCanvas key={layoutVersion} elements={elements} filter={filter} search={search} pathNodeIds={pathNodes} pathEdgeIds={pathEdges} centralityIds={centralityActive ? rankings.slice(0, 5).map((item) => item.id) : []} showEdgeLabels={showEdgeLabels} onSelect={setSelected} /><div className="graph-legend"><span><i className="legend-solid" /> Reviewed evidence relation</span><span><i className="legend-central" /> Structural prominence</span><span>Click a node to isolate its neighborhood</span></div><button className="graph-maximize" type="button" title="Open focused graph" aria-label="Open focused graph" onClick={() => setGraphExpanded(true)}><ArrowsOut size={17} /><span>Maximize</span></button>{pathResult && <div className={`path-summary ${pathResult.found ? "" : "path-summary--empty"}`}><Path size={18} /><div><strong>{pathResult.found ? `Shortest reviewed path · ${pathResult.hop_count} hops` : "No reviewed path found"}</strong><span>{pathResult.found ? pathResult.node_ids.map((id) => labels.get(id) || shortId(id)).join(" → ") : pathResult.disclaimer}</span></div></div>}{centralityActive && <div className="centrality-summary"><div className="centrality-summary__head"><div><p className="eyebrow">PageRank · reviewed case graph</p><strong>Structurally prominent entities</strong></div><StatusPill tone="yellow">NOT A GUILT SCORE</StatusPill></div><div className="centrality-ranking">{rankings.slice(0, 5).map((item, index) => <button key={item.id} onClick={() => setSelected({ group: "node", ...graph.nodes.find((node) => node.id === item.id), type: graphType(item.entity_type), subtitle: `${item.entity_type} · priority level ${item.priority_level}`, evidence: graph.nodes.find((node) => node.id === item.id)?.evidence_count || 0 })}><span>{String(index + 1).padStart(2, "0")}</span><strong>{item.canonical_value}</strong><small>{item.pagerank.toFixed(4)}</small></button>)}</div><p>{state.analytics.disclaimer}</p></div>}</div>
          <aside className="graph-inspector">{selected ? <><div className="inspector-top"><StatusPill tone="yellow">{selected.group?.toUpperCase()}</StatusPill><button className="icon-button" onClick={() => setSelected(null)} aria-label="Close inspector"><X size={16} /></button></div><h2>{selected.label || selected.relation}</h2><p>{selected.subtitle || `${labels.get(selected.source) || shortId(selected.source)} → ${labels.get(selected.target) || shortId(selected.target)}`}</p><dl className="inspector-list">{selected.entity_type && <><dt>Entity type</dt><dd>{selected.entity_type}</dd><dt>Reviewed aliases</dt><dd>{selected.aliases?.join(", ") || "None"}</dd><dt>Graph degree</dt><dd>{selected.degree}</dd><dt>PageRank</dt><dd>{selected.pagerank?.toFixed(6)}</dd><dt>Community</dt><dd>{selected.community_id ?? "Not assigned"}</dd></>}{selected.relation && <><dt>Relationship</dt><dd>{selected.relation}</dd><dt>Extraction confidence</dt><dd>{selected.confidence}%</dd><dt>Evidence page</dt><dd>{selected.page_number || 1}</dd><dt>Observed</dt><dd>{formatDate(selected.observed_at)}</dd><dt>Evidence</dt><dd>{shortId(selected.evidence_id)}</dd></>}</dl>{selectedConnections.length > 0 && <section className="inspector-connections"><div><h3>Connection evidence</h3><span>{selectedConnections.length}</span></div>{selectedConnections.map((edge) => <button type="button" key={edge.id} onClick={() => inspectEdge(edge)}><strong>{relationLabel(edge.relation_type)} · {labels.get(edge.otherId) || shortId(edge.otherId)}</strong><p>{edge.source_excerpt}</p><small>Page {edge.page_number || 1} · {edge.confidence_percent}% extraction confidence</small></button>)}</section>}{selected.source_excerpt && <div className="relationship-reason"><span>Why these entities are connected</span><blockquote className="inspector-excerpt">“{selected.source_excerpt}”</blockquote></div>}<div className="inspector-warning"><Info size={16} /><span>This panel reports evidence coverage and graph structure—not culpability.</span></div></> : <div className="inspector-empty"><Fingerprint size={38} weight="duotone" /><h2>Select a graph item</h2><p>Choose a node or relationship to inspect its reviewed provenance and metrics.</p></div>}</aside>
        </div>
        <footer className="graph-provenance"><LiveBadge>Neo4j reviewed projection</LiveBadge><span>Snapshot {shortId(graph.snapshot_id || "not built")} · {graph.generated_at ? formatDate(graph.generated_at) : "not generated"}</span><span><ShieldCheck size={14} /> {graph.disclaimer}</span></footer>
      </div>}
      {graphExpanded && createPortal(<section className="graph-focus-overlay" role="dialog" aria-modal="true" aria-label={`Focused network graph for ${caseRecord.id}`}>
        <div className="graph-focus-canvas"><NetworkCanvas key={`expanded-${layoutVersion}`} elements={elements} filter={filter} search={search} pathNodeIds={pathNodes} pathEdgeIds={pathEdges} centralityIds={centralityActive ? rankings.slice(0, 5).map((item) => item.id) : []} showEdgeLabels={showEdgeLabels} onSelect={setSelected} /></div>
        <footer className="graph-focus-footer">
          <div><span>ACTIVE CASE</span><strong>{caseRecord.id}</strong><small>{caseRecord.title}</small></div>
          <div className="graph-focus-status"><span>{graph.nodes.length} nodes · {graph.edges.length} reviewed links</span>{selected && <span>Selected: {selected.label || selected.relation}</span>}<small>Network position does not establish guilt.</small></div>
          <div className="graph-focus-actions"><button type="button" className={showEdgeLabels ? "active" : ""} onClick={() => setShowEdgeLabels((value) => !value)}>{showEdgeLabels ? "Hide labels" : "Show labels"}</button><button type="button" onClick={() => setLayoutVersion((value) => value + 1)}><ArrowClockwise size={15} /> Tidy</button><button type="button" onClick={() => setGraphExpanded(false)}><ArrowsIn size={16} /> Minimize</button></div>
        </footer>
      </section>, document.body)}
    </div>
  );
}
