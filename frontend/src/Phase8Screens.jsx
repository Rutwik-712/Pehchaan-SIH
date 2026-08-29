import { useCallback, useEffect, useMemo, useState } from "react";
import {
  ArrowClockwise,
  CheckCircle,
  DownloadSimple,
  FileText,
  LinkSimple,
  PaperPlaneTilt,
  ShieldCheck,
  Sparkle,
  SpinnerGap,
  Warning,
  XCircle,
} from "@phosphor-icons/react";
import {
  createCaseReport,
  decideCaseReport,
  downloadCaseReport,
  downloadEvidence,
  getAssistantQueries,
  getCaseReport,
  getCaseReports,
  queryAssistant,
  submitAssistantFeedback,
} from "./api.js";
import { can, EmptyPanel, ErrorPanel, formatDate, LoadingPanel, SectionHeader, StatusPill } from "./ui.jsx";

const ACTIVE_REPORTS = new Set(["queued", "generating"]);
const suggestions = [
  "Summarize the reviewed evidence",
  "Which reviewed relationships involve this case?",
  "What reviewed phone numbers or vehicles are present?",
];

function useRemote(loader) {
  const [state, setState] = useState({ loading: true, data: null, error: null });
  const load = useCallback(async () => {
    setState((value) => ({ ...value, loading: true, error: null }));
    try { const data = await loader(); setState({ loading: false, data, error: null }); return data; }
    catch (error) { setState((value) => ({ ...value, loading: false, error })); throw error; }
  }, [loader]);
  useEffect(() => { load().catch(() => {}); }, [load]);
  return { ...state, reload: load, setData: (data) => setState({ loading: false, data, error: null }) };
}

export function EvidenceAssistant({ caseRecord, showToast }) {
  const loader = useCallback(() => getAssistantQueries(caseRecord.id), [caseRecord.id]);
  const state = useRemote(loader);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [selectedId, setSelectedId] = useState("");
  const selected = useMemo(() => (state.data || []).find((item) => item.id === selectedId) || state.data?.[0] || null, [state.data, selectedId]);

  const ask = async (event) => {
    event?.preventDefault();
    if (question.trim().length < 3) return;
    setBusy(true);
    try {
      const result = await queryAssistant(caseRecord.id, question.trim());
      state.setData([result, ...(state.data || []).filter((item) => item.id !== result.id)]);
      setSelectedId(result.id); setQuestion("");
      showToast(result.evidence_sufficient ? `Answer grounded in ${result.citations.length} reviewed citation${result.citations.length === 1 ? "" : "s"}.` : "The assistant correctly reported insufficient reviewed evidence.");
    } catch (error) { showToast(error.message, "error"); }
    finally { setBusy(false); }
  };
  const openSource = async (citation) => {
    try {
      const { blob } = await downloadEvidence(caseRecord.id, citation.evidence_id);
      const url = URL.createObjectURL(blob); const anchor = document.createElement("a");
      anchor.href = url; anchor.download = citation.source_label; anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (error) { showToast(error.message, "error"); }
  };
  const feedback = async (rating) => {
    if (!selected) return;
    try { const result = await submitAssistantFeedback(selected.id, rating); state.setData((state.data || []).map((item) => item.id === result.id ? result : item)); showToast("Assistant feedback recorded in the audit trail."); }
    catch (error) { showToast(error.message, "error"); }
  };

  if (state.loading && !state.data) return <LoadingPanel label="Loading case-scoped assistant history…" />;
  if (state.error && !state.data) return <ErrorPanel error={state.error} onRetry={state.reload} />;
  return <div className="screen">
    <SectionHeader eyebrow="Step 06 · Grounded local explanation" title="Evidence assistant" description="Ask about confirmed case facts. Qwen is used locally when enabled; deterministic grounded output remains available offline." action={<StatusPill tone="safe">Citations enforced</StatusPill>} />
    <div className="assistant-layout">
      <section className="assistant-thread">
        <div className="assistant-question-list"><div className="card-heading-row compact"><div><p className="eyebrow">Audited history</p><h2>Case questions</h2></div><button className="icon-button" onClick={() => state.reload()} aria-label="Refresh assistant history"><ArrowClockwise size={16} /></button></div>
          {!state.data?.length ? <EmptyPanel title="No questions yet" detail="Ask a question that can be answered from reviewed case evidence." /> : state.data.map((item) => <button className={`assistant-question ${selected?.id === item.id ? "active" : ""}`} key={item.id} onClick={() => setSelectedId(item.id)}><Sparkle size={16} /><span><strong>{item.question}</strong><p>{formatDate(item.created_at)} · {item.citations.length} citations · {item.provider}</p></span></button>)}
        </div>
        <div className="assistant-answer">
          <div className="assistant-answer__body">{busy ? <div className="assistant-loading"><SpinnerGap className="spin" size={20} /> Retrieving reviewed evidence…</div> : selected ? <>
            <div className="assistant-meta"><span>{selected.evidence_sufficient ? `${selected.coverage_percent}% evidence coverage` : "Evidence insufficient"}</span><small>{selected.model_id}</small></div>
            <p className="assistant-response-text">{selected.answer_text}</p>
            <div className="coverage-note"><ShieldCheck size={18} /><span><strong>Coverage and limitations</strong><br />{selected.limitations.join(" ")}</span></div>
            <div className="assistant-feedback"><span>Was this grounded?</span>{["correct", "incomplete", "unsupported", "access_problem"].map((rating) => <button className={selected.feedback === rating ? "active" : ""} key={rating} onClick={() => feedback(rating)}>{rating.replace("_", " ")}</button>)}</div>
          </> : <EmptyPanel title="Select or ask a question" detail="Answers use only confirmed or corrected extraction records." />}</div>
          <form className="assistant-composer" onSubmit={ask}><input value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask about reviewed persons, identifiers, places or links…" aria-label="Assistant question" /><button disabled={busy || question.trim().length < 3} aria-label="Ask assistant"><PaperPlaneTilt size={18} /></button></form>
          <div className="prompt-suggestions">{suggestions.map((item) => <button key={item} onClick={() => setQuestion(item)}>{item}</button>)}</div>
        </div>
      </section>
      <aside className="citation-panel"><p className="eyebrow">Supporting evidence</p><h2>{selected?.citations.length || 0} citations</h2>{selected?.citations.map((item) => <article key={item.id}><span>{item.citation_number}</span><div><strong>{item.source_label} · page {item.page_number}</strong><p>{item.excerpt}</p><button onClick={() => openSource(item)}><LinkSimple size={13} /> Open protected source</button></div></article>)}<div className="citation-footer"><ShieldCheck size={17} /><small>Assistant output is analytical support only and never determines guilt.</small></div></aside>
    </div>
  </div>;
}

export function CaseBrief({ caseRecord, user, showToast }) {
  const loader = useCallback(() => getCaseReports(caseRecord.id), [caseRecord.id]);
  const state = useRemote(loader);
  const [title, setTitle] = useState(`${caseRecord.id} reviewed evidence brief`);
  const [scope, setScope] = useState("All currently reviewed case evidence");
  const [busy, setBusy] = useState(false);
  const [selectedId, setSelectedId] = useState("");
  const selected = useMemo(() => (state.data || []).find((item) => item.id === selectedId) || state.data?.[0] || null, [state.data, selectedId]);
  useEffect(() => {
    if (!state.data?.some((item) => ACTIVE_REPORTS.has(item.status))) return undefined;
    const timer = window.setInterval(async () => {
      const updated = await Promise.all(state.data.map((item) => ACTIVE_REPORTS.has(item.status) ? getCaseReport(item.id) : item));
      state.setData(updated);
    }, 2000);
    return () => window.clearInterval(timer);
  }, [state.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const generate = async (event) => {
    event.preventDefault(); setBusy(true);
    try { const report = await createCaseReport(caseRecord.id, title.trim(), scope.trim()); state.setData([report, ...(state.data || [])]); setSelectedId(report.id); showToast(`Case brief v${report.version} queued for local generation.`); }
    catch (error) { showToast(error.message, "error"); } finally { setBusy(false); }
  };
  const decide = async (decision) => {
    try { const updated = await decideCaseReport(selected.id, decision, "Reviewed through Phase 8 dashboard"); state.setData((state.data || []).map((item) => item.id === updated.id ? updated : item)); showToast(`Report ${updated.status}.`); }
    catch (error) { showToast(error.message, "error"); }
  };
  const download = async () => {
    try { const { blob } = await downloadCaseReport(selected.id); const url = URL.createObjectURL(blob); const anchor = document.createElement("a"); anchor.href = url; anchor.download = `${caseRecord.id}-case-brief-v${selected.version}.pdf`; anchor.click(); window.setTimeout(() => URL.revokeObjectURL(url), 1000); showToast("Protected PDF download started."); }
    catch (error) { showToast(error.message, "error"); }
  };
  if (state.loading && !state.data) return <LoadingPanel label="Loading immutable report versions…" />;
  if (state.error && !state.data) return <ErrorPanel error={state.error} onRetry={state.reload} />;
  const content = selected?.content || {}; const metrics = content.metrics || {};
  return <div className="screen">
    <SectionHeader eyebrow="Step 07 · Versioned report" title="Cited case brief" description="Generate an immutable PDF snapshot from reviewed evidence, then route it to an SP-level approver." action={<StatusPill tone="safe">Watermarked + hashed</StatusPill>} />
    <div className="brief-layout">
      <article className="brief-document"><div className="brief-cover-strip"><span>{selected?.classification || caseRecord.classification}</span><span>{selected ? `VERSION ${selected.version} · ${selected.status.toUpperCase()}` : "NO VERSION GENERATED"}</span></div>
        <div className="brief-heading"><p>SOURCE-BACKED INVESTIGATION BRIEF</p><h2>{selected?.title || "Generate the first reviewed-evidence brief"}</h2><span>{caseRecord.id} · {caseRecord.jurisdiction}{selected ? ` · ${formatDate(selected.created_at)}` : ""}</span></div>
        {selected ? <><section><h3>01 · CASE AND SCOPE</h3><p>{selected.scope_note || "All currently reviewed case evidence"}</p></section><section><h3>02 · EVIDENCE SNAPSHOT</h3><div className="brief-stat-grid"><div><strong>{metrics.source_count || 0}</strong><span>Sources</span></div><div><strong>{metrics.reviewed_entity_count || 0}</strong><span>Entities</span></div><div><strong>{metrics.reviewed_relationship_count || 0}</strong><span>Links</span></div><div><strong>{metrics.pending_review_count || 0}</strong><span>Pending</span></div></div></section><section><h3>03 · CONFIRMED RELATIONSHIPS</h3>{content.relationships?.length ? <ul>{content.relationships.slice(0, 12).map((item, index) => <li key={`${item.citation}-${index}`}>{item.subject} — {item.relation.replaceAll("_", " ")} — {item.object} <sup>[{item.citation}]</sup></li>)}</ul> : <p>No reviewed relationships were available at generation time.</p>}</section><section><h3>04 · LIMITATIONS</h3><ul>{selected.limitations.map((item) => <li key={item}>{item}</li>)}</ul></section><footer><span>SHA-256 {selected.sha256 || "pending"}</span><span>This brief does not determine guilt.</span></footer></> : <section><EmptyPanel title="No report version exists" detail="Use the controls to generate an immutable reviewed-evidence snapshot." /></section>}
      </article>
      <aside className="brief-controls"><p className="eyebrow">Generation controls</p><h2>Report versions</h2><form className="brief-form" onSubmit={generate}><label><span>Title</span><input value={title} onChange={(event) => setTitle(event.target.value)} /></label><label><span>Scope note</span><textarea value={scope} onChange={(event) => setScope(event.target.value)} /></label><button className="button button--yellow button--wide" disabled={busy || title.trim().length < 3}>{busy ? <SpinnerGap className="spin" size={16} /> : <FileText size={16} />} Generate new version</button></form>
        <div className="report-version-list">{state.data?.map((item) => <button className={selected?.id === item.id ? "active" : ""} key={item.id} onClick={() => setSelectedId(item.id)}><span>v{item.version} · {item.title}</span><StatusPill tone={item.status === "approved" ? "safe" : item.status === "failed" || item.status === "rejected" ? "danger" : "yellow"}>{item.status}</StatusPill></button>)}</div>
        {selected && <div className="brief-actions"><button className="button button--dark button--wide" onClick={download} disabled={!selected.sha256 || ACTIVE_REPORTS.has(selected.status)}><DownloadSimple size={16} /> Download PDF</button>{can(user, "brief:approve") && selected.status === "completed" && <><button className="button button--yellow button--wide" onClick={() => decide("approve")}><CheckCircle size={16} /> Approve brief</button><button className="button button--dark button--wide" onClick={() => decide("reject")}><XCircle size={16} /> Reject brief</button></>}</div>}
        <div className="safety-banner"><Warning size={18} /><span>Each version is a fixed evidence snapshot. Regenerate to include later reviews; existing files never silently change.</span></div>
      </aside>
    </div>
  </div>;
}
