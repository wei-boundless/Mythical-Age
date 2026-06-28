import type { Components } from "react-markdown";

export const workbenchMarkdownComponents: Components = {
  table({ children, node: _node, ...props }) {
    return (
      <div className="markdown-table-frame" role="region" aria-label="表格内容">
        <table {...props}>{children}</table>
      </div>
    );
  },
};
