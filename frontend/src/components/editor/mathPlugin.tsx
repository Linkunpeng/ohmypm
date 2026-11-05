/**
 * MDXEditor plugin for `$inline$` and `$$block$$` math.
 *
 * Without it, MDXEditor treats `$a_1$` as plain text and escapes it on export
 * (`$a\_1$`), silently corrupting formulas. The plugin parses math with the same
 * micromark/mdast extensions remark-math uses for rendering, keeps the TeX source
 * in a Lexical decorator node (rendered with KaTeX) and writes it back verbatim.
 */
import {
  addExportVisitor$,
  addImportVisitor$,
  addLexicalNode$,
  addMdastExtension$,
  addSyntaxExtension$,
  addToMarkdownExtension$,
  realmPlugin,
  type LexicalExportVisitor,
  type MdastImportVisitor,
} from "@mdxeditor/editor";
import katex from "katex";
import {
  $applyNodeReplacement,
  DecoratorNode,
  type EditorConfig,
  type LexicalEditor,
  type LexicalNode,
  type NodeKey,
  type SerializedLexicalNode,
  type Spread,
} from "lexical";
import { mathFromMarkdown, mathToMarkdown } from "mdast-util-math";
import { math } from "micromark-extension-math";
import { useEffect, useRef, useState, type JSX } from "react";

type SerializedMathNode = Spread<{ value: string; inline: boolean }, SerializedLexicalNode>;

export class MathNode extends DecoratorNode<JSX.Element> {
  __value: string;
  __inline: boolean;

  static getType(): string {
    return "ohmypm-math";
  }

  static clone(node: MathNode): MathNode {
    return new MathNode(node.__value, node.__inline, node.__key);
  }

  constructor(value: string, inline: boolean, key?: NodeKey) {
    super(key);
    this.__value = value;
    this.__inline = inline;
  }

  static importJSON(json: SerializedMathNode): MathNode {
    return $createMathNode(json.value, json.inline);
  }

  exportJSON(): SerializedMathNode {
    return { type: "ohmypm-math", version: 1, value: this.__value, inline: this.__inline };
  }

  createDOM(_config: EditorConfig): HTMLElement {
    const el = document.createElement(this.__inline ? "span" : "div");
    el.contentEditable = "false";
    el.className = this.__inline ? "ohmypm-math-inline" : "ohmypm-math-block";
    return el;
  }

  updateDOM(): false {
    return false;
  }

  isInline(): boolean {
    return this.__inline;
  }

  getValue(): string {
    return this.getLatest().__value;
  }

  setValue(value: string): void {
    if (value !== this.getLatest().__value) this.getWritable().__value = value;
  }

  decorate(editor: LexicalEditor): JSX.Element {
    return (
      <MathEditor
        value={this.getValue()}
        inline={this.__inline}
        onChange={(value) =>
          editor.update(() => {
            if (this.isAttached()) this.setValue(value);
          })
        }
      />
    );
  }
}

export function $createMathNode(value: string, inline: boolean): MathNode {
  return $applyNodeReplacement(new MathNode(value, inline));
}

export function $isMathNode(node: LexicalNode | null | undefined): node is MathNode {
  return node instanceof MathNode;
}

function renderTex(value: string, inline: boolean): string {
  return katex.renderToString(value || "\\square", { displayMode: !inline, throwOnError: false, strict: "ignore" });
}

function MathEditor({ value, inline, onChange }: { value: string; inline: boolean; onChange: (v: string) => void }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => setDraft(value), [value]);
  useEffect(() => {
    if (editing) inputRef.current?.focus();
  }, [editing]);

  const commit = () => {
    setEditing(false);
    if (draft !== value) onChange(draft);
  };

  if (editing) {
    return (
      <span className={inline ? "inline-flex align-middle" : "my-2 block"}>
        <textarea
          ref={inputRef}
          aria-label="TeX source"
          value={draft}
          rows={inline ? 1 : Math.max(2, draft.split("\n").length)}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              setDraft(value);
              setEditing(false);
            }
            if (e.key === "Enter" && (inline || e.ctrlKey || e.metaKey)) {
              e.preventDefault();
              commit();
            }
          }}
          className="w-full min-w-48 rounded border border-primary bg-card px-2 py-1 font-mono text-sm"
        />
      </span>
    );
  }
  return (
    <span
      role="button"
      tabIndex={0}
      title="Click to edit formula"
      onClick={() => setEditing(true)}
      onKeyDown={(e) => e.key === "Enter" && setEditing(true)}
      className={
        inline
          ? "cursor-pointer rounded px-0.5 hover:bg-accent"
          : "block cursor-pointer overflow-x-auto rounded py-2 hover:bg-accent"
      }
      dangerouslySetInnerHTML={{ __html: renderTex(value, inline) }}
    />
  );
}

interface MathMdast {
  type: "math" | "inlineMath";
  value: string;
}

const MdastMathVisitor: MdastImportVisitor<never> = {
  testNode: (node) => node.type === "math" || node.type === "inlineMath",
  visitNode({ mdastNode, actions }) {
    const node = mdastNode as unknown as MathMdast;
    actions.addAndStepInto($createMathNode(node.value, node.type === "inlineMath"));
  },
};

const LexicalMathVisitor: LexicalExportVisitor<MathNode, never> = {
  testLexicalNode: $isMathNode,
  visitLexicalNode({ lexicalNode, actions }) {
    actions.addAndStepInto(lexicalNode.__inline ? "inlineMath" : "math", { value: lexicalNode.getValue() }, false);
  },
};

export const mathPlugin = realmPlugin({
  init(realm) {
    realm.pubIn({
      [addSyntaxExtension$]: math(),
      [addMdastExtension$]: mathFromMarkdown(),
      [addToMarkdownExtension$]: mathToMarkdown(),
      [addImportVisitor$]: MdastMathVisitor,
      [addLexicalNode$]: MathNode,
      [addExportVisitor$]: LexicalMathVisitor,
    });
  },
});
