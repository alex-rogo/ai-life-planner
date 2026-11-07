"use client";

import { ClerkProvider } from "@clerk/react";

const key = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  if (!key) return <>{children}</>;
  return <ClerkProvider publishableKey={key}>{children}</ClerkProvider>;
}
