import {
  codeBlockPlugin,
  codeMirrorPlugin,
  headingsPlugin,
  imagePlugin,
  linkPlugin,
  listsPlugin,
  MDXEditor,
  quotePlugin,
  tablePlugin,
  thematicBreakPlugin,
} from "@mdxeditor/editor";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { normalizeForComparison } from "@/components/editor/MarkdownEditor";
import { mathPlugin } from "@/components/editor/mathPlugin";

afterEach(cleanup);

/** Load Markdown into MDXEditor and return what it would write back unchanged. */
function roundTrip(markdown: string, withMath = true): Promise<{ output: string; error: string | null }> {
  return new Promise((resolve) => {
    let output = markdown;
    let error: string | null = null;
    render(
      <MDXEditor
        markdown={markdown}
        onChange={(md, initial) => {
          if (initial) output = md;
        }}
        onError={({ error: e }) => {
          error = e;
        }}
        suppressHtmlProcessing
        toMarkdownOptions={{ bullet: "-", emphasis: "_", strong: "*", rule: "-" }}
        plugins={[
          headingsPlugin(),
          listsPlugin(),
          quotePlugin(),
          thematicBreakPlugin(),
          linkPlugin(),
          tablePlugin(),
          imagePlugin(),
          codeBlockPlugin({ defaultCodeBlockLanguage: "" }),
          codeMirrorPlugin({ codeBlockLanguages: { "": "Text", cpp: "C++", mermaid: "Mermaid", bash: "Bash" } }),
          ...(withMath ? [mathPlugin()] : []),
        ]}
      />,
    );
    setTimeout(() => resolve({ output, error }), 250);
  });
}

const SUPPORTED: Record<string, string> = {
  heading: "## 完成内容\n\n相机节点通过 **V4L2** 采集，发布到 `/camera/image_raw`。",
  emphasis: "Some _italic_ and **bold** and ~~struck~~ text.",
  code: "```cpp\nint main() {\n  return 0;\n}\n```",
  table: "| 指标 | 目标 | 实测 |\n|---|---|---|\n| 帧率 | 30 fps | 29.8 fps |",
  mermaid: "```mermaid\nflowchart LR\n  cam --> node\n```",
  inlineMath: "曝光 $E_v = \\log_2 \\frac{N^2}{t}$ 很重要",
  blockMath: "$$\ne = \\frac{1}{n} \\sum_{i=1}^{n} \\lVert p_i - \\hat{p}_i \\rVert_2\n$$",
  tasks: "- [x] 驱动编译通过\n- [ ] 长时间稳定性测试",
  lists: "1. first\n2. second\n\n- a\n- b",
  image: "![camera](ohmypm-asset://9b1f7c1e-1111-4222-8333-444455556666)",
  link: "See [docs](https://example.com/docs).",
  quote: "> 下一步：接入相机标定。",
  rule: "above\n\n---\n\nbelow",
  comparison: "| 指标 | 目标 |\n|---|---|\n| 延迟 | < 50 ms |\n\nx <= 3",
};

describe("rich editor round trip", () => {
  for (const [name, markdown] of Object.entries(SUPPORTED)) {
    it(`keeps ${name} intact`, async () => {
      const { output, error } = await roundTrip(markdown);
      expect(error).toBeNull();
      expect(normalizeForComparison(output)).toBe(normalizeForComparison(markdown));
    });
  }

  it("does not escape TeX (the reason for the math plugin)", async () => {
    const tex = "Formula $a_1 * b_2$ and $x_{i}^{2}$ end";
    const withPlugin = await roundTrip(tex);
    expect(withPlugin.output).toBe(tex);
    cleanup();
    const without = await roundTrip(tex, false);
    expect(without.output).not.toBe(tex); // plain MDXEditor escapes `_` and `*`
  });

  it("detects inline $$...$$ being rewritten (same rendering, different syntax)", async () => {
    const tex = "Inline $$x_{i}$$ here";
    const { output } = await roundTrip(tex);
    expect(output).toBe("Inline $x_{i}$ here");
    expect(normalizeForComparison(output)).not.toBe(normalizeForComparison(tex)); // -> opens in Markdown mode
  });

  it("never silently drops unsupported syntax", async () => {
    const html = "Text\n\n<details><summary>More</summary>hidden</details>\n\nAfter";
    const { output, error } = await roundTrip(html);
    // Either the editor reports an error or the change is detected by the probe.
    const detected = error !== null || normalizeForComparison(output) !== normalizeForComparison(html);
    const preserved = output.includes("<details>") && output.includes("hidden");
    expect(detected || preserved).toBe(true);
  });
});

describe("normalizeForComparison", () => {
  it("ignores formatting-only differences", () => {
    expect(normalizeForComparison("* a\n+ b")).toBe(normalizeForComparison("- a\n- b"));
    expect(normalizeForComparison("| a | b |\n|---|:-:|")).toBe(normalizeForComparison("| a   | b |\n| -- | -- |"));
    expect(normalizeForComparison("__x__ *y*")).toBe(normalizeForComparison("**x** _y_"));
    expect(normalizeForComparison("a  \n\n\n\nb\n")).toBe(normalizeForComparison("a\n\nb"));
  });

  it("detects real changes", () => {
    expect(normalizeForComparison("$a_1$")).not.toBe(normalizeForComparison("$a\\_1$"));
    expect(normalizeForComparison("<b>x</b>")).not.toBe(normalizeForComparison("x"));
    expect(normalizeForComparison("\\<b>x")).not.toBe(normalizeForComparison("<b>x"));
    expect(normalizeForComparison("a \\< 5")).toBe(normalizeForComparison("a < 5"));
  });
});
