"use client";

import { SignUp } from "@clerk/react";
import Link from "next/link";
import { useEffect } from "react";

export default function SignUpPage() {
  useEffect(() => { localStorage.removeItem("tomo_mode"); }, []);
  return <main className="entry-auth">
    <Link className="entry-back" href="/">← Tomo</Link>
    <div className="entry-auth-intro"><span className="entry-eyebrow">YOUR OWN SPACE</span><h1>Make room for what matters.</h1><p>Create your own plan, then pick up where you left off on any device.</p></div>
    {process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY
      ? <SignUp
          routing="hash" forceRedirectUrl="/app" signInForceRedirectUrl="/app" signInUrl="/sign-in"
          appearance={{ variables: {
            colorPrimary: "#D9531E", colorPrimaryForeground: "#FFFFFF",
            colorBackground: "var(--paper)", colorForeground: "var(--ink)",
            colorMutedForeground: "var(--muted)", colorBorder: "var(--line)",
            colorInput: "var(--bg)", colorInputForeground: "var(--ink)",
            fontFamily: "var(--sans)", borderRadius: "12px",
          } }}
        />
      : <div className="card panel"><p>Sign-up is being configured. You can explore the demo now.</p><Link href="/demo">Try the demo</Link></div>}
  </main>;
}
