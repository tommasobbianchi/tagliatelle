import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Workbench from "../workbench/Workbench";
import { makeSampleSpec } from "../spec";

function renderWorkbench() {
  const spec = makeSampleSpec();
  render(<Workbench mode="material-test" spec={spec} onBack={() => {}} />);
  return { spec };
}

describe("canvas (two-level preview)", () => {
  it("renders the HTML canvas with the fast-preview overlay by default", () => {
    renderWorkbench();
    const canvas = screen.getByTestId("canvas");
    expect(canvas).toBeTruthy();
    expect(canvas.tagName).toBe("CANVAS");
    expect(
      screen.getByTestId("canvas-overlay").textContent,
    ).toContain("geometrica");
    // the B3 grid from the shared spec is part of the content bounds
    // (drawn via the 2d context where one exists, e.g. in a browser)
  });

  it("accurate preview shows the G-code replay placeholder and note", async () => {
    const user = userEvent.setup();
    renderWorkbench();
    await user.click(screen.getByRole("button", { name: "Anteprima accurata" }));
    expect(
      screen.getByTestId("canvas-overlay").textContent,
    ).toContain("replay");
    expect(screen.getByTestId("preview-note").textContent).toContain(
      "core/replay.py",
    );
    // switching back to fast works
    await user.click(screen.getByRole("button", { name: "Anteprima veloce" }));
    expect(
      screen.getByTestId("canvas-overlay").textContent,
    ).toContain("geometrica");
  });

  it("selecting an object keeps the canvas rendering (no crash, highlight state)", async () => {
    const user = userEvent.setup();
    renderWorkbench();
    await user.click(screen.getByTestId("object-test_zone"));
    expect(screen.getByTestId("canvas")).toBeTruthy();
    expect(screen.getByTestId("props-test_zone")).toBeTruthy();
  });
});
