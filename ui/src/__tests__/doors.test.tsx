import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import App from "../App";
import { DOORS, type DoorConfig } from "../doors/config";
import { makeSampleSpec } from "../spec";

describe("four doors -> one workbench", () => {
  it("renders all four doors on the start screen", () => {
    render(<App />);
    for (const d of DOORS) {
      expect(screen.getByTestId(`door-${d.mode}`)).toBeTruthy();
    }
  });

  it.each(DOORS)(
    'door "$title" opens the workbench in mode $mode, preselecting its object',
    async ({ title, mode, preselectId }: DoorConfig) => {
      const user = userEvent.setup();
      render(<App />);

      // door card renders
      expect(screen.getByTestId(`door-${mode}`)).toBeTruthy();
      expect(screen.getByRole("heading", { name: title })).toBeTruthy();

      // navigate: the door drives the single workbench with its mode
      await user.click(screen.getByRole("button", { name: title }));
      const workbench = await screen.findByTestId("workbench");
      expect(workbench.getAttribute("data-mode")).toBe(mode);

      // workbench = canvas + chat + properties, all present
      expect(screen.getByTestId("canvas")).toBeTruthy();
      expect(screen.getByTestId("chat-log")).toBeTruthy();
      expect(screen.getByTestId("properties-panel")).toBeTruthy();

      // the door preconfigured the properties panel (same shared document)
      const id = preselectId(makeSampleSpec());
      expect(id).toBeTruthy();
      expect(screen.getByTestId(`props-${id}`)).toBeTruthy();
    },
  );

  it("the back button returns to the four doors", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: "Importa" }));
    expect(await screen.findByTestId("workbench")).toBeTruthy();
    await user.click(screen.getByTestId("back"));
    expect(screen.getByTestId("door-import")).toBeTruthy();
    expect(screen.queryByTestId("workbench")).toBeNull();
  });
});
