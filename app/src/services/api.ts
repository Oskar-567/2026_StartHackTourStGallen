/**
 * Single place for all HTTP calls to the Django server.
 * EXPO_PUBLIC_API_URL is inlined at build time: app/.env locally, the EAS "production"
 * environment for EAS builds, EAS updates and the web export.
 */
export const API_URL = (process.env.EXPO_PUBLIC_API_URL ?? "http://localhost:8000").replace(
  /\/+$/,
  "",
);

// Render's free tier needs up to about a minute to wake up from sleep.
const REQUEST_TIMEOUT_MS = 70_000;

export class ApiError extends Error {
  readonly status: number;
  readonly body: unknown;

  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const response = await fetch(`${API_URL}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: "application/json",
        ...(init.body ? { "Content-Type": "application/json" } : {}),
        ...(init.headers as Record<string, string> | undefined),
      },
    });
    const body: unknown = await response.json().catch(() => null);

    if (!response.ok) {
      throw new ApiError(
        response.status,
        body,
        `${init.method ?? "GET"} ${path} failed with status ${response.status}`,
      );
    }
    return body as T;
  } catch (error) {
    if (error instanceof Error && error.name === "AbortError") {
      throw new Error(`Request to ${API_URL}${path} timed out`);
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

export type Health = {
  status: "ok" | "error";
  database: "ok" | "error";
  version: string;
};

/** A 503 still carries a Health body (server up, database down), so it is a valid result. */
export async function fetchHealth(): Promise<Health> {
  try {
    return await request<Health>("/health/");
  } catch (error) {
    if (error instanceof ApiError && error.status === 503 && error.body) {
      return error.body as Health;
    }
    throw error;
  }
}

// --- Approval queue (step-ups) ---------------------------------------------

export type Evidence = {
  field: string;
  value: unknown;
  note: string;
};

export type StepUpItem = {
  item_name: string;
  quantity: number;
  unit_price: number;
  item_details: string | null;
};

/** A purchase the engine paused for the customer: `GET /api/step-ups/`. */
export type StepUp = {
  id: number;
  authorization_id: string;
  scenario_id: string;
  merchant_name: string | null;
  purchase_description: string | null;
  items: StepUpItem[];
  /** Decimal serialized as a string, e.g. "189.00". */
  billing_amount_chf: string;
  reason_codes: string[];
  customer_message: string;
  evidence: Evidence[];
  /** When the customer's answer window closes (ISO timestamp). */
  respond_by: string | null;
  seconds_remaining: number;
};

export type StepUpAnswer = "approve" | "decline";

export function fetchStepUps(): Promise<StepUp[]> {
  return request<StepUp[]>("/api/step-ups/");
}

export function resolveStepUp(id: number, decision: StepUpAnswer, message = ""): Promise<StepUp> {
  return request<StepUp>(`/api/step-ups/${id}/resolve/`, {
    method: "POST",
    body: JSON.stringify({ decision, message }),
  });
}

/** The first readable message from a DRF error body, for showing to the customer. */
export function errorMessage(error: unknown): string {
  if (error instanceof ApiError && error.body && typeof error.body === "object") {
    const body = error.body as Record<string, unknown>;
    const first = body.detail ?? body.non_field_errors ?? Object.values(body)[0];
    if (typeof first === "string") return first;
    if (Array.isArray(first) && typeof first[0] === "string") return first[0];
  }
  return error instanceof Error ? error.message : String(error);
}

// --- Wallet policy (mandates) ------------------------------------------------

export type HardRule = {
  field: string;
  operator: "<" | "<=" | "=" | "!=" | ">" | ">=" | "in" | "not_in";
  value: number | string | string[];
  currency?: string | null;
  scope?: "purchase" | "period" | null;
  period_days?: number | null;
};

export type UncertaintyPolicy = "ask" | "decline" | "approve";

/** `GET /api/mandates/` — the customer's wallet policy as stored by our server. */
export type Mandate = {
  id: number;
  instruction: string;
  hard_rules: HardRule[];
  uncertainty_policy: UncertaintyPolicy;
  guidance: string[];
  open_questions: string[];
  status: "draft" | "active" | "revoked";
  draft_id: string;
  mandate_id: string;
  confirmed_by: string;
  confirmed_at: string | null;
  created_at: string;
  updated_at: string;
};

/** Additive only: existing rules must be resent unchanged; the server refuses anything weaker. */
export type MandateTightening = {
  hard_rules?: HardRule[];
  uncertainty_policy?: UncertaintyPolicy;
};

export function fetchMandates(): Promise<Mandate[]> {
  return request<Mandate[]>("/api/mandates/");
}

export function confirmMandate(id: number, confirmedBy = "customer (app)"): Promise<Mandate> {
  return request<Mandate>(`/api/mandates/${id}/confirm/`, {
    method: "POST",
    body: JSON.stringify({ confirmed_by: confirmedBy }),
  });
}

export function tightenMandate(id: number, change: MandateTightening): Promise<Mandate> {
  return request<Mandate>(`/api/mandates/${id}/tighten/`, {
    method: "POST",
    body: JSON.stringify(change),
  });
}

export function revokeMandate(id: number): Promise<Mandate> {
  return request<Mandate>(`/api/mandates/${id}/revoke/`, { method: "POST" });
}
