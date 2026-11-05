import {
  BlockTypeSelect,
  BoldItalicUnderlineToggles,
  codeBlockPlugin,
  codeMirrorPlugin,
  CodeToggle,
  CreateLink,
  headingsPlugin,
  imagePlugin,
  InsertCodeBlock,
  InsertImage,
  InsertTable,
  InsertThematicBreak,
  linkDialogPlugin,
  linkPlugin,
  listsPlugin,
  ListsToggle,
  markdownShortcutPlugin,
  MDXEditor,
  type MDXEditorMethods,
  quotePlugin,
  Separator,
  StrikeThroughSupSubToggles,
  tablePlugin,
  thematicBreakPlugin,
  toolbarPlugin,
  UndoRedo,
} from "@mdxeditor/editor";
import "@mdxeditor/editor/style.css";
import { FileUp, Sigma } from "lucide-react";
import { useCallback, useMemo, useRef, useState, type DragEvent } from "react";
import { toast } from "sonner";

import { MarkdownView } from "@/components/markdown/MarkdownView";
import { ToggleGroup, ToggleGroupItem } from "@/components/ui/toggle-group";
import { api } from "@/lib/api";
import { assetUrl } from "@/lib/format";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

import { mathPlugin } from "./mathPlugin";

export type EditorMode = "rich" | "markdown";

const CODE_LANGUAGES: Record<string, string> = {
  "": "Plain text",
  bash: "Bash",
  sh: "Shell",
  c: "C",
  cpp: "C++",
  cmake: "CMake",
  python: "Python",
  javascript: "JavaScript",
  typescript: "TypeScript",
  tsx: "TSX",
  json: "JSON",
  yaml: "YAML",
  toml: "TOML",
  rust: "Rust",
  go: "Go",
  java: "Java",
  sql: "SQL",
  diff: "Diff",
  xml: "XML",
  html: "HTML",
  css: "CSS",
  markdown: "Markdown",
  mermaid: "Mermaid",
  text: "Text",
};

/**
 * Formatting differences MDXEditor introduces that do not change meaning.
 * Anything else means rich-text editing would rewrite the author's Markdown.
 */
export function normalizeForComparison(markdown: string): string {
  return markdown
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((line) =>
      line
        .replace(/\s+$/, "")
        // "\<" before a space, digit or "=" renders exactly like "<" (e.g. "< 50 ms").
        .replace(/\\<\\=/g, "<=")
        .replace(/\\<(?=[\s\d=])/g, "<")
        .replace(/^(\s*)[*+](\s+)/, "$1-$2")
        .replace(/^(\s*)(\d+)[.)](\s+)/, "$1$2.$3")
        .replace(/^(\s*)-\s+\[([ xX])\]/, (_m, s, c) => `${s}- [${c.toLowerCase()}]`)
        .replace(/^(\s*)(?:\*{3,}|-{3,}|_{3,})$/, "$1---")
        .replace(/__(.+?)__/g, "**$1**")
        .replace(/(^|[^*])\*([^*\s][^*]*?)\*(?!\*)/g, "$1_$2_")
        .replace(/^\s*\|?(\s*:?-+:?\s*\|)*\s*:?-+:?\s*\|?\s*$/, (row) => (row.includes("|") ? "|---|" : row))
        .replace(/\s*\|\s*/g, "|"),
    )
    .join("\n")
    .replace(/\n{2,}/g, "\n\n")
    .trim();
}

interface Props {
  value: string;
  onChange: (value: string) => void;
  projectId: string;
  entryId?: string;
  mode: EditorMode;
  onModeChange: (mode: EditorMode) => void;
  placeholder?: string;
  minHeight?: number;
  /** Called once with an explanation when rich mode would alter the document. */
  onLossyRichText?: (reason: string) => void;
}

export function MarkdownEditor({
  value,
  onChange,
  projectId,
  entryId,
  mode,
  onModeChange,
  placeholder,
  minHeight = 360,
  onLossyRichText,
}: Props) {
  const { resolved } = useTheme();
  const editorRef = useRef<MDXEditorMethods>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [richKey, setRichKey] = useState(0);
  const [dragging, setDragging] = useState(false);
  // The Markdown the rich editor was (re)loaded with; the probe compares against it.
  const [loadedValue, setLoadedValue] = useState(value);
  const fileInput = useRef<HTMLInputElement>(null);

  const upload = useCallback(
    async (file: File) => {
      const asset = await api.uploadAsset(projectId, file, entryId);
      return asset;
    },
    [projectId, entryId],
  );

  const switchMode = (next: EditorMode) => {
    if (next === mode) return;
    if (next === "rich") {
      setLoadedValue(value);
      setRichKey((k) => k + 1);
    }
    onModeChange(next);
  };

  const insertAtCursor = useCallback(
    (snippet: string) => {
      if (mode === "rich" && editorRef.current) {
        editorRef.current.insertMarkdown(snippet);
        return;
      }
      const el = textareaRef.current;
      const start = el?.selectionStart ?? value.length;
      const end = el?.selectionEnd ?? value.length;
      const before = value.slice(0, start);
      // Attachments go into their own paragraph.
      const needsBreak = !before || before.endsWith("\n\n") ? "" : before.endsWith("\n") ? "\n" : "\n\n";
      const next = `${before}${needsBreak}${snippet}\n${value.slice(end)}`;
      onChange(next);
      requestAnimationFrame(() => {
        if (!el) return;
        const pos = before.length + needsBreak.length + snippet.length + 1;
        el.focus();
        el.setSelectionRange(pos, pos);
      });
    },
    [mode, onChange, value],
  );

  const uploadFiles = useCallback(
    async (files: FileList | File[]) => {
      for (const file of Array.from(files)) {
        try {
          const asset = await upload(file);
          insertAtCursor(asset.markdown);
          toast.success(`Attached ${asset.filename}`);
        } catch (err) {
          toast.error(err instanceof Error ? err.message : "Upload failed");
        }
      }
    },
    [insertAtCursor, upload],
  );

  const plugins = useMemo(
    () => [
      headingsPlugin(),
      listsPlugin(),
      quotePlugin(),
      thematicBreakPlugin(),
      linkPlugin(),
      linkDialogPlugin(),
      tablePlugin(),
      imagePlugin({
        imageUploadHandler: async (file: File) => {
          const asset = await upload(file);
          return asset.uri;
        },
        imagePreviewHandler: async (src: string) => assetUrl(src),
        disableImageResize: true,
      }),
      codeBlockPlugin({ defaultCodeBlockLanguage: "" }),
      codeMirrorPlugin({ codeBlockLanguages: CODE_LANGUAGES }),
      mathPlugin(),
      markdownShortcutPlugin(),
      toolbarPlugin({
        toolbarContents: () => (
          <>
            <UndoRedo />
            <Separator />
            <BlockTypeSelect />
            <BoldItalicUnderlineToggles options={["Bold", "Italic"]} />
            <StrikeThroughSupSubToggles options={["Strikethrough"]} />
            <CodeToggle />
            <Separator />
            <ListsToggle />
            <CreateLink />
            <InsertImage />
            <InsertTable />
            <InsertCodeBlock />
            <InsertThematicBreak />
            <button
              type="button"
              className="ml-1 inline-flex items-center gap-1 rounded px-1.5 py-1 text-sm hover:bg-accent"
              title="Insert formula"
              onClick={() => editorRef.current?.insertMarkdown("$$\nE = mc^2\n$$")}
            >
              <Sigma className="size-4" aria-hidden /> Formula
            </button>
          </>
        ),
      }),
    ],
    [upload],
  );

  const onDrop = (event: DragEvent) => {
    setDragging(false);
    if (mode !== "markdown" || !event.dataTransfer.files.length) return;
    event.preventDefault();
    void uploadFiles(event.dataTransfer.files);
  };

  return (
    <div className="rounded-md border border-border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-2 py-1.5">
        <ToggleGroup
          type="single"
          size="sm"
          value={mode}
          onValueChange={(v) => v && switchMode(v as EditorMode)}
          aria-label="Editor mode"
        >
          <ToggleGroupItem value="rich" className="px-3">
            Rich text
          </ToggleGroupItem>
          <ToggleGroupItem value="markdown" className="px-3">
            Markdown
          </ToggleGroupItem>
        </ToggleGroup>
        <button
          type="button"
          onClick={() => fileInput.current?.click()}
          className="inline-flex items-center gap-1.5 rounded px-2 py-1 text-sm text-muted-foreground hover:bg-accent hover:text-foreground"
        >
          <FileUp className="size-4" aria-hidden /> Attach image or file
        </button>
        <input
          ref={fileInput}
          type="file"
          multiple
          hidden
          accept="image/png,image/jpeg,image/webp,image/gif,image/svg+xml,text/*,.md,.log,.json,.yaml,.yml,.toml,.csv,.diff,.patch"
          onChange={(e) => {
            if (e.target.files) void uploadFiles(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {mode === "rich" ? (
        <MDXEditor
          key={richKey}
          ref={editorRef}
          markdown={loadedValue}
          onChange={(markdown, initialNormalize) => {
            if (initialNormalize) {
              if (normalizeForComparison(markdown) !== normalizeForComparison(loadedValue)) {
                if (localStorage.getItem("ohmypm-debug")) {
                  console.debug("ohmypm: rich text would change", { before: loadedValue, after: markdown });
                }
                onLossyRichText?.(
                  "The rich text editor would rewrite parts of this Markdown, so it opened in Markdown mode to keep it exact.",
                );
              }
              return;
            }
            onChange(markdown);
          }}
          onError={({ error }) =>
            onLossyRichText?.(`The rich text editor cannot represent this document (${error}). Use Markdown mode.`)
          }
          plugins={plugins}
          placeholder={placeholder}
          className={cn("ohmypm-editor", resolved === "dark" && "dark-theme")}
          contentEditableClassName="md-prose ohmypm-editor-content"
          suppressHtmlProcessing
          toMarkdownOptions={{ bullet: "-", emphasis: "_", strong: "*", rule: "-" }}
        />
      ) : (
        <div
          className={cn("grid gap-0 lg:grid-cols-2", dragging && "ring-2 ring-primary ring-inset")}
          onDragOver={(e) => {
            if (e.dataTransfer.types.includes("Files")) {
              e.preventDefault();
              setDragging(true);
            }
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <textarea
            ref={textareaRef}
            aria-label="Markdown source"
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onPaste={(e) => {
              if (e.clipboardData.files.length) {
                e.preventDefault();
                void uploadFiles(e.clipboardData.files);
              }
            }}
            placeholder={placeholder}
            spellCheck={false}
            style={{ minHeight }}
            className="w-full resize-y border-0 bg-transparent p-4 font-mono text-sm leading-relaxed outline-none focus-visible:outline-none lg:border-r lg:border-border"
          />
          <div className="hidden overflow-auto p-4 lg:block" style={{ maxHeight: Math.max(minHeight, 640) }}>
            {value.trim() ? (
              <MarkdownView markdown={value} />
            ) : (
              <p className="text-sm text-muted-foreground">The preview appears here.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
