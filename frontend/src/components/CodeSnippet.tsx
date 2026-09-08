import { highlight, type LanguageName } from "sugar-high";
import { CopyButton } from "@/components/CopyButton";

/**
 * A code block with its own copy button; `label` names it for assistive tech.
 *
 * `lang` turns highlighting on. It is not optional once you want it:
 * sugar-high defaults to JavaScript, whose comment rule reads the `//` in
 * an `https://` URL as the start of a line comment and greys out the rest
 * of a curl command. Every caller states its language.
 *
 * `wrap` is for long lines that must stay readable -- a curl command's
 * model and placeholder live at the end, which a horizontal scrollbar
 * hides. It also bounds the height, so a wrapped block scrolls vertically
 * inside itself instead of growing its container. Off by default, so a
 * short snippet keeps the plain one-line-per-line shape.
 *
 * Highlighted markup is inserted as HTML, which is safe because the
 * highlighter escapes `<`, `>` and `&` before wrapping tokens -- checked
 * against a span-breakout payload, not assumed. The values interpolated
 * into these snippets (endpoint, Service address, model reference) are
 * platform-generated or admin-set, and none of them survives as markup.
 */
export function CodeSnippet({
  label,
  code,
  lang,
  wrap = false,
}: {
  label: string;
  code: string;
  lang?: LanguageName;
  wrap?: boolean;
}) {
  return (
    <div className={wrap ? "relative w-full min-w-0" : "relative"}>
      <pre
        role="group"
        aria-label={label}
        className={
          wrap
            ? "max-h-[50vh] w-full min-w-0 overflow-y-auto rounded-md bg-muted p-3 pr-12 text-xs break-words whitespace-pre-wrap"
            : "overflow-x-auto rounded-md bg-muted p-3 pr-12 text-xs"
        }
      >
        {lang ? (
          <code
            className="sh__code"
            dangerouslySetInnerHTML={{ __html: highlight(code, { lang }) }}
          />
        ) : (
          code
        )}
      </pre>
      <div className="absolute top-2 right-2">
        <CopyButton label={label} text={code} />
      </div>
    </div>
  );
}
