import { useEffect, useId, useState } from "react";

import { useTheme } from "@/lib/theme";

type MermaidModule = typeof import("mermaid");
let loader: Promise<MermaidModule> | null = null;

/** Mermaid is large; load it only when a diagram is actually rendered. */
function loadMermaid(): Promise<MermaidModule> {
  loader ??= import("mermaid");
  return loader;
}

let renderQueue: Promise<unknown> = Promise.resolve();

export function Mermaid({ code }: { code: string }) {
  const { resolved } = useTheme();
  const reactId = useId();
  const [svg, setSvg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showSource, setShowSource] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const id = `mermaid-${reactId.replace(/[^a-zA-Z0-9]/g, "")}-${resolved}`;
    // mermaid.render is not re-entrant; serialise renders across diagrams.
    renderQueue = renderQueue.then(async () => {
      try {
        const { default: mermaid } = await loadMermaid();
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: resolved === "dark" ? "dark" : "neutral",
          fontFamily: "IBM Plex Sans, sans-serif",
        });
        const result = await mermaid.render(id, code);
        if (!cancelled) {
          setSvg(result.svg);
          setError(null);
        }
      } catch (err) {
        document.getElementById(`d${id}`)?.remove();
        if (!cancelled) {
          setSvg(null);
          setError(err instanceof Error ? err.message : String(err));
        }
      }
    });
    return () => {
      cancelled = true;
    };
  }, [code, resolved, reactId]);

  if (error) {
    return (
      <figure className="not-prose rounded-md border border-destructive/40 p-3 font-sans text-sm">
        <figcaption className="mb-2 text-destructive">Mermaid diagram could not be rendered: {error}</figcaption>
        <pre className="overflow-x-auto font-mono text-xs">{code}</pre>
      </figure>
    );
  }

  return (
    <figure className="group relative my-4 rounded-md border border-rule bg-card p-4" data-testid="mermaid">
      {svg ? (
        // Output of mermaid.render with securityLevel "strict" (sanitised by DOMPurify).
        <div className="flex justify-center overflow-x-auto [&_svg]:max-w-full" dangerouslySetInnerHTML={{ __html: svg }} />
      ) : (
        <div className="h-24 animate-pulse rounded bg-muted" aria-label="Rendering diagram" />
      )}
      <button
        type="button"
        onClick={() => setShowSource((v) => !v)}
        className="absolute right-2 top-2 rounded px-2 py-0.5 font-sans text-xs text-muted-foreground opacity-0 transition-opacity hover:bg-muted group-hover:opacity-100 focus-visible:opacity-100"
      >
        {showSource ? "Hide source" : "Source"}
      </button>
      {showSource && <pre className="mt-3 overflow-x-auto font-mono text-xs">{code}</pre>}
    </figure>
  );
}
