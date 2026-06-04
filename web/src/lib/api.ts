import type {
  AutoLabelResponse,
  EvolveOnlineResponse,
  FeedbackResponse,
  HarnessActionResponse,
  HarnessCandidate,
  HarnessFailureCase,
  HarnessListResponse,
  Nl2SqlResponse,
  PageResponse,
} from "@/types";

async function requestJson<T>(input: string, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  const text = await response.text();
  const data = text ? (JSON.parse(text) as T) : ({} as T);
  if (!response.ok) {
    throw new Error(`请求失败(${response.status})`);
  }
  return data;
}

export function runNl2Sql(query: string): Promise<Nl2SqlResponse> {
  return requestJson<Nl2SqlResponse>("/nl2sql", {
    method: "POST",
    body: JSON.stringify({ query }),
  });
}

export async function listFailureCases(status?: string, limit = 50): Promise<HarnessFailureCase[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (status) params.set("status", status);
  const result = await requestJson<HarnessListResponse<HarnessFailureCase>>(`/admin/harness/failure-cases?${params}`);
  return result.items ?? [];
}

export async function listCandidates(status?: string, limit = 50): Promise<HarnessCandidate[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (status) params.set("status", status);
  const result = await requestJson<HarnessListResponse<HarnessCandidate>>(`/admin/harness/candidates?${params}`);
  return result.items ?? [];
}

export function labelFailureCase(failureCaseId: number, correctSql: string, note = "", labelType = "correct_sql"): Promise<HarnessActionResponse> {
  return requestJson<HarnessActionResponse>(`/admin/harness/failure-cases/${failureCaseId}/label`, {
    method: "POST",
    body: JSON.stringify({ correct_sql: correctSql, note, label_type: labelType }),
  });
}

export function analyzeFailures(limit = 200): Promise<HarnessActionResponse> {
  return requestJson<HarnessActionResponse>(`/admin/harness/analyze-failures?limit=${limit}&sync_failures=true`, {
    method: "POST",
  });
}

export function autoLabelFailures(limit = 50, generateModel = "", evalModel = ""): Promise<AutoLabelResponse> {
  const params = new URLSearchParams({ limit: String(limit), sync_failures: "true" });
  if (generateModel) params.set("generate_model", generateModel);
  if (evalModel) params.set("eval_model", evalModel);
  return requestJson<AutoLabelResponse>(`/admin/harness/auto-label-failures?${params}`, {
    method: "POST",
  });
}

export function evolveOnline(limit = 200): Promise<EvolveOnlineResponse> {
  const params = new URLSearchParams({ limit: String(limit), sync_failures: "true" });
  return requestJson<EvolveOnlineResponse>(`/admin/harness/evolve-online?${params}`, {
    method: "POST",
  });
}

export function reviewCandidate(candidateId: number, action: "approve" | "reject", note = ""): Promise<HarnessActionResponse> {
  return requestJson<HarnessActionResponse>(`/admin/harness/candidates/${candidateId}/review`, {
    method: "POST",
    body: JSON.stringify({ action, note }),
  });
}

export function publishApproved(version: string): Promise<HarnessActionResponse> {
  return requestJson<HarnessActionResponse>("/admin/harness/publish", {
    method: "POST",
    body: JSON.stringify({ version }),
  });
}

export function submitFeedback(requestId: string, rating: "up" | "down", reason = ""): Promise<FeedbackResponse> {
  return requestJson<FeedbackResponse>("/admin/harness/feedback", {
    method: "POST",
    body: JSON.stringify({ request_id: requestId, rating, reason }),
  });
}

export function fetchPage(sql: string, page: number, pageSize = 20): Promise<PageResponse> {
  return requestJson<PageResponse>("/execute/page", {
    method: "POST",
    body: JSON.stringify({ sql, page, page_size: pageSize }),
  });
}
