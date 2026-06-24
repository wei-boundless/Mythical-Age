"use client";

import { Check, Copy } from "lucide-react";
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
  image?: AssistantMessageImage | null;
  imageUnavailable: boolean;
  onCopyReply: () => void;
  onImageError: (src: string) => void;
  showCopy: boolean;
  streamingContent: boolean;
};

const STRUCTURE_LINE_RE = /(?:[┌┬┐├┼┤└┴┘─│━┃╭╮╰╯]|(?:^|\s)(?:backend|frontend|api|task_system|harness|registry|canvas|editor|instance|workbench|templates)[\w/.-]*\/.*(?:->|→|──))/i;
const FENCE_RE = /^\s*(```|~~~)/;

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
  const lines = str(text).replace(/\r\n/g, "\n").split("\n");
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
  image,
  imageUnavailable,
  onCopyReply,
  onImageError,
  showCopy,
  streamingContent,
}: AssistantMessageProps) {
  const readableMarkdown = React.useMemo(
    () => formatAssistantMarkdownForReading(displayText),
    [displayText],
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
        <ReactMarkdown components={assistantMarkdownComponents} remarkPlugins={[remarkGfm]}>
          {readableMarkdown}
        </ReactMarkdown>
      )}
    </div>
  );
}
