import type { Metadata } from "next";
import { Cormorant_SC, IBM_Plex_Mono, Noto_Serif_SC } from "next/font/google";

import "./globals.css";

const displayFont = Noto_Serif_SC({
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  variable: "--font-display"
});

const brandLatinFont = Cormorant_SC({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-brand-latin"
});

const monoFont = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500"],
  variable: "--font-mono"
});

export const metadata: Metadata = {
  title: "Mini-OpenClaw",
  description: "A transparent, file-first local AI agent system."
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className={`${displayFont.variable} ${brandLatinFont.variable} ${monoFont.variable}`}>
        {children}
      </body>
    </html>
  );
}
