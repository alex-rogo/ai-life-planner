import type { Metadata } from "next";
import { Familjen_Grotesk, IBM_Plex_Mono } from "next/font/google";
import { THEME_SCRIPT } from "../lib/theme";
import AuthProvider from "../components/auth-provider";
import "./globals.css";

const grotesk = Familjen_Grotesk({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-grotesk" });
const mono = IBM_Plex_Mono({ subsets: ["latin"], weight: ["400", "500"], variable: "--font-plex-mono" });
export const metadata: Metadata = { title: "Tomo", description: "Say what changed. Tomo reworks your day." };
export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  // suppressHydrationWarning: the theme script may set data-theme on <html> before React loads.
  return (
    <html lang="en" className={`${grotesk.variable} ${mono.variable}`} suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: THEME_SCRIPT }} /></head>
      <body><AuthProvider>{children}</AuthProvider></body>
    </html>
  );
}
