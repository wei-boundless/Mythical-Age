"use client";

import { Check, Copy } from "lucide-react";
import React from "react";
import ReactMarkdown from "react-markdown";
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
  return (
    <div className="chat-message-shell__content markdown">
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
        <ReactMarkdown remarkPlugins={[remarkGfm]}>
          {displayText}
        </ReactMarkdown>
      )}
    </div>
  );
}
