import type { Metadata } from "next";

import "./globals.css";
import "../styles/00-foundation.css";
import "../styles/01-theme-templates.css";
import "../styles/02-workbench-shell.css";
import "../styles/03-workbench-primitives.css";
import "../styles/04-chat-workbench.css";
import "../styles/05-system-pages.css";
import "../styles/06-task-workbench.css";
import "../styles/07-agent-management.css";

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
    <html data-workbench-density="standard" data-workbench-theme="clean-light" lang="zh-CN" suppressHydrationWarning>
      <body>
        <script dangerouslySetInnerHTML={{
          __html: `(function(){try{var t=localStorage.getItem("workbenchTheme")||localStorage.getItem("workbench-theme");var s=localStorage.getItem("workbenchCustomSettings");if(t){document.documentElement.setAttribute("data-workbench-theme",t);var c=["clean-light","warm-paper","ocean-breeze","mineral-gray","lavender-mist","focus-dark","midnight-ocean","charcoal-ember"];if(!c.includes(t))document.documentElement.setAttribute("data-workbench-theme","clean-light")}if(s){try{var o=JSON.parse(s);if(o.bgImage)document.documentElement.style.setProperty("--workbench-bg-image","url(\\""+o.bgImage+"\\")")}catch(e){}}if(t==="focus-dark"||t==="midnight-ocean"||t==="charcoal-ember")document.documentElement.style.colorScheme="dark";else document.documentElement.style.colorScheme="light"}catch(e){}})()`,
        }} />
        {children}
      </body>
    </html>
  );
}
