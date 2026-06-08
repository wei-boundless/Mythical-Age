import type { Metadata } from "next";

import "./globals.css";

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
