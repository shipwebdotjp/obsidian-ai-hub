import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  cancelHitlRun,
  clearToken,
  deleteMemory,
  getMemory,
  getToken,
  health,
  listMemories,
  renderCopilotProfile,
  reviewMemory,
  setToken,
  submitHitlAnswer,
  updateSummary,
  generateSummary,
} from "./client";

const TOKEN_KEY = "obsidian-ai-hub:review-token";

function makeResponse(options: {
  status?: number;
  body?: unknown;
  text?: string;
}): Response {
  const status = options.status ?? 200;
  const ok = status >= 200 && status < 300;
  const bodyText = options.text ?? (options.body !== undefined ? JSON.stringify(options.body) : "");
  const headers = new Headers();
  if (bodyText) headers.set("Content-Type", "application/json");
  return {
    status,
    ok,
    statusText:
      status === 200
        ? "OK"
        : status === 204
        ? "No Content"
        : status === 401
        ? "Unauthorized"
        : status === 400
        ? "Bad Request"
        : status === 422
        ? "Unprocessable Entity"
        : status === 500
        ? "Internal Server Error"
        : "Error",
    headers,
    json: async () => (bodyText ? JSON.parse(bodyText) : null),
    text: async () => bodyText,
  } as unknown as Response;
}

describe("api/client", () => {
  const fetchMock = vi.fn();

  beforeEach(() => {
    sessionStorage.clear();
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  describe("token management", () => {
    it("returns an empty string when no token is stored", () => {
      expect(getToken()).toBe("");
    });

    it("setToken stores the token in sessionStorage", () => {
      setToken("abc123");
      expect(sessionStorage.getItem(TOKEN_KEY)).toBe("abc123");
    });

    it("setToken('') removes the existing token", () => {
      setToken("abc123");
      setToken("");
      expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
    });

    it("clearToken removes the token from sessionStorage", () => {
      setToken("abc123");
      clearToken();
      expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
    });
  });

  describe("request building", () => {
    it("generateSummary POSTs the selected period target", async () => {
      fetchMock.mockResolvedValue(makeResponse({ body: { summary_id: "sum-1" } }));
      await generateSummary({ period_type: "month", target_month: "2026-07" });
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/api/v1/summary-dashboard/summaries/generate");
      expect(init.method).toBe("POST");
      expect(JSON.parse(init.body as string)).toEqual({ period_type: "month", target_month: "2026-07" });
    });
    it("listMemories builds a query string and GETs /api/v1/memories", async () => {
      fetchMock.mockResolvedValue(
        makeResponse({ body: { items: [], total: 0 } }),
      );
      await listMemories({
        status: "candidate",
        kind: "fact",
        q: "hello world",
      });
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe(
        "/api/v1/memories?status=candidate&kind=fact&q=hello+world",
      );
      expect(init.method ?? "GET").toBe("GET");
      expect(new Headers(init.headers).get("Accept")).toBe("application/json");
      expect(new Headers(init.headers).get("Content-Type")).toBeNull();
      expect(init.body).toBeUndefined();
    });

    it("listMemories with no params calls /api/v1/memories without a query string", async () => {
      fetchMock.mockResolvedValue(
        makeResponse({ body: { items: [], total: 0 } }),
      );
      await listMemories({});
      expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/memories");
    });

    it("listMemories drops undefined and empty params", async () => {
      fetchMock.mockResolvedValue(
        makeResponse({ body: { items: [], total: 0 } }),
      );
      await listMemories({
        status: "candidate",
        kind: undefined,
        topic: "",
        q: undefined,
      });
      expect(fetchMock.mock.calls[0][0]).toBe(
        "/api/v1/memories?status=candidate",
      );
    });

    it("reviewMemory POSTs action and new_content as JSON", async () => {
      fetchMock.mockResolvedValue(
        makeResponse({ body: { memory: { id: "m1" } } }),
      );
      await reviewMemory("m1", "edit", "updated body");
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/api/v1/memories/m1/review");
      expect(init.method).toBe("POST");
      expect(new Headers(init.headers).get("Content-Type")).toBe(
        "application/json",
      );
      expect(JSON.parse(init.body as string)).toEqual({
        action: "edit",
        new_content: "updated body",
      });
    });

    it("reviewMemory omits new_content when undefined", async () => {
      fetchMock.mockResolvedValue(
        makeResponse({ body: { memory: { id: "m1" } } }),
      );
      await reviewMemory("m1", "approve");
      expect(JSON.parse(fetchMock.mock.calls[0][1].body as string)).toEqual({
        action: "approve",
      });
    });

    it("reviewMemory encodes special characters in memoryId", async () => {
      fetchMock.mockResolvedValue(
        makeResponse({ body: { memory: { id: "m/1" } } }),
      );
      await reviewMemory("m/1", "approve");
      expect(fetchMock.mock.calls[0][0]).toBe(
        "/api/v1/memories/m%2F1/review",
      );
    });

    it("getMemory uses GET on /api/v1/memories/:id", async () => {
      fetchMock.mockResolvedValue(makeResponse({ body: { id: "m1" } }));
      await getMemory("m1");
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/api/v1/memories/m1");
      expect(init.method ?? "GET").toBe("GET");
    });

    it("submitHitlAnswer POSTs to the question-specific path", async () => {
      fetchMock.mockResolvedValue(
        makeResponse({ body: { success: true } }),
      );
      await submitHitlAnswer("run-1", "approve", "yes", "looks good");
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe(
        "/api/v1/hitl/runs/run-1/questions/approve/answer",
      );
      expect(init.method).toBe("POST");
      expect(JSON.parse(init.body as string)).toEqual({
        answer: "yes",
        comment: "looks good",
      });
    });

    it("cancelHitlRun POSTs without a body and does not set Content-Type", async () => {
      fetchMock.mockResolvedValue(
        makeResponse({ body: { success: true } }),
      );
      await cancelHitlRun("run-1");
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/api/v1/hitl/runs/run-1/cancel");
      expect(init.method).toBe("POST");
      expect(new Headers(init.headers).get("Content-Type")).toBeNull();
    });

    it("deleteMemory uses DELETE on /api/v1/memories/:id", async () => {
      fetchMock.mockResolvedValue(
        makeResponse({ status: 204, text: "" }),
      );
      await deleteMemory("m1");
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/api/v1/memories/m1");
      expect(init.method).toBe("DELETE");
    });

    it("renderCopilotProfile POSTs without a body", async () => {
      fetchMock.mockResolvedValue(
        makeResponse({ body: { updated_files: [] } }),
      );
      await renderCopilotProfile();
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/api/v1/copilot-profile/render");
      expect(init.method).toBe("POST");
      expect(new Headers(init.headers).get("Content-Type")).toBeNull();
    });

    it("updateSummary uses PATCH with JSON body", async () => {
      fetchMock.mockResolvedValue(
        makeResponse({ body: { summary_id: "s1" } }),
      );
      await updateSummary("s1", { summary: "edited" } as never);
      const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
      expect(url).toBe("/api/v1/summary-dashboard/summaries/s1");
      expect(init.method).toBe("PATCH");
      expect(JSON.parse(init.body as string)).toEqual({ summary: "edited" });
    });

    it("health calls /health (not under /api)", async () => {
      fetchMock.mockResolvedValue(
        makeResponse({ body: { status: "ok", auth_required: false } }),
      );
      const res = await health();
      expect(fetchMock.mock.calls[0][0]).toBe("/health");
      expect(res).toEqual({ status: "ok", auth_required: false });
    });
  });

  describe("Authorization header", () => {
    it("does not set Authorization when no token is stored", async () => {
      fetchMock.mockResolvedValue(makeResponse({ body: {} }));
      await listMemories({});
      const headers = new Headers(fetchMock.mock.calls[0][1].headers);
      expect(headers.get("Authorization")).toBeNull();
    });

    it("sets Authorization: Bearer <token> when a token is stored", async () => {
      setToken("secret-token");
      fetchMock.mockResolvedValue(makeResponse({ body: {} }));
      await listMemories({});
      const headers = new Headers(fetchMock.mock.calls[0][1].headers);
      expect(headers.get("Authorization")).toBe("Bearer secret-token");
    });

    it("reflects the latest token on each call", async () => {
      setToken("first");
      fetchMock.mockResolvedValue(makeResponse({ body: {} }));
      await listMemories({});
      expect(
        new Headers(fetchMock.mock.calls[0][1].headers).get("Authorization"),
      ).toBe("Bearer first");

      setToken("second");
      fetchMock.mockResolvedValue(makeResponse({ body: {} }));
      await listMemories({});
      expect(
        new Headers(fetchMock.mock.calls[1][1].headers).get("Authorization"),
      ).toBe("Bearer second");
    });
  });

  describe("error handling", () => {
    it("throws ApiError(401) and clears the token on 401 responses", async () => {
      setToken("expired");
      fetchMock.mockResolvedValue(makeResponse({ status: 401 }));
      await expect(listMemories({})).rejects.toMatchObject({
        status: 401,
        message: "Authentication failed. Please check your token.",
      });
      const err = await listMemories({}).catch((e) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(sessionStorage.getItem(TOKEN_KEY)).toBeNull();
    });

    it("extracts detail as a string from the error body", async () => {
      fetchMock.mockResolvedValue(
        makeResponse({ status: 400, body: { detail: "Bad input" } }),
      );
      const err = await listMemories({}).catch((e) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err.status).toBe(400);
      expect(err.message).toBe("Bad input");
      expect((err as ApiError).body).toEqual({ detail: "Bad input" });
    });

    it("extracts detail.message from an object body", async () => {
      fetchMock.mockResolvedValue(
        makeResponse({
          status: 422,
          body: { detail: { message: "Validation failed", code: "E001" } },
        }),
      );
      const err = await listMemories({}).catch((e) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err.status).toBe(422);
      expect(err.message).toBe("Validation failed");
    });

    it("falls back to statusText when the body is not JSON", async () => {
      fetchMock.mockResolvedValue(
        makeResponse({ status: 500, text: "Internal Server Error" }),
      );
      const err = await listMemories({}).catch((e) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err.status).toBe(500);
      expect(err.message).toBe("Internal Server Error");
    });

    it("falls back to statusText when the body has no detail field", async () => {
      fetchMock.mockResolvedValue(
        makeResponse({ status: 400, body: { error: "x" } }),
      );
      const err = await listMemories({}).catch((e) => e);
      expect(err).toBeInstanceOf(ApiError);
      expect(err.status).toBe(400);
      expect(err.message).toBe("Bad Request");
    });
  });

  describe("204 No Content", () => {
    it("returns undefined for 204 responses", async () => {
      fetchMock.mockResolvedValue(makeResponse({ status: 204, text: "" }));
      const result = await deleteMemory("m1");
      expect(result).toBeUndefined();
    });
  });
});
