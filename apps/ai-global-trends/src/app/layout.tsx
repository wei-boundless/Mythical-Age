import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "AI Global Trends | AI 出海热文雷达",
  description: "实时追踪全球 AI 出海创业热文、行业机会和每日日报订阅。",
  icons: {
    icon: [{ url: "/favicon.svg", type: "image/svg+xml" }]
  }
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
