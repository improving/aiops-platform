import { isValidElement, memo, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { LanguageName } from "sugar-high";
import { CodeSnippet } from "@/components/CodeSnippet";

const LANGUAGES: Record<string, LanguageName> = {
  javascript: "javascript",
  js: "javascript",
  jsx: "javascript",
  typescript: "typescript",
  ts: "typescript",
  tsx: "typescript",
  python: "python",
  py: "python",
  shell: "shell",
  sh: "shell",
  bash: "shell",
  zsh: "shell",
  console: "shell",
  json: "json",
  yaml: "yaml",
  yml: "yaml",
  go: "go",
  rust: "rust",
  rs: "rust",
  java: "java",
  kotlin: "kotlin",
  c: "c",
  cpp: "cpp",
  "c++": "cpp",
  csharp: "csharp",
  cs: "csharp",
  sql: "sql",
  html: "html",
  css: "css",
  diff: "diff",
  ruby: "ruby",
  rb: "ruby",
  markdown: "markdown",
  md: "markdown",
};

/** A fenced block: the one code-block component, with its copy button.
    An unknown language is shown without highlighting rather than parsed
    as JavaScript. */
function Pre({ children }: { children?: ReactNode }) {
  const code = isValidElement<{ className?: string; children?: ReactNode }>(
    children
  )
    ? children
    : null;
  const name = /language-([\w+#-]+)/.exec(code?.props.className ?? "")?.[1];
  const text = String(code?.props.children ?? "").replace(/\n$/, "");
  return (
    <div className="my-2">
      <CodeSnippet
        label={name ? `${name} code` : "code"}
        code={text}
        lang={name ? LANGUAGES[name.toLowerCase()] : undefined}
      />
    </div>
  );
}

/**
 * An answer as Markdown (GFM: tables, task lists, strikethrough). Raw
 * HTML in the text stays text: there is no `rehype-raw` here, so a model
 * cannot put markup into the page.
 */
export const Markdown = memo(function Markdown({ text }: { text: string }) {
  return (
    <div className="space-y-2 break-words [&_:not(pre)>code]:rounded [&_:not(pre)>code]:bg-muted [&_:not(pre)>code]:px-1 [&_:not(pre)>code]:py-0.5 [&_:not(pre)>code]:text-[0.85em] [&_a]:underline [&_blockquote]:border-l-2 [&_blockquote]:pl-3 [&_blockquote]:text-muted-foreground [&_h1]:text-lg [&_h1]:font-semibold [&_h2]:text-base [&_h2]:font-semibold [&_h3]:font-semibold [&_hr]:my-3 [&_li]:my-0.5 [&_ol]:list-decimal [&_ol]:pl-5 [&_table]:block [&_table]:overflow-x-auto [&_table]:text-sm [&_td]:border [&_td]:px-2 [&_td]:py-1 [&_th]:border [&_th]:px-2 [&_th]:py-1 [&_th]:text-left [&_ul]:list-disc [&_ul]:pl-5">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          pre: Pre,
          a: ({ href, children }) => (
            <a href={href} target="_blank" rel="noreferrer">
              {children}
            </a>
          ),
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
});
