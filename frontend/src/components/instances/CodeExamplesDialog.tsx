"use client";

import { useState } from "react";
import { type LanguageName } from "sugar-high";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { CodeSnippet } from "@/components/CodeSnippet";

export type CodeExample = {
  id: string;
  label: string;
  /** Passed to the highlighter: without it every snippet parses as
      JavaScript, and `//` in `https://` turns the rest of a curl line
      into a comment -- greying out the very URL the reader came for. */
  lang: LanguageName;
  code: string;
};

/**
 * The worked examples, behind a button rather than on the page.
 *
 * The values above are the lookup people come back for; the code is read
 * once, when wiring a client up. Keeping three snippets inline pushed the
 * fields off the top of the section for everyone, to serve the rarer
 * need. It opens on demand instead, one language at a time.
 *
 * Highlighting earns its place here: it separates the placeholders that
 * must be replaced from the values that are already correct, which is the
 * one mistake this dialog exists to prevent.
 */
export function CodeExamplesDialog({
  examples,
  title,
  description,
  triggerLabel = "Code examples",
  trigger,
}: {
  examples: CodeExample[];
  title: string;
  description: string;
  triggerLabel?: string;
  /** A trigger of the caller's own (an icon button in a tight row);
      it must carry its accessible name itself. */
  trigger?: React.ReactNode;
}) {
  const [open, setOpen] = useState(false);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger ?? (
          <Button variant="outline" size="sm">
            {triggerLabel}
          </Button>
        )}
      </DialogTrigger>
      {/* sm:max-w-3xl, not max-w-3xl: DialogContent ships sm:max-w-lg, which
          wins at that breakpoint. And min-w-0 all the way down to the pre,
          because DialogContent is a grid and a grid item's default min-width
          is its content, so one long curl line widens the dialog rather than
          wrapping inside it. */}
      <DialogContent className="sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <Tabs defaultValue={examples[0]?.id} className="w-full min-w-0">
          <TabsList>
            {examples.map((example) => (
              <TabsTrigger key={example.id} value={example.id}>
                {example.label}
              </TabsTrigger>
            ))}
          </TabsList>
          {examples.map((example) => (
            <TabsContent
              key={example.id}
              value={example.id}
              className="w-full min-w-0"
            >
              <CodeSnippet
                label={`${example.label} example`}
                code={example.code}
                lang={example.lang}
                wrap
              />
            </TabsContent>
          ))}
        </Tabs>
      </DialogContent>
    </Dialog>
  );
}
