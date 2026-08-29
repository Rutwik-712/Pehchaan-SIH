const API_PREFIX = "/api/v1";
const SESSION_KEY = "threadline.phase8.session";

function readSession() {
  try {
    return JSON.parse(window.sessionStorage.getItem(SESSION_KEY) || "null");
  } catch {
    return null;
  }
}

function writeSession(session) {
  if (session) window.sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
  else window.sessionStorage.removeItem(SESSION_KEY);
}

async function errorFromResponse(response) {
  let message = `Request failed (${response.status})`;
  try {
    const payload = await response.json();
    message = typeof payload.detail === "string" ? payload.detail : message;
  } catch {
    // Keep the status-based fallback for non-JSON failures.
  }
  const error = new Error(message);
  error.status = response.status;
  return error;
}

async function parseResponse(response) {
  if (!response.ok) throw await errorFromResponse(response);
  if (response.status === 204) return null;
  return response.json();
}

async function refreshSession() {
  const response = await fetch(`${API_PREFIX}/auth/refresh`, {
    method: "POST",
    credentials: "include",
  });
  const tokens = await parseResponse(response);
  const nextSession = { accessToken: tokens.access_token };
  writeSession(nextSession);
  return nextSession;
}

async function authorizedResponse(path, options = {}, retry = true) {
  const session = readSession();
  if (!session?.accessToken) throw new Error("Authentication required");

  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  headers.set("Authorization", `Bearer ${session.accessToken}`);

  const response = await fetch(`${API_PREFIX}${path}`, { ...options, headers });
  if (response.status === 401 && retry) {
    try {
      await refreshSession();
      return authorizedResponse(path, options, false);
    } catch (error) {
      writeSession(null);
      throw error;
    }
  }
  return response;
}

async function authorizedFetch(path, options = {}) {
  return parseResponse(await authorizedResponse(path, options));
}

function encodeQuery(params) {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  });
  const encoded = query.toString();
  return encoded ? `?${encoded}` : "";
}

export async function login(username, password) {
  const response = await fetch(`${API_PREFIX}/auth/login`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  const tokens = await parseResponse(response);
  writeSession({ accessToken: tokens.access_token });
  return getCurrentUser();
}

export async function logout() {
  try {
    await fetch(`${API_PREFIX}/auth/logout`, { method: "POST", credentials: "include" });
  } finally {
    writeSession(null);
  }
}

export function hasStoredSession() { return Boolean(readSession()?.accessToken); }
export function clearStoredSession() { writeSession(null); }
export function getCurrentUser() { return authorizedFetch("/auth/me"); }
export function getCases() { return authorizedFetch("/cases"); }
export function getCase(caseId) { return authorizedFetch(`/cases/${caseId}`); }
export function getEvidence(caseId) { return authorizedFetch(`/cases/${caseId}/evidence`); }

export function uploadEvidence(caseId, file) {
  const body = new FormData();
  body.append("file", file);
  return authorizedFetch(`/cases/${caseId}/evidence`, { method: "POST", body });
}

export function verifyEvidenceIntegrity(caseId, evidenceId) {
  return authorizedFetch(`/cases/${caseId}/evidence/${evidenceId}/verify-integrity`, { method: "POST" });
}

export async function downloadEvidence(caseId, evidenceId) {
  const response = await authorizedResponse(`/cases/${caseId}/evidence/${evidenceId}/download`);
  if (!response.ok) throw await errorFromResponse(response);
  return { blob: await response.blob(), sha256: response.headers.get("X-Content-SHA256") };
}

export function getProcessingJobs(caseId, evidenceId) {
  return authorizedFetch(`/cases/${caseId}/processing-jobs${encodeQuery({ evidence_id: evidenceId })}`);
}

export function startProcessingJob(caseId, evidenceId) {
  return authorizedFetch(`/cases/${caseId}/evidence/${evidenceId}/processing-jobs`, { method: "POST" });
}

export function retryProcessingJob(caseId, jobId) {
  return authorizedFetch(`/cases/${caseId}/processing-jobs/${jobId}/retry`, { method: "POST" });
}

export function getExtractions(caseId, evidenceId) {
  return authorizedFetch(`/cases/${caseId}/evidence/${evidenceId}/extractions`);
}

export function getExtractedText(caseId, evidenceId) {
  return authorizedFetch(`/cases/${caseId}/evidence/${evidenceId}/extracted-text`);
}

export function getReviewQueue(caseId) { return authorizedFetch(`/cases/${caseId}/review-queue`); }

export function reviewMention(caseId, mentionId, payload) {
  return authorizedFetch(`/cases/${caseId}/mentions/${mentionId}/review`, { method: "POST", body: JSON.stringify(payload) });
}

export function reviewRelation(caseId, relationId, payload) {
  return authorizedFetch(`/cases/${caseId}/relations/${relationId}/review`, { method: "POST", body: JSON.stringify(payload) });
}

export function runEntityResolution(caseId) {
  return authorizedFetch(`/cases/${caseId}/resolution/run`, { method: "POST" });
}

export function getResolutionCandidates(caseId, pendingOnly = true) {
  return authorizedFetch(`/cases/${caseId}/resolution/candidates${encodeQuery({ pending_only: pendingOnly })}`);
}

export function reviewResolutionCandidate(caseId, candidateId, decision, notes = "") {
  return authorizedFetch(`/cases/${caseId}/resolution/candidates/${candidateId}/review`, {
    method: "POST",
    body: JSON.stringify({ decision, notes }),
  });
}

export function rebuildGraph(caseId) { return authorizedFetch(`/cases/${caseId}/graph/rebuild`, { method: "POST" }); }
export function getGraph(caseId) { return authorizedFetch(`/cases/${caseId}/graph`); }
export function runGraphAnalytics(caseId) { return authorizedFetch(`/cases/${caseId}/graph/analytics`, { method: "POST" }); }
export function getGraphAnalytics(caseId) { return authorizedFetch(`/cases/${caseId}/graph/analytics`); }
export function getGraphTimeline(caseId) { return authorizedFetch(`/cases/${caseId}/graph/timeline`); }

export function getEvidencePath(caseId, sourceId, targetId, maxHops = 8) {
  return authorizedFetch(`/cases/${caseId}/graph/path${encodeQuery({ source_id: sourceId, target_id: targetId, max_hops: maxHops })}`);
}

export function reviewGraphAlert(caseId, alertId, notes = "") {
  return authorizedFetch(`/cases/${caseId}/graph/alerts/${alertId}/review`, {
    method: "POST",
    body: JSON.stringify({ notes }),
  });
}

export function getAuditLogs(caseId) { return authorizedFetch(`/cases/${caseId}/audit-logs`); }
export function verifyAuditChain(caseId) { return authorizedFetch(`/cases/${caseId}/audit-chain/verify`); }

export function queryAssistant(caseId, question) {
  return authorizedFetch(`/cases/${caseId}/assistant/query`, { method: "POST", body: JSON.stringify({ question }) });
}
export function getAssistantQueries(caseId) { return authorizedFetch(`/cases/${caseId}/assistant/queries`); }
export function submitAssistantFeedback(queryId, rating, notes = "") {
  return authorizedFetch(`/assistant/queries/${queryId}/feedback`, { method: "POST", body: JSON.stringify({ rating, notes }) });
}
export function createCaseReport(caseId, title, scopeNote = "") {
  return authorizedFetch(`/cases/${caseId}/reports`, { method: "POST", body: JSON.stringify({ title, scope_note: scopeNote }) });
}
export function getCaseReports(caseId) { return authorizedFetch(`/cases/${caseId}/reports`); }
export function getCaseReport(reportId) { return authorizedFetch(`/reports/${reportId}`); }
export function decideCaseReport(reportId, decision, notes = "") {
  return authorizedFetch(`/reports/${reportId}/decision`, { method: "POST", body: JSON.stringify({ decision, notes }) });
}
export async function downloadCaseReport(reportId) {
  const response = await authorizedResponse(`/reports/${reportId}/download`);
  if (!response.ok) throw await errorFromResponse(response);
  return { blob: await response.blob(), sha256: response.headers.get("X-Content-SHA256") };
}
