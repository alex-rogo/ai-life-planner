import { afterEach, it, expect, vi } from "vitest";
import { api } from "../lib/api";
afterEach(() => vi.unstubAllGlobals());
it("surfaces structured backend validation messages", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 422, json: async () => ({ detail: [{ msg: "Timezone required" }] }) }));
  await expect(api("/tasks")).rejects.toThrow("Timezone required");
});
it("handles a successful delete without parsing an empty response", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 204 }));
  expect(await api("/tasks/example", "DELETE")).toBeUndefined();
});
