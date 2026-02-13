"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

const REMARK_PLUGINS = [remarkGfm];

/** Shared prose classes for consistent markdown styling across the app. */
const PROSE_CLASSES = [
  "prose prose-sm prose-invert max-w-none",
  "text-sm leading-relaxed",
  // Headings
  "[&_h1]:text-base [&_h2]:text-sm [&_h3]:text-sm [&_h1]:font-semibold [&_h2]:font-semibold [&_h3]:font-semibold",
  // Paragraphs & lists
  "[&_p]:text-sm [&_li]:text-sm [&_ul]:my-1 [&_ol]:my-1 [&_p]:my-1",
  // Tables — the core fix for GFM table rendering
  "[&_table]:w-full [&_table]:text-xs [&_table]:border-collapse [&_table]:my-2",
  "[&_th]:text-left [&_th]:px-3 [&_th]:py-1.5 [&_th]:border [&_th]:border-card-border [&_th]:bg-card-hover [&_th]:font-semibold [&_th]:text-foreground",
  "[&_td]:px-3 [&_td]:py-1.5 [&_td]:border [&_td]:border-card-border [&_td]:text-muted-foreground",
  // Code
  "[&_code]:text-xs [&_code]:bg-card-hover [&_code]:px-1 [&_code]:py-0.5 [&_code]:rounded",
  // Links
  "[&_a]:text-accent [&_a]:no-underline [&_a:hover]:underline",
].join(" ");

/**
 * Universal markdown renderer with GFM support (tables, strikethrough, etc.).
 * Use this everywhere markdown content is displayed for consistent styling.
 */
export function Markdown({ children, className }: { children: string; className?: string }) {
  return (
    <div className={`${PROSE_CLASSES} ${className ?? ""}`}>
      <ReactMarkdown remarkPlugins={REMARK_PLUGINS}>{children}</ReactMarkdown>
    </div>
  );
}
