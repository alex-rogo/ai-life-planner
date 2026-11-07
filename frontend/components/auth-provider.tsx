"use client";

import { ClerkProvider } from "@clerk/react";

const key = process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  if (!key) return <>{children}</>;
  return <ClerkProvider publishableKey={key} signInUrl="/sign-in" signUpUrl="/sign-up" localization={{
    signIn: { start: { title: "Sign in to Tomo" } },
    signUp: { start: { title: "Create your Tomo account" } },
  }}>{children}</ClerkProvider>;
}
