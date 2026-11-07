import { useState } from "react";

interface Seen { scope: string; signature: string; known: string[]; fresh: string[]; primed: boolean; }
const prefersReducedMotion = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * Keys that just appeared in a list, so they can grow in instead of popping into place. The first
 * data (`ready` turning true) and a change of `scope` (navigating to another range) never animate.
 * A key stays fresh until the list changes again; its animation only plays when it mounts.
 */
export function useArrivals(keys: string[], scope: string, ready = true): Set<string> {
  const signature = keys.join("\n");
  const [seen, setSeen] = useState<Seen>({ scope, signature, known: keys, fresh: [], primed: ready });
  if (seen.scope !== scope || seen.signature !== signature || seen.primed !== ready) {
    // Adjusted while rendering, like useStage(), so no frame shows a new item without its animation.
    const animate = ready && seen.primed && seen.scope === scope && !prefersReducedMotion();
    const known = new Set(seen.known);
    setSeen({ scope, signature, known: keys, fresh: animate ? keys.filter(k => !known.has(k)) : [], primed: ready });
  }
  return new Set(seen.fresh);
}
