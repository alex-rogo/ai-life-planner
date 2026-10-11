import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import ThemeToggle from "../components/theme-toggle";

afterEach(() => { delete document.documentElement.dataset.theme; localStorage.clear(); vi.unstubAllGlobals(); });

it("follows the system theme, then switches and remembers an explicit choice", async () => {
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("dark"), addEventListener() {}, removeEventListener() {} }));
  render(<ThemeToggle />);
  const button = screen.getByRole("button", { name: "Switch to light mode" });
  await userEvent.click(button);
  expect(document.documentElement.dataset.theme).toBe("light");
  expect(localStorage.getItem("tomo-theme")).toBe("light");
  expect(screen.getByRole("button", { name: "Switch to dark mode" })).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Switch to dark mode" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
});
