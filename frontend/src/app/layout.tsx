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
      <head>
        <link rel="preconnect" href="https://fonts.googleapis.com" />
        <link rel="preconnect" href="https://fonts.gstatic.com" crossOrigin="anonymous" />
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Nunito:wght@400;500;600;700&family=Noto+Sans+SC:wght@400;500;700&family=Noto+Serif+SC:wght@400;500;700&display=swap" rel="stylesheet" />
      </head>
      <body>
        <script dangerouslySetInnerHTML={{
          __html: `(function(){try{var t=localStorage.getItem("workbenchTheme")||localStorage.getItem("workbench-theme");var s=localStorage.getItem("workbenchCustomSettings");if(t){document.documentElement.setAttribute("data-workbench-theme",t);var c=["clean-light","warm-paper","ocean-breeze","mineral-gray","lavender-mist","focus-dark","midnight-ocean","charcoal-ember"];if(!c.includes(t))document.documentElement.setAttribute("data-workbench-theme","clean-light")}if(s){try{var o=JSON.parse(s);if(o.bgImage)document.documentElement.style.setProperty("--workbench-bg-image","url(\\""+o.bgImage+"\\")");if(o.fontOverride){var f=[{id:"system",fd:"system-ui, -apple-system, BlinkMacSystemFont, \\"Segoe UI\\", \\"Microsoft YaHei UI\\", \\"PingFang SC\\", \\"Noto Sans SC\\", sans-serif",fm:"\\"Cascadia Mono\\", \\"Consolas\\", \\"SFMono-Regular\\", monospace"},{id:"modern",fd:"\\"Inter\\", \\"Noto Sans SC\\", \\"Segoe UI Variable\\", -apple-system, system-ui, sans-serif",fm:"\\"JetBrains Mono\\", \\"Fira Code\\", \\"Cascadia Code\\", \\"Consolas\\", monospace"},{id:"classic",fd:"\\"Noto Serif SC\\", \\"Source Serif 4\\", \\"Palatino Linotype\\", \\"Palatino\\", Georgia, serif",fm:"\\"Cascadia Mono\\", \\"Consolas\\", \\"SFMono-Regular\\", monospace"},{id:"rounded",fd:"\\"Nunito\\", \\"Noto Sans SC\\", \\"PingFang SC\\", \\"Microsoft YaHei UI\\", system-ui, sans-serif",fm:"\\"Cascadia Mono\\", \\"Consolas\\", \\"SFMono-Regular\\", monospace"},{id:"code-friendly",fd:"\\"SF Mono\\", \\"Cascadia Code\\", \\"JetBrains Mono\\", \\"Consolas\\", monospace",fm:"\\"SF Mono\\", \\"Cascadia Code\\", \\"JetBrains Mono\\", \\"Consolas\\", monospace"}];var m=f.find(function(x){return x.id===o.fontOverride});if(m){document.documentElement.style.setProperty("--font-display",m.fd);document.documentElement.style.setProperty("--font-mono",m.fm);document.documentElement.style.setProperty("--console-font",m.fd);document.documentElement.style.setProperty("--console-mono",m.fm);document.documentElement.style.setProperty("--workbench-font",m.fd);document.documentElement.style.setProperty("--workbench-font-mono",m.fm);document.documentElement.style.setProperty("--font-sans",m.fd);document.documentElement.style.setProperty("--font-brand-latin",m.fd)}}if(o.fontSizeScale){var s2=o.fontSizeScale;document.documentElement.style.setProperty("--console-font-size-ui",Math.round(15*s2)+"px");document.documentElement.style.setProperty("--console-font-size-page",Math.round(16*s2)+"px");document.documentElement.style.setProperty("--console-font-size-body",Math.round(17*s2)+"px");document.documentElement.style.fontSize=Math.round(15*s2)+"px"}if(o.customColorsEnabled===true){if(o.bgColor)document.documentElement.style.setProperty("--console-bg",o.bgColor);if(o.panelColor){document.documentElement.style.setProperty("--console-surface",o.panelColor);document.documentElement.style.setProperty("--console-bg-raised",o.panelColor)}if(o.accentSoftColor)document.documentElement.style.setProperty("--console-accent-soft",o.accentSoftColor)}}catch(e){}}if(t==="focus-dark"||t==="midnight-ocean"||t==="charcoal-ember")document.documentElement.style.colorScheme="dark";else document.documentElement.style.colorScheme="light"}catch(e){}})()`,
        }} />
        {children}
      </body>
    </html>
  );
}
