import type { Metadata } from "next";
import "./globals.css";
import TopBar from "@/components/TopBar";

export const metadata: Metadata = {
  title: "NEWS INTEL — Intelligence Terminal",
  description: "AI-powered news intelligence platform",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full">
      <body className="h-full flex flex-col overflow-hidden" style={{ background: "var(--bg)" }}>
        <TopBar />
        <main className="flex-1 overflow-hidden">{children}</main>
      </body>
    </html>
  );
}
