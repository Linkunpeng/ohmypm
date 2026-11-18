import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Relations, SimilarRecords } from "@/components/Relations";
import { linkTarget } from "@/lib/entryTypes";
import type { Entry, SimilarEntry } from "@/lib/types";

const link = (sequence: number, kind: "relates" | "fixes" | "supersedes" | "mentions") => ({
  kind,
  entry_id: `e${sequence}`,
  sequence,
  type: "issue",
  title: `Record ${sequence}`,
  status: null,
});

const entry: Entry = {
  id: "e1",
  project_id: "p1",
  sequence: 1,
  type: "milestone",
  title: "Done",
  content: "",
  excerpt: "",
  status: null,
  author: null,
  source: "cli",
  revision: 1,
  created_at: "2026-11-18T00:00:00Z",
  updated_at: "2026-11-18T00:00:00Z",
  metadata: {},
  asset_ids: [],
  tags: [],
  links: [link(3, "fixes"), link(4, "mentions")],
  backlinks: [link(5, "relates")],
};

const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });

/** Mocks fetch: /api/meta, /similar and PATCH; returns the PATCH bodies. */
function mockApi(similar: SimilarEntry[] = []) {
  const patches: unknown[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const url = String(input);
    if (init?.method === "PATCH") {
      patches.push(JSON.parse(String(init.body)));
      return json({ changed: true, entry });
    }
    if (url.includes("/similar")) return json(similar);
    return json({ version: "0.1.0", default_author: null, entry_types: {}, statuses: [] });
  });
  return patches;
}

function renderWithClient(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("linkTarget", () => {
  it("normalises record numbers and keeps ids", () => {
    expect(linkTarget(" 12 ")).toBe("#12");
    expect(linkTarget("#7")).toBe("#7");
    expect(linkTarget("8f2c1a")).toBe("8f2c1a");
  });
});

describe("Relations", () => {
  it("only offers removal for explicit outgoing links", async () => {
    const patches = mockApi();
    renderWithClient(<Relations entry={entry} projectId="p1" />);
    expect(screen.getByText("Fixes")).toBeInTheDocument();
    expect(screen.getByText("Mentions")).toBeInTheDocument();
    expect(screen.getByText("Related to")).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Remove link/ })).toHaveLength(1);

    await userEvent.click(screen.getByRole("button", { name: "Remove link to #3" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({ remove_links: ["#3"] });
  });

  it("adds a link of the chosen kind", async () => {
    const patches = mockApi();
    renderWithClient(<Relations entry={{ ...entry, links: [], backlinks: [] }} projectId="p1" />);
    expect(screen.getByText(/No links yet/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add a link" }));
    await userEvent.selectOptions(screen.getByRole("combobox", { name: "Link kind" }), "supersedes");
    await userEvent.type(screen.getByRole("textbox", { name: "Target record" }), "12");
    await userEvent.click(screen.getByRole("button", { name: "Link" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({ add_links: [{ target: "#12", kind: "supersedes" }] });
  });
});

describe("SimilarRecords", () => {
  const hit = (sequence: number, linked: boolean): SimilarEntry => ({
    entry_id: `e${sequence}`,
    sequence,
    type: "issue",
    title: `Similar ${sequence}`,
    status: "open",
    created_at: "2026-11-18T00:00:00Z",
    updated_at: "2026-11-18T00:00:00Z",
    tags: [],
    score: 0.42,
    title_score: 0.5,
    body_score: null,
    shared_tags: [],
    linked,
  });

  it("lists similar records and links one as related", async () => {
    const patches = mockApi([hit(7, false), hit(8, true)]);
    renderWithClient(<SimilarRecords entry={entry} projectId="p1" />);
    expect(await screen.findByText("Similar 7")).toBeInTheDocument();
    expect(screen.getAllByText("42%")).toHaveLength(2);
    expect(screen.getByText("linked")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Link #7 as related" }));
    await waitFor(() => expect(patches).toHaveLength(1));
    expect(patches[0]).toMatchObject({ add_links: [{ target: "#7", kind: "relates" }] });
  });

  it("renders nothing without matches", async () => {
    mockApi([]);
    const { container } = renderWithClient(<SimilarRecords entry={entry} projectId="p1" />);
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });
});
