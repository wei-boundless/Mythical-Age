import type { Components } from "react-markdown";

export function markdownLinkOpensOutsideWorkbench(href?: string) {
  const value = String(href || "").trim().toLowerCase();
  return value.startsWith("http://")
    || value.startsWith("https://")
    || value.startsWith("/output/")
    || value.startsWith("output/");
}

export const workbenchMarkdownComponents: Components = {
  a({ children, href, node: _node, ...props }) {
    const opensOutsideWorkbench = markdownLinkOpensOutsideWorkbench(href);
    return (
      <a
        {...props}
        href={href}
        {...(opensOutsideWorkbench ? { rel: "noopener noreferrer", target: "_blank" } : {})}
      >
        {children}
      </a>
    );
  },
  table({ children, node: _node, ...props }) {
    return (
      <div className="markdown-table-frame" role="region" aria-label="表格内容">
        <table {...props}>{children}</table>
      </div>
    );
  },
};
