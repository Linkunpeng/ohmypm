import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MarkdownView } from "@/components/markdown/MarkdownView";
import { ThemeProvider } from "@/lib/theme";

vi.mock("mermaid", () => ({
  default: {
    initialize: vi.fn(),
    render: vi.fn(async (_id: string, code: string) => {
      if (code.includes("broken")) throw new Error("Parse error on line 1");
      return { svg: `<svg data-diagram="ok"><text>${code.length}</text></svg>` };
    }),
  },
}));

function view(markdown: string) {
  return render(
    <ThemeProvider>
      <MarkdownView markdown={markdown} />
    </ThemeProvider>,
  );
}

describe("MarkdownView", () => {
  it("renders GFM: headings, tables, task lists, strikethrough", () => {
    const { container } = view("## 标题\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n- [x] done\n- [ ] todo\n\n~~old~~");
    expect(screen.getByRole("heading", { level: 2, name: "标题" })).toBeInTheDocument();
    expect(container.querySelector("table td")?.textContent).toBe("1");
    const boxes = container.querySelectorAll("input[type=checkbox]");
    expect(boxes).toHaveLength(2);
    expect((boxes[0] as HTMLInputElement).checked).toBe(true);
    expect((boxes[0] as HTMLInputElement).disabled).toBe(true);
    expect(container.querySelector("del")?.textContent).toBe("old");
  });

  it("highlights code blocks", () => {
    const { container } = view("```python\ndef f():\n    return 1\n```");
    expect(container.querySelector("code.hljs.language-python .hljs-keyword")).not.toBeNull();
  });

  it("renders KaTeX for inline and display math", () => {
    const { container } = view("Inline $E=mc^2$ and\n\n$$\n\\sum_{i=1}^n i\n$$");
    expect(container.querySelectorAll(".katex").length).toBeGreaterThanOrEqual(2);
    expect(container.querySelector(".katex-display")).not.toBeNull();
  });

  it("maps ohmypm-asset:// images to the local API", () => {
    view("![截图](ohmypm-asset://9B1F7C1E-1111-4222-8333-444455556666)");
    const img = screen.getByAltText("截图") as HTMLImageElement;
    expect(img.getAttribute("src")).toBe("/api/assets/9b1f7c1e-1111-4222-8333-444455556666");
  });

  it("drops dangerous URLs and does not render raw HTML", () => {
    const { container } = view(
      "[click](javascript:alert(1)) <script>alert(1)</script> <img src=x onerror=alert(1)>\n\n![x](ohmypm-asset://../../etc/passwd)",
    );
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("img[onerror]")).toBeNull();
    const link = screen.getByText("click").closest("a")!;
    expect(link.getAttribute("href") ?? "").not.toContain("javascript");
    const images = Array.from(container.querySelectorAll("img"));
    expect(images.every((i) => !i.getAttribute("src")?.includes("passwd"))).toBe(true);
    expect(container.textContent).toContain("<script>");
  });

  it("opens external links in a new tab without referrer", () => {
    view("[site](https://example.com)");
    const a = screen.getByText("site").closest("a")!;
    expect(a.getAttribute("target")).toBe("_blank");
    expect(a.getAttribute("rel")).toContain("noopener");
  });

  it("renders mermaid diagrams and reports errors", async () => {
    const { container } = view("```mermaid\nflowchart LR\n  a --> b\n```\n\n```mermaid\nbroken\n```");
    await waitFor(() => expect(container.querySelector("svg[data-diagram=ok]")).not.toBeNull());
    await waitFor(() => expect(screen.getByText(/could not be rendered/)).toBeInTheDocument());
  });
});
