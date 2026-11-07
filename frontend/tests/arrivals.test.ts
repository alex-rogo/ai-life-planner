import { renderHook } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { useArrivals } from "../lib/arrivals";

vi.stubGlobal("matchMedia", () => ({ matches: false }));

it("marks only items that appear after the first data, within the same scope", () => {
  const { result, rerender } = renderHook(({ keys, scope, ready }) => useArrivals(keys, scope, ready), {
    initialProps: { keys: [] as string[], scope: "week:1", ready: false },
  });
  rerender({ keys: ["a", "b"], scope: "week:1", ready: true });
  expect([...result.current]).toEqual([]);
  rerender({ keys: ["a", "b", "c"], scope: "week:1", ready: true });
  expect([...result.current]).toEqual(["c"]);
  rerender({ keys: ["x"], scope: "week:2", ready: true });
  expect([...result.current]).toEqual([]);
  rerender({ keys: ["x", "y"], scope: "week:2", ready: true });
  expect([...result.current]).toEqual(["y"]);
});
