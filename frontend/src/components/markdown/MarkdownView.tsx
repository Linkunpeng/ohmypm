import type { Element, ElementContent } from "hast";
import { memo, useState, type ComponentProps } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { safeUrl } from "@/lib/format";
import { cn } from "@/lib/utils";

import { Mermaid } from "./Mermaid";

/**
 * Renders entry / summary Markdown. Raw HTML is never interpreted (no
 * rehype-raw); URLs pass through `safeUrl`, which maps `ohmypm-asset://` to the
 * local API and drops javascript: and other unsafe schemes.
 */

function textOf(node: ElementContent | Element): string {
  if (node.type === "text") return node.value;
  if ("children" in node) return node.children.map((c) => textOf(c as ElementContent)).join("");
  return "";
}

function ZoomableImage({ src, alt, title }: ComponentProps<"img">) {
  const [open, setOpen] = useState(false);
  if (!src || typeof src !== "string") return <span className="text-muted-foreground">[missing image: {alt}]</span>;
  return (
    <>
      <button
        type="button"
        className="inline-block cursor-zoom-in rounded align-top"
        onClick={() => setOpen(true)}
        aria-label={`Enlarge image ${alt ?? ""}`}
      >
        <img src={src} alt={alt ?? ""} title={title} loading="lazy" />
      </button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-h-[92vh] w-auto max-w-[94vw] sm:max-w-[94vw] p-3">
          <DialogTitle className="sr-only">{alt || "Image"}</DialogTitle>
          <img src={src} alt={alt ?? ""} className="max-h-[84vh] w-auto max-w-full object-contain" />
          {alt && <p className="text-center text-sm text-muted-foreground">{alt}</p>}
          <a href={`${src}?download=1`} className="text-center text-xs text-primary underline">
            Download original
          </a>
        </DialogContent>
      </Dialog>
    </>
  );
}

const components: Components = {
  pre({ node, children, ...props }) {
    const code = node?.children.find((c): c is Element => c.type === "element" && c.tagName === "code");
    const classes = (code?.properties?.className as string[] | undefined) ?? [];
    if (code && classes.includes("language-mermaid")) {
      return <Mermaid code={textOf(code).replace(/\n$/, "")} />;
    }
    return <pre {...props}>{children}</pre>;
  },
  img({ node: _node, ...props }) {
    return <ZoomableImage {...props} />;
  },
  a({ node: _node, href, children, ...props }) {
    const external = !!href && /^(https?:)?\/\//.test(href);
    const asset = !!href && href.startsWith("/api/assets/");
    return (
      <a href={href} {...props} {...(external || asset ? { target: "_blank", rel: "noopener noreferrer" } : {})}>
        {children}
      </a>
    );
  },
  input({ node: _node, ...props }) {
    // GFM task list checkboxes are display-only.
    return <input {...props} disabled />;
  },
};

const remarkPlugins = [remarkGfm, remarkMath];
const rehypePlugins = [
  [rehypeKatex, { throwOnError: false, strict: "ignore" }],
  [rehypeHighlight, { detect: false, plainText: ["mermaid", "text", "txt"] }],
] as ComponentProps<typeof ReactMarkdown>["rehypePlugins"];

export const MarkdownView = memo(function MarkdownView({
  markdown,
  className,
}: {
  markdown: string;
  className?: string;
}) {
  return (
    <div className={cn("md-prose", className)}>
      <ReactMarkdown
        remarkPlugins={remarkPlugins}
        rehypePlugins={rehypePlugins}
        components={components}
        urlTransform={safeUrl}
      >
        {markdown}
      </ReactMarkdown>
    </div>
  );
});
