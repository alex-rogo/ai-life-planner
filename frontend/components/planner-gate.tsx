"use client";

import { useAuth, useClerk } from "@clerk/react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { api, setApiTokenGetter } from "../lib/api";
import Planner from "./planner";

type Mode = "demo" | "account";
const clerkEnabled = !!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY;

function Gate({ loaded, signedIn, getToken, signOut }: {
  loaded: boolean; signedIn: boolean;
  getToken?: () => Promise<string | null>; signOut?: () => Promise<void>;
}) {
  const router = useRouter();
  const [mode, setMode] = useState<Mode | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!loaded) return;
    const next: Mode | null = localStorage.getItem("tomo_mode") === "demo" ? "demo" : signedIn ? "account" : null;
    if (!next) { router.replace("/"); return; }
    setApiTokenGetter(next === "account" ? getToken ?? null : null);
    api<{ mode: string }>("/workspaces/status")
      .then((status) => {
        if (status.mode !== next && status.mode !== "legacy") throw new Error("Planner session changed. Please enter again.");
        setMode(next);
      })
      .catch((e: Error) => {
        if (next === "demo") { localStorage.removeItem("tomo_mode"); router.replace("/"); }
        else setError(e.message);
      });
    return () => setApiTokenGetter(null);
  }, [loaded, signedIn, getToken, router]);

  const exit = async () => {
    setApiTokenGetter(null);
    localStorage.removeItem("tomo_mode");
    if (mode === "account") await signOut?.();
    router.push("/");
  };
  if (error) return <div className="entry-wait"><h1>Can’t open your planner</h1><p>{error}</p><Link href="/">Back to Tomo</Link></div>;
  if (!mode) return <div className="entry-wait" role="status">Opening your planner…</div>;
  return <Planner mode={mode} onExit={() => void exit()} />;
}

function ClerkGate() {
  const { isLoaded, isSignedIn, getToken } = useAuth();
  const { signOut } = useClerk();
  return <Gate loaded={isLoaded} signedIn={!!isSignedIn} getToken={getToken} signOut={() => signOut()} />;
}

export default function PlannerGate() {
  return clerkEnabled ? <ClerkGate /> : <Gate loaded signedIn={false} />;
}
