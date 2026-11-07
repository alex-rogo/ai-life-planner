"use client";

import { SignIn } from "@clerk/react";
import Link from "next/link";
import { useEffect } from "react";

export default function SignInPage() {
  useEffect(() => { localStorage.removeItem("tomo_mode"); }, []);
  return <main className="entry-auth">
    <Link className="entry-back" href="/">← Tomo</Link>
    <div className="entry-auth-intro"><span className="entry-eyebrow">YOUR OWN SPACE</span><h1>Welcome back.</h1><p>Your plan stays yours, across visits and devices.</p></div>
    {process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
      ? <SignIn
          routing="hash" forceRedirectUrl="/app" signUpForceRedirectUrl="/app" signUpUrl="/sign-up"
          appearance={{ variables: {
            colorPrimary: "#D9531E", colorPrimaryForeground: "#FFFFFF",
            colorBackground: "var(--paper)", colorForeground: "var(--ink)",
            colorMutedForeground: "var(--muted)", colorBorder: "var(--line)",
            colorInput: "var(--bg)", colorInputForeground: "var(--ink)",
            fontFamily: "var(--sans)", borderRadius: "12px",
          } }}
        />
      : <div className="card panel"><p>Sign-in is being configured. You can explore the demo now.</p><Link href="/demo">Try the demo</Link></div>}
  </main>;
}
