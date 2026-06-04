import type {
  HarnessActionResponse,
  HarnessCandidate,
  HarnessFailureCase,
  HarnessListResponse,
  Nl2SqlResponse,
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

export async function listFailureCases(limit = 20): Promise<HarnessFailureCase[]> {
  const result = await requestJson<HarnessListResponse<HarnessFailureCase>>(`/admin/harness/failure-cases?limit=${limit}`);
  return result.items ?? [];
}

export async function listCandidates(limit = 20): Promise<HarnessCandidate[]> {
  const result = await requestJson<HarnessListResponse<HarnessCandidate>>(`/admin/harness/candidates?limit=${limit}`);
  return result.items ?? [];
}

export function analyzeFailures(limit = 50): Promise<HarnessActionResponse> {
  return requestJson<HarnessActionResponse>(`/admin/harness/analyze-failures?limit=${limit}&sync_failures=true`, {
    method: "POST",
  });
}

export function publishApproved(version: string): Promise<HarnessActionResponse> {
  return requestJson<HarnessActionResponse>("/admin/harness/publish", {
    method: "POST",
    body: JSON.stringify({ version }),
  });
}
