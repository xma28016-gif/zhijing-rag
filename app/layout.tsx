import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "知境 · 企业知识库中台",
  description: "企业知识导入、检索测试与可信问答工作台",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
