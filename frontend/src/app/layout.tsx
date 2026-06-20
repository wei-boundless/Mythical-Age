import type { Metadata } from "next";

import "./globals.css";
import "../styles/00-foundation.css";
import "../styles/01-chat-workbench.css";
import "../styles/02-memory.css";
import "../styles/03-orchestration-and-controls.css";
import "../styles/04-workspace-shell-base.css";
import "../styles/05-capability-system.css";
import "../styles/06-system-config.css";
import "../styles/07-health-system.css";
import "../styles/08-orchestration-console.css";
import "../styles/09-practical-workspace-shell.css";
import "../styles/10-console-unification.css";
import "../styles/11-final-chat-workbench.css";
import "../styles/12-soft-agent-console.css";
import "../styles/13-graph-foreground.css";
import "../styles/14-crisp-agent-console.css";

export const metadata: Metadata = {
  title: "Mythical Age | 洪荒智能",
  description: "洪荒智能：透明、文件优先的本地 AI agent 系统。",
  icons: {
    icon: [
      { url: "/favicon.svg", type: "image/svg+xml" },
    ],
  },
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
