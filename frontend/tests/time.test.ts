import { describe, it, expect } from "vitest";
import { addDays, dateKey, zonedISO, duration } from "../lib/time";
describe("timezone boundaries", () => {
  it("shows UTC dates in the configured user timezone", () => {
    expect(dateKey("2027-01-05T01:00:00Z", "America/Los_Angeles")).toBe("2027-01-04");
    expect(zonedISO("2027-01-04", "23:59", "America/Los_Angeles")).toBe("2027-01-05T07:59:00.000Z");
  });
  it("handles summer offsets and rejects nonexistent DST times", () => {
    expect(zonedISO("2027-06-01", "09:00", "America/Los_Angeles")).toBe("2027-06-01T16:00:00.000Z");
    expect(() => zonedISO("2027-03-14", "02:30", "America/Los_Angeles")).toThrow();
  });
  it("moves calendar dates across month boundaries and uses elapsed duration", () => {
    expect(addDays("2027-01-31", 1)).toBe("2027-02-01");
    expect(duration({ starts_at: "2027-03-14T09:30:00Z", ends_at: "2027-03-14T10:30:00Z" })).toBe(60);
  });
});
