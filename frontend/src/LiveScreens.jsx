import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowClockwise,
  ArrowRight,
  BookOpenText,
  Check,
  CheckCircle,
  ClockCounterClockwise,
  Database,
  DownloadSimple,
  FileArrowUp,
  FileText,
  Fingerprint,
  Graph,
  HardDrives,
  LinkSimple,
  Scan,
  ShieldCheck,
  SpinnerGap,
  Warning,
  X,
} from "@phosphor-icons/react";
import {
  downloadEvidence,
  getAuditLogs,
  getEvidence,
  getGraph,
  getGraphAnalytics,
  getGraphTimeline,
  getProcessingJobs,
  getResolutionCandidates,
  getReviewQueue,
  retryProcessingJob,
  reviewGraphAlert,
  reviewMention,
  reviewRelation,
  reviewResolutionCandidate,
  runEntityResolution,
  runGraphAnalytics,
  startProcessingJob,
  uploadEvidence,
  verifyAuditChain,
  verifyEvidenceIntegrity,
} from "./api.js";
import evidenceBoard from "./assets/evidence-board-wide.png";
import {
  can,
  EmptyPanel,
  ErrorPanel,
  formatBytes,
  formatDate,
  LiveBadge,
  LoadingPanel,
  SectionHeader,
  shortId,
  StatusPill,
  statusTone,
} from "./ui.jsx";

const ACTIVE_JOB_STATUSES = new Set(["queued", "running", "processing", "retrying"]);

function relationPhrase(relation = "") {
  const labels = {
    CALLED: "called",
    MET_WITH: "met with",
    TRANSFERRED_TO: "transferred to",
    ASSOCIATED_WITH: "associated with",
    LOCATED_AT: "located at",
    USED_PHONE: "used phone",
    USED_VEHICLE: "used vehicle",
    CO_OCCURS_WITH: "appears with",
  };
  return labels[relation] || relation.replaceAll("_", " ").toLowerCase();
}

function useReloadable(loader, dependencies) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const load = useCallback(async () => {
    setState((current) => ({ ...current, loading: true, error: null }));
    try {
      const data = await loader();
      setState({ loading: false, data, error: null });
      return data;
    } catch (error) {
      setState((current) => ({ ...current, loading: false, error }));
      throw error;
    }
  }, dependencies); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load().catch(() => {}); }, [load]);
  return { ...state, reload: load, setData: (data) => setState({ loading: false, data, error: null }) };
}

export function Overview({ caseRecord, user, onNavigate, refreshToken }) {
  const loader = useCallback(async () => {
    const requests = [getEvidence(caseRecord.id), getProcessingJobs(caseRecord.id), getGraph(caseRecord.id)];
    if (can(user, "entity:review")) requests.push(getReviewQueue(caseRecord.id));
    if (can(user, "analytics:run")) requests.push(getGraphAnalytics(caseRecord.id));
    const results = await Promise.allSettled(requests);
    const value = (index, fallback) => results[index]?.status === "fulfilled" ? results[index].value : fallback;
    return {
      evidence: value(0, []),
      jobs: value(1, []),
      graph: value(2, { nodes: [], edges: [] }),
      queue: can(user, "entity:review") ? value(3, { total_pending: 0, mentions: [], relations: [] }) : null,
      analytics: can(user, "analytics:run") ? value(can(user, "entity:review") ? 4 : 3, null) : null,
    };
  }, [caseRecord.id, user, refreshToken]);
  const state = useReloadable(loader, [loader]);
  const [auditResult, setAuditResult] = useState(null);
  const [auditBusy, setAuditBusy] = useState(false);

  if (state.loading && !state.data) return <LoadingPanel label="Building the authorized case summary…" />;
  if (state.error && !state.data) return <ErrorPanel error={state.error} onRetry={state.reload} />;
  const { evidence, jobs, graph, queue, analytics } = state.data;
  const completedJobs = jobs.filter((job) => job.status === "completed").length;
  const activeJobs = jobs.filter((job) => ACTIVE_JOB_STATUSES.has(job.status)).length;
  const openAlerts = analytics?.alerts?.filter((alert) => alert.status !== "reviewed").length || 0;
  const metrics = [
    { label: "Evidence sources", value: evidence.length, detail: `${completedJobs}/${jobs.length} jobs complete`, icon: HardDrives },
    { label: "Reviewed entities", value: graph.nodes.length, detail: `${new Set(graph.nodes.map((node) => node.entity_type)).size} entity types`, icon: Fingerprint },
    { label: "Reviewed links", value: graph.edges.length, detail: graph.snapshot_id ? `Snapshot ${shortId(graph.snapshot_id)}` : "Graph not built", icon: LinkSimple },
    { label: "Pending review", value: queue?.total_pending ?? "Restricted", detail: `${openAlerts} analytical alerts`, icon: Scan },
  ];
  const pipeline = [
    { label: "Register", value: `${evidence.length} sources`, done: evidence.length > 0, target: "intake" },
    { label: "Process", value: `${completedJobs} complete`, done: completedJobs > 0, target: "intake" },
    { label: "Review", value: queue ? `${queue.total_pending} pending` : "Role restricted", done: queue ? queue.total_pending === 0 && completedJobs > 0 : false, target: "review" },
    { label: "Resolve", value: `${graph.nodes.length} entities`, done: graph.nodes.length > 0, target: "graph" },
    { label: "Analyze", value: analytics ? `${analytics.rankings.length} ranked` : "Not run", done: analytics?.snapshot?.status === "analytics_completed", target: "graph" },
    { label: "Investigate", value: `${openAlerts} open leads`, done: Boolean(analytics), target: "alerts" },
  ];

  const checkAudit = async () => {
    setAuditBusy(true);
    try {
      const [chain, logs] = await Promise.all([verifyAuditChain(caseRecord.id), getAuditLogs(caseRecord.id)]);
      setAuditResult({ ...chain, logs: logs.length });
    } finally { setAuditBusy(false); }
  };

  return (
    <div className="screen screen--overview">
      <SectionHeader eyebrow="Active investigation workspace" title={caseRecord.title} description={`${caseRecord.description} This workspace reports reviewed evidence structure and never determines guilt.`} action={<div className="header-actions"><button className="button button--dark" onClick={() => state.reload()}><ArrowClockwise size={17} /> Refresh</button><button className="button button--yellow" onClick={() => onNavigate("intake")}><FileArrowUp size={18} /> Add evidence</button></div>} />
      <div className="metrics-grid">{metrics.map((metric) => { const Icon = metric.icon; return <article className="metric-card" key={metric.label}><Icon size={20} weight="duotone" /><div><strong>{metric.value}</strong><span>{metric.label}</span></div><small>{metric.detail}</small></article>; })}</div>
      <section className="pipeline-card">
        <div className="card-heading-row"><div><p className="eyebrow">Live pipeline status</p><h2>Source to reviewed graph</h2></div><LiveBadge /></div>
        <div className="pipeline-track">{pipeline.map((step, index) => <button key={step.label} className={`pipeline-step pipeline-step--${step.done ? "done" : activeJobs && index === 1 ? "active" : "pending"}`} onClick={() => onNavigate(step.target)}><span className="pipeline-index">0{index + 1}</span><span className="pipeline-copy"><strong>{step.label}</strong><small>{step.value}</small></span>{index < pipeline.length - 1 && <ArrowRight className="pipeline-arrow" size={15} />}</button>)}</div>
      </section>
      <div className="overview-grid">
        <article className="evidence-hero"><img src={evidenceBoard} alt="Evidence board representing source-backed investigation records" /><div className="evidence-hero__shade" /><div className="evidence-hero__content"><StatusPill tone={openAlerts ? "danger" : "safe"}>{openAlerts ? `${openAlerts} OPEN ANALYTICAL LEADS` : "NO OPEN GRAPH ALERTS"}</StatusPill><h2>{graph.nodes.length ? `${graph.nodes.length} reviewed entities connected by ${graph.edges.length} evidence links` : "Review extracted facts to build the first network"}</h2><p>{graph.generated_at ? `Latest projection: ${formatDate(graph.generated_at)}.` : "The graph remains empty until an investigator confirms extracted mentions and relationships."}</p><button className="button button--light" onClick={() => onNavigate("graph")}>Open network <ArrowRight size={17} /></button></div></article>
        <article className="activity-card"><div className="card-heading-row compact"><div><p className="eyebrow">Case controls</p><h2>Needs attention</h2></div><span className="queue-count">{String((queue?.total_pending || 0) + openAlerts).padStart(2, "0")}</span></div><div className="attention-list"><button onClick={() => onNavigate("intake")}><span className="attention-icon attention-icon--blue"><Database size={18} /></span><span><strong>{activeJobs} jobs active</strong><small>PostgreSQL-backed stage status</small></span><ArrowRight size={15} /></button>{queue && <button onClick={() => onNavigate("review")}><span className="attention-icon attention-icon--yellow"><Scan size={18} /></span><span><strong>{queue.total_pending} facts awaiting review</strong><small>{queue.mentions.length} mentions · {queue.relations.length} relations</small></span><ArrowRight size={15} /></button>}{can(user, "audit:view") && <button onClick={checkAudit} disabled={auditBusy}><span className="attention-icon attention-icon--yellow"><ShieldCheck size={18} /></span><span><strong>{auditBusy ? "Checking audit chain…" : auditResult ? `${auditResult.entries_checked} entries checked` : "Verify audit chain"}</strong><small>{auditResult ? `Chain ${auditResult.valid ? "valid" : "invalid"} · ${auditResult.logs} visible rows` : "SP-level integrity control"}</small></span><ArrowRight size={15} /></button>}</div><div className="safety-note"><ShieldCheck size={16} /><p><strong>Interpretation boundary</strong> Priority and graph prominence describe reviewed network structure. They do not establish identity, intent or culpability.</p></div></article>
      </div>
    </div>
  );
}

export function EvidenceIntake({ caseRecord, user, showToast, onDataChanged }) {
  const fileRef = useRef(null);
  const [files, setFiles] = useState([]);
  const [busy, setBusy] = useState(false);
  const [actionId, setActionId] = useState("");
  const loader = useCallback(async () => {
    const [evidence, jobs] = await Promise.all([getEvidence(caseRecord.id), getProcessingJobs(caseRecord.id)]);
    return { evidence, jobs };
  }, [caseRecord.id]);
  const state = useReloadable(loader, [loader]);

  useEffect(() => {
    if (!state.data?.jobs?.some((job) => ACTIVE_JOB_STATUSES.has(job.status))) return undefined;
    const timer = window.setInterval(() => state.reload().catch(() => {}), 2500);
    return () => window.clearInterval(timer);
  }, [state.data?.jobs, state.reload]);

  const latestJob = useMemo(() => {
    const map = new Map();
    (state.data?.jobs || []).forEach((job) => { if (!map.has(job.evidence_id)) map.set(job.evidence_id, job); });
    return map;
  }, [state.data?.jobs]);

  const submit = async (event) => {
    event.preventDefault();
    if (!files.length) return;
    setBusy(true);
    try {
      let deduplicated = 0;
      for (const file of files) {
        const result = await uploadEvidence(caseRecord.id, file);
        if (result.deduplicated) deduplicated += 1;
      }
      setFiles([]);
      if (fileRef.current) fileRef.current.value = "";
      await state.reload();
      onDataChanged();
      showToast(`${files.length} evidence file${files.length === 1 ? "" : "s"} registered${deduplicated ? `; ${deduplicated} duplicate reused` : ""}.`);
    } catch (error) { showToast(error.message, "error"); } finally { setBusy(false); }
  };

  const runAction = async (id, action, success) => {
    setActionId(id);
    try { await action(); await state.reload(); onDataChanged(); showToast(success); }
    catch (error) { showToast(error.message, "error"); }
    finally { setActionId(""); }
  };

  const download = async (item) => {
    setActionId(item.id);
    try {
      const { blob } = await downloadEvidence(caseRecord.id, item.id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url; anchor.download = item.original_filename; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      showToast("Protected evidence download started.");
    } catch (error) { showToast(error.message, "error"); }
    finally { setActionId(""); }
  };

  return (
    <div className="screen">
      <SectionHeader eyebrow="Step 01 · Source registration" title="Evidence intake" description="Upload case-scoped evidence, monitor its durable Celery stages, verify integrity, and download originals through the protected API." action={<LiveBadge>MinIO + PostgreSQL live</LiveBadge>} />
      <div className="intake-layout">
        <form className="drop-panel live-upload" onSubmit={submit}>
          <div className="drop-panel__visual"><FileArrowUp size={30} weight="duotone" /></div><p className="eyebrow">New immutable source</p><h2>Select evidence files</h2><p>Supported local processing formats include PDF, images, CSV and UTF-8 text. Every file is hashed before storage.</p>
          <input ref={fileRef} className="file-input" type="file" multiple accept=".pdf,.png,.jpg,.jpeg,.csv,.txt" onChange={(event) => setFiles(Array.from(event.target.files || []))} />
          <div className="selected-files">{files.length ? files.map((file) => <span key={`${file.name}-${file.size}`}><FileText size={14} /> {file.name} · {formatBytes(file.size)}</span>) : <span>No files selected</span>}</div>
          <button className="button button--yellow button--wide" type="submit" disabled={busy || !files.length}>{busy ? <><SpinnerGap className="spin" size={18} /> Registering evidence…</> : <><ShieldCheck size={18} /> Register and process {files.length || ""}</>}</button>
          <div className="provenance-strip compact-strip"><Fingerprint size={20} /><div><strong>Original bytes remain immutable</strong><span>SHA-256, media type, size, uploader and storage metadata are recorded before asynchronous processing.</span></div></div>
        </form>
        <section className="source-register">
          <div className="card-heading-row"><div><p className="eyebrow">Registered evidence</p><h2>Live source register</h2></div><button className="button button--dark" onClick={() => state.reload()}><ArrowClockwise size={16} /> Refresh</button></div>
          {state.loading && !state.data ? <LoadingPanel /> : state.error ? <ErrorPanel error={state.error} onRetry={state.reload} /> : !state.data.evidence.length ? <EmptyPanel title="No evidence registered" detail="Upload the first synthetic FIR or structured source for this case." /> : <div className="source-list live-source-list">{state.data.evidence.map((item) => { const job = latestJob.get(item.id); return <article className="source-row live-source-row" key={item.id}><div className="source-file-icon source-file-icon--yellow"><FileText size={21} /></div><div className="source-main"><strong>{item.original_filename}</strong><span>{item.media_type} · {formatBytes(item.size_bytes)} · {formatDate(item.created_at)}</span><small>SHA-256 {shortId(item.sha256)} · {item.storage_backend}</small>{job && <div className="job-progress"><span style={{ width: `${job.progress_percent}%` }} /><small>{job.current_stage || job.status} · {job.progress_percent}%</small></div>}</div><div className="source-actions"><StatusPill tone={statusTone(job?.status || item.status)}>{job?.status || item.status}</StatusPill><div><button title="Verify integrity" onClick={() => runAction(item.id, () => verifyEvidenceIntegrity(caseRecord.id, item.id), "Evidence integrity verified.")} disabled={actionId === item.id}><Fingerprint size={15} /></button><button title="Download original" onClick={() => download(item)} disabled={actionId === item.id}><DownloadSimple size={15} /></button>{job?.status && ["failed", "dispatch_failed"].includes(job.status) && can(user, "analytics:run") && <button title="Retry failed job" onClick={() => runAction(job.id, () => retryProcessingJob(caseRecord.id, job.id), "Processing job queued for retry.")}><ArrowClockwise size={15} /></button>}{!job && <button title="Start processing" onClick={() => runAction(item.id, () => startProcessingJob(caseRecord.id, item.id), "Processing job started.")}><Scan size={15} /></button>}</div></div>{job?.stages?.length > 0 && <details className="stage-ledger"><summary>{job.stages.length} durable stages · {job.retry_count} retries</summary><div>{job.stages.map((stage) => <span key={stage.id} className={`stage-ledger__item stage-ledger__item--${stage.status}`}><i />{stage.sequence}. {stage.stage_name}<small>{stage.status}{stage.attempt_count > 1 ? ` · ${stage.attempt_count} attempts` : ""}</small></span>)}</div></details>}</article>; })}</div>}
        </section>
      </div>
    </div>
  );
}

export function ExtractionReview({ caseRecord, showToast, onDataChanged }) {
  const [tab, setTab] = useState("mentions");
  const [busyId, setBusyId] = useState("");
  const [resolving, setResolving] = useState(false);
  const loader = useCallback(async () => {
    const [queue, candidates] = await Promise.all([getReviewQueue(caseRecord.id), getResolutionCandidates(caseRecord.id)]);
    return { queue, candidates };
  }, [caseRecord.id]);
  const state = useReloadable(loader, [loader]);
  const mentionMap = useMemo(() => new Map((state.data?.queue.mentions || []).map((item) => [item.id, item])), [state.data]);

  const decide = async (kind, item, decision) => {
    let payload = { decision, notes: "Reviewed in Phase 7 dashboard." };
    if (decision === "correct") {
      if (kind === "mention") {
        const correctedValue = window.prompt("Corrected entity value", item.value);
        if (!correctedValue) return;
        const correctedType = window.prompt("Corrected entity type", item.entity_type);
        if (!correctedType) return;
        payload = { ...payload, corrected_value: correctedValue, corrected_type: correctedType.toUpperCase() };
      } else {
        const correctedType = window.prompt("Corrected relationship type", item.relation_type);
        if (!correctedType) return;
        payload = { ...payload, corrected_type: correctedType.toUpperCase() };
      }
    }
    setBusyId(item.id);
    try {
      if (kind === "mention") await reviewMention(caseRecord.id, item.id, payload);
      else await reviewRelation(caseRecord.id, item.id, payload);
      await state.reload(); onDataChanged(); showToast(`${kind === "mention" ? "Entity" : "Relationship"} ${decision === "confirm" ? "confirmed" : decision === "reject" ? "rejected" : "corrected"}.`);
    } catch (error) { showToast(error.message, "error"); } finally { setBusyId(""); }
  };

  const runResolution = async () => {
    setResolving(true);
    try { const result = await runEntityResolution(caseRecord.id); await state.reload(); onDataChanged(); showToast(`Resolution completed: ${result.entity_count} entities and ${result.candidate_count} pending matches.`); }
    catch (error) { showToast(error.message, "error"); } finally { setResolving(false); }
  };

  const decideCandidate = async (candidate, decision) => {
    setBusyId(candidate.id);
    try { await reviewResolutionCandidate(caseRecord.id, candidate.id, decision, "Reviewed in Phase 7 dashboard."); await state.reload(); onDataChanged(); showToast(`Potential duplicate ${decision === "confirm" ? "confirmed" : "rejected"}. Run resolution again to apply confirmed merges.`); }
    catch (error) { showToast(error.message, "error"); } finally { setBusyId(""); }
  };

  if (state.loading && !state.data) return <LoadingPanel label="Loading the investigator review queue…" />;
  if (state.error) return <ErrorPanel error={state.error} onRetry={state.reload} />;
  const { queue, candidates } = state.data;
  const current = tab === "mentions" ? queue.mentions : tab === "relations" ? queue.relations : candidates;
  return (
    <div className="screen">
      <SectionHeader eyebrow="Step 02 · Human verification" title="Extraction and identity review" description="Confirm, correct, or reject machine proposals before they can enter the reviewed graph. Fuzzy identity matches also require an explicit decision." action={<div className="header-actions"><button className="button button--dark" onClick={() => state.reload()}><ArrowClockwise size={16} /> Refresh</button><button className="button button--yellow" onClick={runResolution} disabled={resolving}>{resolving ? <><SpinnerGap className="spin" size={17} /> Resolving…</> : <><Fingerprint size={17} /> Run entity resolution</>}</button></div>} />
      <section className="review-workspace">
        <div className="review-tabs"><button className={tab === "mentions" ? "active" : ""} onClick={() => setTab("mentions")}>Entities <span>{queue.mentions.length}</span></button><button className={tab === "relations" ? "active" : ""} onClick={() => setTab("relations")}>Relationships <span>{queue.relations.length}</span></button><button className={tab === "candidates" ? "active" : ""} onClick={() => setTab("candidates")}>Possible duplicates <span>{candidates.length}</span></button></div>
        <div className="review-panel__head"><div><p className="eyebrow">Append-only decisions</p><h2>{tab === "candidates" ? "Review Splink identity candidates" : `Review pending ${tab}`}</h2></div><StatusPill tone={current.length ? "yellow" : "safe"}>{current.length ? "Review required" : "Queue clear"}</StatusPill></div>
        {!current.length ? <EmptyPanel title="Nothing pending in this queue" detail={tab === "candidates" ? "Run entity resolution after confirming mentions to discover conservative fuzzy-match candidates." : "Upload and process evidence, or switch to another review tab."} /> : <div className="live-review-list">{tab === "mentions" && current.map((item) => <article className="live-review-card" key={item.id}><div className="review-card-meta"><StatusPill tone="blue">{item.entity_type}</StatusPill><span>{item.confidence_percent}% extraction confidence</span><span>Page {item.page_number}</span></div><h3>{item.value}</h3><blockquote>{item.source_excerpt}</blockquote><div className="review-card-foot"><span>{item.extraction_method} · evidence {shortId(item.evidence_id)}</span><div><button className="decision decision--confirm" disabled={busyId === item.id} onClick={() => decide("mention", item, "confirm")}><Check size={15} /> Confirm</button><button className="decision" disabled={busyId === item.id} onClick={() => decide("mention", item, "correct")}>Correct</button><button className="decision decision--reject" disabled={busyId === item.id} onClick={() => decide("mention", item, "reject")}><X size={15} /> Reject</button></div></div></article>)}{tab === "relations" && current.map((item) => { const subject = item.subject_value || mentionMap.get(item.subject_mention_id)?.value || shortId(item.subject_mention_id); const object = item.object_value || mentionMap.get(item.object_mention_id)?.value || shortId(item.object_mention_id); return <article className="live-review-card relation-review-card" key={item.id}><div className="review-card-meta"><StatusPill tone="yellow">{item.relation_type}</StatusPill><span>{item.confidence_percent}% extraction confidence</span><span>Page {item.page_number || 1}</span></div><h3 className="relation-statement"><span><strong>{subject}</strong><small>{item.subject_entity_type || "ENTITY"}</small></span><ArrowRight size={15} /><em>{relationPhrase(item.relation_type)}</em><ArrowRight size={15} /><span><strong>{object}</strong><small>{item.object_entity_type || "ENTITY"}</small></span></h3><blockquote>{item.source_excerpt}</blockquote><div className="review-card-foot"><span>{item.extraction_method} · mentions {shortId(item.subject_mention_id)} → {shortId(item.object_mention_id)} · evidence {shortId(item.evidence_id)}</span><div><button className="decision decision--confirm" disabled={busyId === item.id} onClick={() => decide("relation", item, "confirm")}><Check size={15} /> Confirm</button><button className="decision" disabled={busyId === item.id} onClick={() => decide("relation", item, "correct")}>Correct</button><button className="decision decision--reject" disabled={busyId === item.id} onClick={() => decide("relation", item, "reject")}><X size={15} /> Reject</button></div></div></article>; })}{tab === "candidates" && current.map((item) => <article className="live-review-card identity-card" key={item.id}><div className="review-card-meta"><StatusPill tone="yellow">{item.entity_type}</StatusPill><span>{Math.round(item.match_probability * 100)}% match probability</span><span>{item.method}</span></div><h3>{item.left_value} <span className="identity-equals">possibly equals</span> {item.right_value}</h3><p>Confirming this candidate permits these reviewed mentions to merge on the next resolution run. It does not verify a real-world identity beyond the selected records.</p><div className="review-card-foot"><span>Candidate {shortId(item.id)}</span><div><button className="decision decision--confirm" disabled={busyId === item.id} onClick={() => decideCandidate(item, "confirm")}><Check size={15} /> Same entity</button><button className="decision decision--reject" disabled={busyId === item.id} onClick={() => decideCandidate(item, "reject")}><X size={15} /> Keep separate</button></div></div></article>)}</div>}
      </section>
      <div className="safety-banner"><ShieldCheck size={19} /><span><strong>Human review boundary</strong> Extraction confidence estimates parser certainty. It is not an accusation, risk score, or measure of investigative importance.</span></div>
    </div>
  );
}

export function TimelineView({ caseRecord }) {
  const loader = useCallback(async () => {
    const [graph, events] = await Promise.all([getGraph(caseRecord.id), getGraphTimeline(caseRecord.id)]);
    return { graph, events };
  }, [caseRecord.id]);
  const state = useReloadable(loader, [loader]);
  const [relationFilter, setRelationFilter] = useState("all");
  if (state.loading && !state.data) return <LoadingPanel label="Loading reviewed graph events…" />;
  if (state.error) return <ErrorPanel error={state.error} onRetry={state.reload} />;
  const labels = new Map(state.data.graph.nodes.map((node) => [node.id, node.label]));
  const relationTypes = [...new Set(state.data.events.map((item) => item.relation_type))].sort();
  const events = relationFilter === "all" ? state.data.events : state.data.events.filter((item) => item.relation_type === relationFilter);
  const exportEvents = () => {
    const rows = [["observed_at", "relation_type", "source", "target", "evidence_id", "source_excerpt"], ...events.map((item) => [item.observed_at, item.relation_type, labels.get(item.source_entity_id), labels.get(item.target_entity_id), item.evidence_id, item.source_excerpt])];
    const csv = rows.map((row) => row.map((value) => `"${String(value ?? "").replaceAll('"', '""')}"`).join(",")).join("\n");
    const url = URL.createObjectURL(new Blob([csv], { type: "text/csv" }));
    const anchor = document.createElement("a"); anchor.href = url; anchor.download = `${caseRecord.id}-reviewed-timeline.csv`; anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <div className="screen"><SectionHeader eyebrow="Step 04 · Temporal context" title="Reviewed event timeline" description="Chronology derived only from relationships in the reviewed Neo4j projection." action={<div className="header-actions"><button className="button button--dark" onClick={() => state.reload()}><ArrowClockwise size={16} /> Refresh</button><button className="button button--yellow" onClick={exportEvents} disabled={!events.length}><DownloadSimple size={17} /> Export CSV</button></div>} /><div className="timeline-layout"><aside className="timeline-filter-card"><p className="eyebrow">Relationship filters</p><h2>Selected graph</h2>{["all", ...relationTypes].map((item) => <button key={item} className={relationFilter === item ? "active" : ""} onClick={() => setRelationFilter(item)}><span>{item === "all" ? "All reviewed events" : item}</span><small>{item === "all" ? state.data.events.length : state.data.events.filter((event) => event.relation_type === item).length}</small></button>)}<div className="timeline-boundary"><ShieldCheck size={18} /><p>Only confirmed or corrected graph facts appear here.</p></div></aside><section className="timeline-card"><div className="card-heading-row"><div><p className="eyebrow">Observed chronology</p><h2>{events.length} matching events</h2></div><LiveBadge>Neo4j projection</LiveBadge></div>{!events.length ? <EmptyPanel title="No reviewed timeline events" detail="Confirm a relationship and rebuild the graph to populate this chronology." /> : <div className="timeline-list">{events.map((event, index) => <article className="timeline-event timeline-event--communication" key={event.relation_id}><div className="timeline-time"><strong>{formatDate(event.observed_at, false)}</strong><span>{new Date(event.observed_at).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}</span></div><div className="timeline-dot"><i /></div><div className="timeline-event-card"><div><StatusPill tone="safe">{event.relation_type}</StatusPill><span className="mono-note">EVENT {String(index + 1).padStart(2, "0")}</span></div><h3>{labels.get(event.source_entity_id) || shortId(event.source_entity_id)} → {labels.get(event.target_entity_id) || shortId(event.target_entity_id)}</h3><p>{event.source_excerpt}</p><small><BookOpenText size={13} /> Evidence {shortId(event.evidence_id)}</small></div></article>)}</div>}</section></div></div>;
}

export function PatternAlerts({ caseRecord, showToast, onDataChanged }) {
  const loader = useCallback(() => getGraphAnalytics(caseRecord.id), [caseRecord.id]);
  const state = useReloadable(loader, [loader]);
  const [running, setRunning] = useState(false);
  const [busyId, setBusyId] = useState("");
  const run = async () => { setRunning(true); try { const result = await runGraphAnalytics(caseRecord.id); state.setData(result); onDataChanged(); showToast(`${result.alerts.length} explainable graph alerts generated.`); } catch (error) { showToast(error.message, "error"); } finally { setRunning(false); } };
  const review = async (alert) => { setBusyId(alert.id); try { await reviewGraphAlert(caseRecord.id, alert.id, "Reviewed in Phase 7 dashboard."); await state.reload(); onDataChanged(); showToast("Alert marked reviewed; no guilt or finding status was assigned."); } catch (error) { showToast(error.message, "error"); } finally { setBusyId(""); } };
  if (state.loading && !state.data) return <LoadingPanel label="Loading explainable graph alerts…" />;
  if (state.error && state.error.status !== 409) return <ErrorPanel error={state.error} onRetry={state.reload} />;
  const analytics = state.data;
  const alerts = analytics?.alerts || [];
  const alertEntities = new Map((analytics?.rankings || []).map((entity) => [entity.id, entity]));
  const openCount = alerts.filter((alert) => alert.status !== "reviewed").length;
  return <div className="screen"><SectionHeader eyebrow="Step 05 · Explainable graph patterns" title="Pattern review queue" description="Run transparent structural rules over the reviewed graph. Alerts prioritize human attention and are never accusations." action={<div className="header-actions"><button className="button button--dark" onClick={() => state.reload()}><ArrowClockwise size={16} /> Refresh</button><button className="button button--yellow" onClick={run} disabled={running || !analytics}>{running ? <><SpinnerGap className="spin" size={17} /> Running GDS…</> : <><Warning size={17} /> Run analytics</>}</button></div>} />{!analytics ? <EmptyPanel title="Build the case graph first" detail="Confirm evidence facts, run entity resolution, then rebuild the graph from the Network view." /> : <><section className="rule-runner-strip"><div><p className="eyebrow">Latest analytics snapshot</p><h2>{analytics.snapshot.analytics_version}</h2><span>{formatDate(analytics.snapshot.created_at)}</span></div><div className="rule-family-list"><article><code>GRAPH-CONNECT-01</code><strong>High reviewed connectivity</strong><span>Degree over reviewed links</span></article><article><code>GRAPH-BRIDGE-02</code><strong>Potential community bridge</strong><span>Sampled betweenness</span></article><article><code>GRAPH-MULTISOURCE-03</code><strong>Multiple evidence sources</strong><span>Independent source coverage</span></article></div></section><div className="alert-summary-row"><div><span className="summary-number">{String(openCount).padStart(2, "0")}</span><span>Open for review</span></div><div><span className="summary-number">{String(alerts.length - openCount).padStart(2, "0")}</span><span>Reviewed</span></div><div className="summary-message"><ShieldCheck size={22} /><span><strong>Structure, not culpability</strong> {analytics.disclaimer}</span></div></div>{!alerts.length ? <EmptyPanel title="No rules matched" detail="The analytics completed successfully but produced no alert requiring review." /> : <div className="alert-list">{alerts.map((alert) => <article className={`alert-card ${alert.status === "reviewed" ? "alert-card--reviewed" : ""}`} key={alert.id}><div className="alert-card__severity"><Warning size={22} weight="fill" /><span>LEVEL {alert.severity_level}</span><small>{alert.rule_code}</small></div><div className="alert-card__body"><div className="alert-title-row"><h2>{alert.title}</h2><StatusPill tone={alert.status === "reviewed" ? "safe" : "danger"}>{alert.status}</StatusPill></div><p>{alert.explanation}</p><div className="evidence-chips">{Object.entries(alert.evidence_summary || {}).map(([key, value]) => <span key={key}>{key}: {String(value)}</span>)}</div></div><div className="alert-card__actions"><div className="alert-entity-label"><strong>{alertEntities.get(alert.entity_id)?.canonical_value || "Unknown entity"}</strong><small>{alertEntities.get(alert.entity_id)?.entity_type || "ENTITY"} · ID {shortId(alert.entity_id)}</small></div><button className="button button--light" disabled={alert.status === "reviewed" || busyId === alert.id} onClick={() => review(alert)}>{alert.status === "reviewed" ? <><CheckCircle size={17} /> Reviewed</> : <><Check size={17} /> Mark reviewed</>}</button></div></article>)}</div>}</>}</div>;
}
