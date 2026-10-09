import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "ai schedular · AI Life Assistant", description: "Make room for what matters. A local-first adaptive scheduler." };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="en"><body>{children}</body></html>;
}
