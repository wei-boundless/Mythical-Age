import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "The Mythical Agent",
  description: "A transparent, file-first local AI agent system.",
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
