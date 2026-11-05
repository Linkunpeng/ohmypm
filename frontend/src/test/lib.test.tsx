import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { TypeDistribution } from "@/components/TypeDistribution";
import { api, ApiError } from "@/lib/api";
import { assetUrl, formatBytes, safeUrl, timeAgo } from "@/lib/format";
import { highlight } from "@/pages/SearchPage";

describe("format helpers", () => {
  it("maps asset URIs and rejects malformed ones", () => {
    expect(assetUrl("ohmypm-asset://9b1f7c1e-1111-4222-8333-444455556666")).toBe(
      "/api/assets/9b1f7c1e-1111-4222-8333-444455556666",
    );
    expect(assetUrl("ohmypm-asset://../../etc/passwd")).toBe("");
    expect(assetUrl("https://example.com/a.png")).toBe("https://example.com/a.png");
  });

  it("allows only safe URL schemes", () => {
    expect(safeUrl("javascript:alert(1)")).toBe("");
    expect(safeUrl(" JAVASCRIPT:alert(1)")).toBe("");
    expect(safeUrl("data:text/html,x")).toBe("");
    expect(safeUrl("file:///etc/passwd")).toBe("");
    expect(safeUrl("https://example.com")).toBe("https://example.com");
    expect(safeUrl("mailto:a@b.c")).toBe("mailto:a@b.c");
    expect(safeUrl("#section")).toBe("#section");
    expect(safeUrl("docs/readme.md")).toBe("docs/readme.md");
  });

  it("formats sizes and relative times", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2.0 KiB");
    const now = new Date("2026-11-04T12:00:00Z");
    expect(timeAgo("2026-11-04T11:59:50Z", now)).toBe("just now");
    expect(timeAgo("2026-11-04T10:00:00Z", now)).toMatch(/2 hours ago/);
    expect(timeAgo(null)).toBe("never");
  });
});

describe("search highlighting", () => {
  it("marks every term case-insensitively and literally", () => {
    render(<p data-testid="p">{highlight("OpenCV 链接失败 opencv (a+b)", ["opencv", '"链接"', "(a+b)"])}</p>);
    const marks = screen.getByTestId("p").querySelectorAll("mark");
    expect(Array.from(marks).map((m) => m.textContent)).toEqual(["OpenCV", "链接", "opencv", "(a+b)"]);
  });
});

describe("TypeDistribution", () => {
  it("lists every type with its count in a table", () => {
    render(<TypeDistribution counts={{ milestone: 3, issue: 1, experiment: 2 }} />);
    const table = screen.getByRole("table", { name: "Records per type" });
    const rows = table.querySelectorAll("tbody tr");
    expect(rows).toHaveLength(7);
    expect(screen.getByRole("rowheader", { name: "Milestone" }).parentElement?.textContent).toContain("3");
    expect(screen.getByRole("rowheader", { name: "Experiment" })).toBeInTheDocument();
  });

  it("shows an empty state", () => {
    render(<TypeDistribution counts={{}} />);
    expect(screen.getByText("No records yet.")).toBeInTheDocument();
  });
});

describe("api client", () => {
  afterEach(() => vi.restoreAllMocks());

  it("builds query strings with repeated parameters", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ items: [], total: 0, limit: 10, offset: 0 }), { status: 200 }),
    );
    await api.entries({ project_id: "p1", type: ["issue", "note"], q: "", limit: 10 });
    expect(fetchMock.mock.calls[0][0]).toBe("/api/entries?project_id=p1&type=issue&type=note&limit=10");
  });

  it("turns error payloads into ApiError", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: { code: "conflict", message: "changed elsewhere", details: { current_revision: 3 } } }), {
        status: 409,
      }),
    );
    const err = await api.entry("x").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(409);
    expect(err.code).toBe("conflict");
    expect(err.details.current_revision).toBe(3);
  });

  it("reports network failures clearly", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const err = await api.meta().catch((e) => e);
    expect(err.code).toBe("network_error");
    expect(err.message).toContain("ohmypm web");
  });

  it("sends uploads as multipart form data", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("{}", { status: 201 }));
    await api.uploadAsset("p1", new File(["x"], "a.txt", { type: "text/plain" }), "e1");
    const init = fetchMock.mock.calls[0][1]!;
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get("project_id")).toBe("p1");
    expect((init.headers as Record<string, string>)["Content-Type"]).toBeUndefined();
  });
});
