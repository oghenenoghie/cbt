import type { Metadata } from "next";
import "./globals.css";

import { SessionProvider } from "@/lib/session";

export const metadata: Metadata = {
  title: "Intelligent CBT | School Assessment Platform",
  description:
    "A school-controlled assessment platform with source-grounded AI question generation and online/offline examinations.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <SessionProvider>{children}</SessionProvider>
      </body>
    </html>
  );
}
