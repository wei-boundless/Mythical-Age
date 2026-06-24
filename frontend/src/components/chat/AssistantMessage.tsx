"use client";

import { Check, Copy, FileText } from "lucide-react";
import React from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import remarkGfm from "remark-gfm";

type AssistantMessageImage = {
  alt?: string;
  caption?: string;
  src: string;
};

type AssistantMessageProps = {
  copiedReply: boolean;
  copyableReplyText: string;
  displayText: string;
  explicitBodyText: boolean;
  fileNameIndex?: Map<string, string>;
  image?: AssistantMessageImage | null;
  imageUnavailable: boolean;
  onCopyReply: () => void;
  onOpenWorkspaceFile?: (path: string, options?: { lineNumber?: number }) => void;
  onImageError: (src: string) => void;
  showCopy: boolean;
  streamingContent: boolean;
  workspaceRoot?: string;
};

const STRUCTURE_LINE_RE = /(?:[┌┬┐├┼┤└┴┘─│━┃╭╮╰╯]|(?:^|\s)(?:backend|frontend|api|task_system|harness|registry|canvas|editor|instance|workbench|templates)[\w/.-]*\/.*(?:->|→|──))/i;
const FENCE_RE = /^\s*(```|~~~)/;
const FENCE_OPEN_RE = /^\s*(```|~~~)\s*([A-Za-z0-9_-]*)?.*$/;
const REPORT_HEADING_RE = /^(?:#{2,6}\s+\S|[一二三四五六七八九十]+[、.．]\s*\S|\d+(?:\.\d+)+\s+\S)/;
const REPORT_PROSE_RE = /[\u4e00-\u9fff].*[。；：，]/;
const REPORT_LIKE_FENCE_LANGS = new Set(["", "text", "txt", "markdown", "md", "plain"]);
const CODE_LIKE_FENCE_LANGS = new Set([
  "bash",
  "bat",
  "c",
  "cmd",
  "cpp",
  "css",
  "diff",
  "go",
  "html",
  "java",
  "javascript",
  "js",
  "json",
  "jsx",
  "powershell",
  "ps1",
  "python",
  "py",
  "rust",
  "sh",
  "sql",
  "tsx",
  "ts",
  "typescript",
  "xml",
  "yaml",
  "yml",
]);
const MARKDOWN_SIGNAL_RE = /(^|\n)\s*(?:#{1,6}\s+\S|[-*+]\s+\S|\d+\.\s+\S|>\s+\S|\|.+\|)|\*\*[^*\n]{1,120}\*\*|`[^`\n]{1,120}`/;
const CODE_SIGNAL_RE = /(^|\n)\s*(?:import|from|export|const|let|var|function|class|def|return|if|for|while|try|catch|with|type|interface)\b|[{};]\s*$|^\s*[$>]\s+/m;
const ROOT_FILE_NAMES = new Set([
  "AGENTS.md",
  "README.md",
  "Dockerfile",
  "Makefile",
  "package.json",
  "package-lock.json",
  "pnpm-lock.yaml",
  "pyproject.toml",
  "tsconfig.json",
  "next.config.js",
  "next.config.mjs",
  "next.config.ts",
  "tailwind.config.js",
  "tailwind.config.ts",
  "vite.config.ts",
  "vite.config.js",
]);
const WORKSPACE_ROOT_SEGMENTS = new Set([
  ".codex",
  "backend",
  "docs",
  "frontend",
  "harness",
  "registry",
  "runtime",
  "scripts",
  "storage",
  "task_system",
  "templates",
  "tests",
]);
const PATH_SEGMENT_SOURCE = "[^\\s\\\\/\\[\\]{}()<>\"'“”‘’|，。；：、]+";
const FILE_PATH_SOURCE = `(?:[A-Za-z]:)?[\\\\/]?${PATH_SEGMENT_SOURCE}(?:[\\\\/]${PATH_SEGMENT_SOURCE})+`;
const ROOT_FILE_SOURCE = "(?:AGENTS\\.md|README\\.md|Dockerfile|Makefile|package(?:-lock)?\\.json|pnpm-lock\\.yaml|pyproject\\.toml|tsconfig\\.json|next\\.config\\.(?:js|mjs|ts)|tailwind\\.config\\.(?:js|ts)|vite\\.config\\.(?:js|ts))";
const BARE_FILE_SOURCE = `${PATH_SEGMENT_SOURCE}\\.(?:py|tsx?|jsx?|mjs|cjs|json|md|mdx|css|scss|sass|html|ya?ml|toml|sql|sh|ps1|bat|cmd|txt|lock)`;
const FILE_REFERENCE_RE = new RegExp(
  `(^|[\\s([{\`"'“‘<，。；：、])(${FILE_PATH_SOURCE}(?::\\d{1,6}(?:[-:]\\d{1,6})?)?|${ROOT_FILE_SOURCE}(?::\\d{1,6}(?:[-:]\\d{1,6})?)?|${BARE_FILE_SOURCE}(?::\\d{1,6}(?:[-:]\\d{1,6})?)?)(?=$|[\\s)\`\\]}"'”’>，。；：、])`,
  "giu",
);

type FileReferenceCandidate = {
  displayPath: string;
  lineEndNumber?: number;
  lineNumber?: number;
  path: string;
};

type FileReference = FileReferenceCandidate & {
  index: number;
};

const assistantMarkdownComponents: Components = {
  table({ children, node: _node, ...props }) {
    return (
      <div className="markdown-table-frame" role="region" aria-label="表格内容">
        <table {...props}>{children}</table>
      </div>
    );
  },
};

function formatAssistantMarkdownForReading(text: string): string {
  const lines = repairRunawayMarkdownFences(str(text).replace(/\r\n/g, "\n")).split("\n");
  const output: string[] = [];
  let structureBlock: string[] = [];
  let inFence = false;

  const flushStructureBlock = () => {
    if (!structureBlock.length) {
      return;
    }
    if (structureBlock.length >= 2 || structureBlock.some((line) => /[┌┬┐├┼┤└┴┘─│━┃]/.test(line))) {
      output.push("```text", ...structureBlock.flatMap(expandStructureLine), "```");
    } else {
      output.push(...structureBlock);
    }
    structureBlock = [];
  };

  for (const line of lines) {
    if (FENCE_RE.test(line)) {
      flushStructureBlock();
      output.push(line);
      inFence = !inFence;
      continue;
    }
    if (!inFence && STRUCTURE_LINE_RE.test(line.trim())) {
      structureBlock.push(line);
      continue;
    }
    flushStructureBlock();
    output.push(line);
  }
  flushStructureBlock();
  return output.join("\n");
}

function repairRunawayMarkdownFences(markdown: string): string {
  const lines = markdown.split("\n");
  const output: string[] = [];
  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const fence = line.match(FENCE_OPEN_RE);
    if (!fence) {
      output.push(line);
      continue;
    }
    const marker = fence[1];
    const lang = (fence[2] || "").toLowerCase();
    const closeIndex = lines.findIndex((candidate, candidateIndex) => (
      candidateIndex > index && candidate.trimStart().startsWith(marker)
    ));
    if (closeIndex > index) {
      output.push(...lines.slice(index, closeIndex + 1));
      index = closeIndex;
      continue;
    }
    const tail = lines.slice(index + 1);
    const breakIndex = runawayFenceBreakIndex(tail, lang);
    output.push(line);
    if (breakIndex >= 0) {
      output.push(...tail.slice(0, breakIndex), marker, ...tail.slice(breakIndex));
    } else {
      output.push(...tail, marker);
    }
    break;
  }
  return output.join("\n");
}

function runawayFenceBreakIndex(lines: string[], lang: string): number {
  if (!shouldRenderFenceAsRichMarkdown(lines.join("\n"), lang)) {
    return -1;
  }
  const firstContentIndex = lines.findIndex((line) => line.trim());
  if (firstContentIndex < 0) {
    return -1;
  }
  const firstContent = lines[firstContentIndex].trim();
  if (isStandaloneSignatureLine(firstContent)) {
    const proseIndex = lines.findIndex((line, index) => index > firstContentIndex && REPORT_PROSE_RE.test(line.trim()));
    if (proseIndex > firstContentIndex) {
      return proseIndex;
    }
  }
  const headingIndex = lines.findIndex((line, index) => (
    index > firstContentIndex
    && REPORT_HEADING_RE.test(line.trim())
    && lines.slice(firstContentIndex, index).some((candidate) => REPORT_PROSE_RE.test(candidate.trim()))
  ));
  return headingIndex > firstContentIndex ? headingIndex : -1;
}

function createAssistantMarkdownComponents(
  fileReferences: Map<string, FileReference>,
  fileNameIndex?: Map<string, string>,
  onOpenWorkspaceFile?: (path: string, options?: { lineNumber?: number }) => void,
  workspaceRoot?: string,
): Components {
  const renderTextReferences = (children: React.ReactNode) => (
    renderMarkdownTextReferences(children, fileReferences, fileNameIndex, onOpenWorkspaceFile, workspaceRoot)
  );
  const richFenceComponents = createRichFenceMarkdownComponents(renderTextReferences);

  return {
    ...assistantMarkdownComponents,
    a({ children, href, node: _node, ...props }) {
      const reference = href ? indexedFileReferenceFromCandidate(href, fileReferences, fileNameIndex) : null;
      if (reference) {
        return (
          <FileReferenceChip
            onOpenWorkspaceFile={onOpenWorkspaceFile}
            reference={reference}
            workspaceRoot={workspaceRoot}
          />
        );
      }
      return (
        <a {...props} href={href}>
          {children}
        </a>
      );
    },
    pre({ children, className, node: _node, ref: _ref, ...props }) {
      const fence = codeFenceFromPreChildren(children);
      if (fence && shouldRenderFenceAsRichMarkdown(fence.text, fence.language)) {
        const reportClassName = ["markdown-fenced-report", className].filter(Boolean).join(" ");
        return (
          <div className={reportClassName || "markdown-fenced-report"}>
            <ReactMarkdown components={richFenceComponents} remarkPlugins={[remarkGfm]}>
              {normalizeRichFenceMarkdown(fence.text)}
            </ReactMarkdown>
          </div>
        );
      }
      return <pre className={className} {...props}>{children}</pre>;
    },
    code({ children, className, node: _node, ...props }) {
      const text = plainTextFromReactNode(children).trim();
      const reference = !className && !text.includes("\n")
        ? indexedFileReferenceFromCandidate(text, fileReferences, fileNameIndex)
        : null;
      if (reference) {
        return (
          <FileReferenceChip
            onOpenWorkspaceFile={onOpenWorkspaceFile}
            reference={reference}
            workspaceRoot={workspaceRoot}
          />
        );
      }
      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    },
    em({ children, node: _node, ...props }) {
      return <em {...props}>{renderTextReferences(children)}</em>;
    },
    h1({ children, node: _node, ...props }) {
      return <h1 {...props}>{renderTextReferences(children)}</h1>;
    },
    h2({ children, node: _node, ...props }) {
      return <h2 {...props}>{renderTextReferences(children)}</h2>;
    },
    h3({ children, node: _node, ...props }) {
      return <h3 {...props}>{renderTextReferences(children)}</h3>;
    },
    h4({ children, node: _node, ...props }) {
      return <h4 {...props}>{renderTextReferences(children)}</h4>;
    },
    li({ children, node: _node, ...props }) {
      return <li {...props}>{renderTextReferences(children)}</li>;
    },
    p({ children, node: _node, ...props }) {
      return <p {...props}>{renderTextReferences(children)}</p>;
    },
    strong({ children, node: _node, ...props }) {
      return <strong {...props}>{renderTextReferences(children)}</strong>;
    },
    td({ children, node: _node, ...props }) {
      return <td {...props}>{renderTextReferences(children)}</td>;
    },
    th({ children, node: _node, ...props }) {
      return <th {...props}>{renderTextReferences(children)}</th>;
    },
  };
}

function createRichFenceMarkdownComponents(
  renderTextReferences: (children: React.ReactNode) => React.ReactNode,
): Components {
  const components: Components = {
    ...assistantMarkdownComponents,
    pre({ children, className, node: _node, ref: _ref, ...props }) {
      const fence = codeFenceFromPreChildren(children);
      if (fence && shouldRenderFenceAsRichMarkdown(fence.text, fence.language)) {
        const reportClassName = ["markdown-fenced-report", "markdown-fenced-report--nested", className]
          .filter(Boolean)
          .join(" ");
        return (
          <div className={reportClassName}>
            <ReactMarkdown components={components} remarkPlugins={[remarkGfm]}>
              {normalizeRichFenceMarkdown(fence.text)}
            </ReactMarkdown>
          </div>
        );
      }
      return <pre className={className} {...props}>{children}</pre>;
    },
    code({ children, className, node: _node, ...props }) {
      return (
        <code className={className} {...props}>
          {children}
        </code>
      );
    },
    em({ children, node: _node, ...props }) {
      return <em {...props}>{renderTextReferences(children)}</em>;
    },
    h1({ children, node: _node, ...props }) {
      return <h1 {...props}>{renderTextReferences(children)}</h1>;
    },
    h2({ children, node: _node, ...props }) {
      return <h2 {...props}>{renderTextReferences(children)}</h2>;
    },
    h3({ children, node: _node, ...props }) {
      return <h3 {...props}>{renderTextReferences(children)}</h3>;
    },
    h4({ children, node: _node, ...props }) {
      return <h4 {...props}>{renderTextReferences(children)}</h4>;
    },
    li({ children, node: _node, ...props }) {
      return <li {...props}>{renderTextReferences(children)}</li>;
    },
    p({ children, node: _node, ...props }) {
      return <p {...props}>{renderTextReferences(children)}</p>;
    },
    strong({ children, node: _node, ...props }) {
      return <strong {...props}>{renderTextReferences(children)}</strong>;
    },
    td({ children, node: _node, ...props }) {
      return <td {...props}>{renderTextReferences(children)}</td>;
    },
    th({ children, node: _node, ...props }) {
      return <th {...props}>{renderTextReferences(children)}</th>;
    },
  };
  return components;
}

function codeFenceFromPreChildren(children: React.ReactNode): { language: string; text: string } | null {
  const child = React.Children.toArray(children).find((item) => React.isValidElement(item));
  if (!React.isValidElement<{ className?: string; children?: React.ReactNode }>(child)) {
    return null;
  }
  const className = child.props.className || "";
  const language = className.match(/(?:^|\s)language-([A-Za-z0-9_-]+)/)?.[1]?.toLowerCase() || "";
  const text = plainTextFromReactNode(child.props.children).replace(/\n$/, "");
  return text ? { language, text } : null;
}

function shouldRenderFenceAsRichMarkdown(text: string, language: string): boolean {
  const normalizedLanguage = language.trim().toLowerCase();
  const normalizedText = text.trim();
  if (normalizedText.length < 80 || looksLikeAsciiDiagram(normalizedText)) {
    return false;
  }
  const markdownScore = markdownSignalScore(normalizedText);
  const codeScore = codeSignalScore(normalizedText);
  if (CODE_LIKE_FENCE_LANGS.has(normalizedLanguage)) {
    return hasRichMarkdownSyntax(normalizedText)
      && markdownScore >= 6
      && proseLineCount(normalizedText) >= 1
      && markdownScore >= codeScore + 2;
  }
  if (normalizedLanguage && !REPORT_LIKE_FENCE_LANGS.has(normalizedLanguage)) {
    return false;
  }
  return markdownScore >= 4 && markdownScore >= codeScore + 2;
}

function normalizeRichFenceMarkdown(text: string): string {
  const normalized = text.replace(/\r\n/g, "\n").trim();
  const lines = normalized.split("\n");
  const firstTextIndex = lines.findIndex((line) => line.trim());
  if (firstTextIndex < 0) {
    return normalized;
  }
  const firstLine = lines[firstTextIndex].trim();
  if (isStandaloneSignatureLine(firstLine) && !REPORT_HEADING_RE.test(firstLine)) {
    const next = [...lines];
    next[firstTextIndex] = `#### \`${firstLine.replace(/`/g, "")}\``;
    return next.join("\n");
  }
  return normalized;
}

function markdownSignalScore(text: string): number {
  const lines = text.split("\n");
  let score = MARKDOWN_SIGNAL_RE.test(text) ? 2 : 0;
  lines.forEach((line) => {
    const trimmed = line.trim();
    if (!trimmed) return;
    if (/^#{1,6}\s+\S/.test(trimmed)) score += 3;
    if (/^(?:[-*+]\s+\S|\d+\.\s+\S)/.test(trimmed)) score += 1;
    if (/\*\*[^*\n]{1,120}\*\*/.test(trimmed)) score += 2;
    if (/`[^`\n]{1,120}`/.test(trimmed)) score += 1;
    if (REPORT_PROSE_RE.test(trimmed)) score += 1;
  });
  return score;
}

function codeSignalScore(text: string): number {
  const lines = text.split("\n").filter((line) => line.trim());
  let score = CODE_SIGNAL_RE.test(text) ? 2 : 0;
  lines.forEach((line) => {
    const trimmed = line.trim();
    if (/^(?:import|from|export|const|let|var|function|class|def|return|if|for|while|try|catch|with|type|interface)\b/.test(trimmed)) {
      score += 2;
    }
    if (/[{};]\s*$/.test(trimmed)) score += 1;
    if (/^\s{2,}\S/.test(line)) score += 0.5;
  });
  return score;
}

function proseLineCount(text: string): number {
  return text.split("\n").filter((line) => REPORT_PROSE_RE.test(line.trim())).length;
}

function hasRichMarkdownSyntax(text: string): boolean {
  return /(^|\n)\s*#{1,6}\s+\S|(^|\n)\s*(?:[-*+]\s+\S|\d+\.\s+\S)|\*\*[^*\n]{1,120}\*\*/m.test(text);
}

function looksLikeAsciiDiagram(text: string): boolean {
  const lines = text.split("\n").filter((line) => line.trim());
  if (lines.length < 3) return false;
  const diagramLines = lines.filter((line) => /[┌┬┐├┼┤└┴┘─│━┃╭╮╰╯]/.test(line));
  return diagramLines.length >= Math.max(2, Math.ceil(lines.length * 0.35));
}

function isStandaloneSignatureLine(line: string): boolean {
  return /^`?[\w.$:-]+(?:\([^)]*\))?(?:\s*#\s*\S.*)?`?$/.test(line) && /[\w)]/.test(line);
}

function buildFileReferenceIndex(
  markdown: string,
  fileNameIndex?: Map<string, string>,
): Map<string, FileReference> {
  const references = new Map<string, FileReference>();
  const scanText = markdownWithoutFences(markdown);
  FILE_REFERENCE_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = FILE_REFERENCE_RE.exec(scanText))) {
    const candidate = normalizedFileReferenceCandidate(match[2] || "", fileNameIndex);
    if (!candidate || references.has(candidate.path)) {
      continue;
    }
    references.set(candidate.path, {
      ...candidate,
      index: references.size + 1,
    });
  }
  return references;
}

function markdownWithoutFences(markdown: string): string {
  const lines = str(markdown).replace(/\r\n/g, "\n").split("\n");
  let inFence = false;
  return lines
    .map((line) => {
      if (FENCE_RE.test(line)) {
        inFence = !inFence;
        return "";
      }
      return inFence ? "" : line;
    })
    .join("\n");
}

function renderMarkdownTextReferences(
  children: React.ReactNode,
  fileReferences: Map<string, FileReference>,
  fileNameIndex?: Map<string, string>,
  onOpenWorkspaceFile?: (path: string, options?: { lineNumber?: number }) => void,
  workspaceRoot?: string,
): React.ReactNode {
  return React.Children.toArray(children).flatMap((child, childIndex) => {
    if (typeof child !== "string") {
      return child;
    }
    return renderTextFileReferences(child, fileReferences, fileNameIndex, onOpenWorkspaceFile, workspaceRoot, `file-ref-${childIndex}`);
  });
}

function renderTextFileReferences(
  text: string,
  fileReferences: Map<string, FileReference>,
  fileNameIndex: Map<string, string> | undefined,
  onOpenWorkspaceFile: ((path: string, options?: { lineNumber?: number }) => void) | undefined,
  workspaceRoot: string | undefined,
  keyPrefix: string,
): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let cursor = 0;
  let partIndex = 0;
  FILE_REFERENCE_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = FILE_REFERENCE_RE.exec(text))) {
    const fullMatch = match[0] || "";
    const prefix = match[1] || "";
    const rawCandidate = match[2] || "";
    const candidateStart = match.index + prefix.length;
    const candidateEnd = match.index + fullMatch.length;
    const reference = indexedFileReferenceFromCandidate(rawCandidate, fileReferences, fileNameIndex);
    if (!reference) {
      continue;
    }
    if (candidateStart > cursor) {
      parts.push(text.slice(cursor, candidateStart));
    }
    const suffix = trailingFileReferenceSuffix(rawCandidate);
    parts.push(
      <FileReferenceChip
        key={`${keyPrefix}-${partIndex}`}
        onOpenWorkspaceFile={onOpenWorkspaceFile}
        reference={reference}
        workspaceRoot={workspaceRoot}
      />,
    );
    if (suffix) {
      parts.push(suffix);
    }
    cursor = candidateEnd;
    partIndex += 1;
  }
  if (cursor < text.length) {
    parts.push(text.slice(cursor));
  }
  return parts.length ? parts : [text];
}

function indexedFileReferenceFromCandidate(
  value: string,
  fileReferences: Map<string, FileReference>,
  fileNameIndex?: Map<string, string>,
): FileReference | null {
  const candidate = normalizedFileReferenceCandidate(value, fileNameIndex);
  if (!candidate) {
    return null;
  }
  const indexed = fileReferences.get(candidate.path);
  if (!indexed) {
    return null;
  }
  return {
    ...indexed,
    displayPath: candidate.displayPath,
    lineEndNumber: candidate.lineEndNumber,
    lineNumber: candidate.lineNumber,
  };
}

function normalizedFileReferenceCandidate(
  value: string,
  fileNameIndex?: Map<string, string>,
): FileReferenceCandidate | null {
  const stripped = stripFileReferenceToken(value);
  if (!stripped || stripped.includes("://") || stripped.startsWith("@") || stripped.startsWith("--")) {
    return null;
  }
  const withoutFileProtocol = stripped.replace(/^file:[\\/]+/i, "");
  const lineSuffixMatch = withoutFileProtocol.match(/:(\d{1,6})(?:[-:](\d{1,6}))?$/);
  const lineSuffix = lineSuffixMatch?.[0] ?? "";
  const lineNumber = boundedLineNumber(lineSuffixMatch?.[1]);
  const lineEndNumber = boundedLineNumber(lineSuffixMatch?.[2]);
  const withoutLineSuffix = lineSuffix
    ? withoutFileProtocol.slice(0, -lineSuffix.length)
    : withoutFileProtocol;
  const normalized = withoutLineSuffix
    .replace(/\\/g, "/")
    .replace(/^\/+([A-Za-z]:\/)/, "$1")
    .replace(/^\.\//, "")
    .replace(/\/+/g, "/");
  const workspacePath = workspaceRelativeFilePath(normalized, fileNameIndex);
  if (!workspacePath || workspacePath.includes("\0")) {
    return null;
  }
  const segments = workspacePath.split("/");
  const filename = segments[segments.length - 1] || "";
  if (!filename || segments.some((segment) => segment === "." || segment === "..")) {
    return null;
  }
  if (!ROOT_FILE_NAMES.has(filename) && !/\.[A-Za-z0-9]{1,12}$/.test(filename)) {
    return null;
  }
  return {
    displayPath: `${workspacePath}${lineSuffix}`,
    lineEndNumber,
    lineNumber,
    path: workspacePath,
  };
}

function boundedLineNumber(value: string | undefined): number | undefined {
  const lineNumber = Number(value);
  return Number.isInteger(lineNumber) && lineNumber > 0 ? Math.min(lineNumber, 999999) : undefined;
}

function workspaceRelativeFilePath(path: string, fileNameIndex?: Map<string, string>): string {
  const trimmed = path.replace(/^\/+/, "");
  if (ROOT_FILE_NAMES.has(trimmed)) {
    return trimmed;
  }
  if (!/[\\/]/.test(trimmed)) {
    return fileNameIndex?.get(trimmed.toLowerCase()) || "";
  }
  const parts = trimmed.split("/").filter(Boolean);
  const rootIndex = parts.findIndex((part) => WORKSPACE_ROOT_SEGMENTS.has(part));
  if (rootIndex < 0) {
    return "";
  }
  return parts.slice(rootIndex).join("/");
}

function stripFileReferenceToken(value: string): string {
  return str(value)
    .trim()
    .replace(/^[`"'“”‘’(<\[]+/, "")
    .replace(/[`"'“”‘’)>\\\],.;!?，。；：、]+$/u, "");
}

function trailingFileReferenceSuffix(value: string): string {
  const raw = str(value).trim();
  const stripped = stripFileReferenceToken(raw);
  return raw.startsWith(stripped) ? raw.slice(stripped.length) : "";
}

function plainTextFromReactNode(value: React.ReactNode): string {
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map(plainTextFromReactNode).join("");
  }
  return "";
}

function FileReferenceChip({
  onOpenWorkspaceFile,
  reference,
  workspaceRoot,
}: {
  onOpenWorkspaceFile?: (path: string, options?: { lineNumber?: number }) => void;
  reference: FileReference;
  workspaceRoot?: string;
}) {
  const filename = compactFileReferenceName(reference.path);
  const lineLabel = fileReferenceLineLabel(reference);
  const title = fullFileReferenceTitle(reference, workspaceRoot);
  const content = (
    <>
      <FileText aria-hidden="true" className="markdown-file-ref__icon" size={13} />
      <span className="markdown-file-ref__name">{filename}</span>
      {lineLabel ? <span className="markdown-file-ref__line"> {lineLabel}</span> : null}
    </>
  );
  if (!onOpenWorkspaceFile) {
    return (
      <span className="markdown-file-ref" title={title}>
        {content}
      </span>
    );
  }
  return (
    <button
      aria-label={`打开 ${title}`}
      className="markdown-file-ref markdown-file-ref--button"
      onClick={() => onOpenWorkspaceFile(reference.path, { lineNumber: reference.lineNumber })}
      title={title}
      type="button"
    >
      {content}
    </button>
  );
}

function compactFileReferenceName(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  const segments = normalized.split("/");
  return segments[segments.length - 1] || normalized || "文件";
}

function fileReferenceLineLabel(reference: FileReference): string {
  if (!reference.lineNumber) {
    return "";
  }
  if (reference.lineEndNumber && reference.lineEndNumber > reference.lineNumber) {
    return `(lines ${reference.lineNumber}-${reference.lineEndNumber})`;
  }
  return `(line ${reference.lineNumber})`;
}

function fullFileReferenceTitle(reference: FileReference, workspaceRoot?: string): string {
  const root = str(workspaceRoot || "").trim().replace(/\\/g, "/").replace(/\/+$/, "");
  const path = reference.path.replace(/\\/g, "/").replace(/^\/+/, "");
  const fullPath = root ? `${root}/${path}` : path;
  if (reference.lineEndNumber && reference.lineEndNumber > (reference.lineNumber || 0)) {
    return `${fullPath}:${reference.lineNumber}-${reference.lineEndNumber}`;
  }
  return reference.lineNumber ? `${fullPath}:${reference.lineNumber}` : fullPath;
}

function expandStructureLine(line: string): string[] {
  return line
    .replace(/\s+(?=[├└]──)/g, "\n  ")
    .split("\n")
    .map((item) => item.trimEnd());
}

function str(value: string): string {
  return value || "";
}

export function AssistantMessage({
  copiedReply,
  copyableReplyText,
  displayText,
  explicitBodyText,
  fileNameIndex,
  image,
  imageUnavailable,
  onCopyReply,
  onOpenWorkspaceFile,
  onImageError,
  showCopy,
  streamingContent,
  workspaceRoot,
}: AssistantMessageProps) {
  const readableMarkdown = React.useMemo(
    () => formatAssistantMarkdownForReading(displayText),
    [displayText],
  );
  const fileReferences = React.useMemo(
    () => buildFileReferenceIndex(readableMarkdown, fileNameIndex),
    [fileNameIndex, readableMarkdown],
  );
  const markdownComponents = React.useMemo(
    () => createAssistantMarkdownComponents(fileReferences, fileNameIndex, onOpenWorkspaceFile, workspaceRoot),
    [fileNameIndex, fileReferences, onOpenWorkspaceFile, workspaceRoot],
  );

  return (
    <div className="chat-message-shell__content markdown markdown--assistant-closeout">
      {showCopy && copyableReplyText ? (
        <button
          aria-label={copiedReply ? "已复制回复" : "复制回复"}
          className="message-copy-button"
          onClick={onCopyReply}
          title={copiedReply ? "已复制" : "复制回复"}
          type="button"
        >
          {copiedReply ? <Check size={13} /> : <Copy size={13} />}
        </button>
      ) : null}
      {!explicitBodyText && image?.src && !imageUnavailable ? (
        <figure className="chat-image-message">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            alt={image.alt || "生成图像"}
            loading="lazy"
            onError={() => onImageError(image.src)}
            src={image.src}
          />
          {image.caption ? <figcaption>{image.caption}</figcaption> : null}
        </figure>
      ) : !explicitBodyText && imageUnavailable ? (
        <div className="chat-image-message chat-image-message--missing">
          <p>图像文件不可用。</p>
          <span>{image?.src}</span>
        </div>
      ) : streamingContent ? (
        <span className="chat-message-shell__streaming-text">{displayText}</span>
      ) : (
        <ReactMarkdown components={markdownComponents} remarkPlugins={[remarkGfm]}>
          {readableMarkdown}
        </ReactMarkdown>
      )}
    </div>
  );
}
