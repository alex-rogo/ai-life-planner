"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { api, setApiTokenGetter } from "../../lib/api";

export default function DemoEntry() {
  const router = useRouter();
  const [error, setError] = useState("");
  const started = useRef(false);
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    setApiTokenGetter(null);
    api<{ mode: string }>("/workspaces/demo", "POST")
      .then(() => { localStorage.setItem("tomo_mode", "demo"); router.replace("/app"); })
      .catch((e: Error) => setError(e.message));
  }, [router]);
  return <main className="entry-wait" role="status">
    <span className="brand">Tomo</span><h1>Preparing your own demo…</h1>
    <p>{error || "Loading a sample week you can edit freely."}</p>
    {error && <Link href="/">Back to Tomo</Link>}
  </main>;
}
