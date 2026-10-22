import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Workbench from "../workbench/Workbench";
import Properties from "../workbench/Properties";
import { makeSampleSpec } from "../spec";

function renderProps(mode: "import" | "material-test" = "import") {
  render(<Workbench mode={mode} spec={makeSampleSpec()} onBack={() => {}} />);
}

describe("properties", () => {
  it("lists every object of the shared Job Spec", () => {
    renderProps();
    for (const id of ["test_zone", "title", "grid_power_speed"]) {
      expect(screen.getByTestId(`object-${id}`)).toBeTruthy();
    }
  });

  it("shows the material of the document", () => {
    renderProps();
    const material = screen.getByTestId("props-material");
    expect(material.textContent).toContain("basswood-3mm");
    expect(material.textContent).toContain("safe");
  });

  it("reflects the selected: import door preselects the rect and shows geometry", () => {
    renderProps("import");
    expect(screen.getByTestId("props-test_zone")).toBeTruthy();
    const props = screen.getByTestId("props-test_zone");
    expect(props.textContent).toContain("w");
    expect(props.textContent).toContain("210");
  });

  it("reflects the selected: text object shows font fields and text", async () => {
    const user = userEvent.setup();
    renderProps("import");
    await user.click(screen.getByTestId("object-title"));
    const props = screen.getByTestId("props-title");
    expect(props.textContent).toContain("potenza x velocita' griglia");
    expect(props.textContent).toContain("dejavu");
    expect(props.textContent).toContain("height_mm");
    // the previous selection's panel is gone
    expect(screen.queryByTestId("props-test_zone")).toBeNull();
  });

  it("reflects the selected: material-test door preselects the grid, showing axes and labels", () => {
    renderProps("material-test");
    const props = screen.getByTestId("props-grid_power_speed");
    expect(props.textContent).toContain("row_labels");
    expect(props.textContent).toContain("col_labels");
    expect(props.textContent).toContain("1600");
    expect(screen.getByTestId("prop-axes").textContent).toContain('"axis"');
  });

  it("shows the empty hint when no object is selected", () => {
    render(
      <Properties
        spec={makeSampleSpec()}
        selectedId={null}
        onSelect={() => {}}
      />,
    );
    expect(screen.getByTestId("props-empty")).toBeTruthy();
    expect(screen.queryByTestId("props-test_zone")).toBeNull();
  });
});
