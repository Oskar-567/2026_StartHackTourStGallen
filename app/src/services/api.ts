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
