import React from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { it, expect, vi } from "vitest";
import TaskForm from "../components/task-form";

it("submits a task estimate and UTC deadline to the service", async () => {
  const save = vi.fn().mockResolvedValue(undefined);
  render(<TaskForm goals={[]} timezone="America/Los_Angeles" onSave={save} onCancel={() => {}} />);
  await userEvent.type(screen.getByLabelText("Task name"), "Pointers");
  await userEvent.type(screen.getByLabelText(/Deadline/), "2027-01-04");
  await userEvent.click(screen.getByRole("button", { name: "Create task" }));
  await waitFor(() => expect(save).toHaveBeenCalledWith(expect.objectContaining({
    title: "Pointers", duration_minutes: 60, deadline: "2027-01-05T07:59:00.000Z",
  })));
});
it("keeps the form open and displays backend validation errors", async () => {
  const save = vi.fn().mockRejectedValue(new Error("Minimum session must fit"));
  render(<TaskForm goals={[]} timezone="UTC" onSave={save} onCancel={() => {}} />);
  await userEvent.type(screen.getByLabelText("Task name"), "Read");
  await userEvent.click(screen.getByRole("button", { name: "Create task" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Minimum session must fit");
});
