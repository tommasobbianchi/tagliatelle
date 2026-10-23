import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import A1Overlay from "../workbench/A1Overlay";
import { makeSampleA1 } from "../a1";
import App from "../App";

function renderA1() {
  const doc = makeSampleA1();
  render(<A1Overlay doc={doc} />);
  return { doc };
}

describe("A1 preview overlay", () => {
  it("renders one numbered badge per ordered profile, outer contour last", () => {
    const { doc } = renderA1();
    expect(doc.profiles.length).toBeGreaterThanOrEqual(2);

    const badges = screen.getAllByTestId("a1-badge");
    expect(badges).toHaveLength(doc.profiles.length);

    // numbered 1..N in the §4.2 work order (the profiles array order)
    badges.forEach((badge, i) => {
      expect(badge.getAttribute("data-number")).toBe(String(i + 1));
      // the visible number is drawn in the badge's text node (not its title)
      expect(badge.querySelector("text")?.textContent).toBe(String(i + 1));
      // each badge lives inside the profile group of the same order slot
      const group = badge.parentElement as SVGGElement | null;
      expect(group?.getAttribute("data-id")).toBe(doc.profiles[i].id);
    });

    // the outer contour is emphasised and ordered LAST in the proposal
    const groups = screen.getAllByTestId("a1-profile");
    expect(groups).toHaveLength(doc.profiles.length);
    const outerGroups = groups.filter((g) => g.getAttribute("data-outer") === "true");
    expect(outerGroups).toHaveLength(1); // exactly one outer contour in the document
    expect(outerGroups[0].getAttribute("data-id")).toBe(
      doc.profiles[doc.profiles.length - 1].id,
    );
  });

  it("marks highlight_open paths with attention and auto_closed paths as closed", () => {
    const { doc } = renderA1();
    const expectedOpen = doc.profiles.reduce(
      (n, p) => n + p.highlight_open.length,
      0,
    );
    const expectedClosed = doc.profiles.reduce(
      (n, p) => n + p.auto_closed.length,
      0,
    );
    // the sample document exercises both branches
    expect(expectedOpen).toBeGreaterThanOrEqual(1);
    expect(expectedClosed).toBeGreaterThanOrEqual(1);

    expect(screen.getAllByTestId("a1-open-marker")).toHaveLength(expectedOpen);
    expect(screen.getAllByTestId("a1-closed-marker")).toHaveLength(
      expectedClosed,
    );
    // open paths are drawn in the distinct dashed/attention style
    expect(screen.getAllByTestId("a1-path-open")).toHaveLength(expectedOpen);
  });

  it("shows one legend row per layer with op + power/passes", () => {
    const { doc } = renderA1();
    const rows = screen.getAllByTestId("a1-layer");
    expect(rows).toHaveLength(doc.layers.length);

    for (const layer of doc.layers) {
      const row = rows.find((r) => r.getAttribute("data-op") === layer.op);
      expect(row).toBeTruthy();
      expect(row?.textContent).toContain(layer.op);
      expect(row?.textContent).toContain(String(layer.settings.power_pct));
      expect(row?.textContent).toContain(String(layer.settings.passes));
    }
  });

  it("confirm buttons transition to a visible confirmed state", async () => {
    const user = userEvent.setup();
    render(<A1Overlay doc={makeSampleA1()} />);

    // UNCONFIRMED: both confirmations pending
    const proposal = screen.getByTestId("confirm-proposal") as HTMLButtonElement;
    expect(proposal.textContent).toBe("Conferma proposta");
    expect(proposal.getAttribute("aria-pressed")).toBe("false");
    expect(proposal.disabled).toBe(false);
    expect(screen.getByTestId("proposal-state").textContent).toContain(
      "non confermata",
    );

    const dims = screen.getByTestId("confirm-dims") as HTMLButtonElement;
    expect(dims.textContent).toBe("Conferma dimensioni");
    expect(dims.getAttribute("aria-pressed")).toBe("false");
    expect(dims.disabled).toBe(false);
    expect(screen.getByTestId("dims-state").textContent).toContain(
      "non confermate",
    );

    // CONFIRM the proposal: text, aria and the section's accent all change
    await user.click(proposal);
    const proposalAfter = screen.getByTestId("confirm-proposal") as HTMLButtonElement;
    expect(proposalAfter.textContent).toContain("Proposta confermata");
    expect(proposalAfter.getAttribute("aria-pressed")).toBe("true");
    expect(proposalAfter.disabled).toBe(true);
    expect(screen.getByTestId("proposal-state").textContent).toContain(
      "confermata",
    );
    expect(screen.getByTestId("a1-confirm").className).toContain("a1-confirmed");

    // the dimensions confirmation is independent and transitions too
    const dimsAfter = screen.getByTestId("confirm-dims") as HTMLButtonElement;
    expect(dimsAfter.textContent).toBe("Conferma dimensioni");
    expect(dimsAfter.disabled).toBe(false);
    await user.click(dimsAfter);
    expect(screen.getByTestId("confirm-dims").textContent).toContain(
      "confermate",
    );
    expect(screen.getByTestId("dims-state").textContent).toContain(
      "confermate",
    );
  });

  it("import door workbench shows the overlay (integration)", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: "Importa" }));

    const overlay = await screen.findByTestId("a1-overlay");
    expect(overlay).toBeTruthy();
    expect(screen.getByTestId("a1-legend")).toBeTruthy();
    expect(screen.getByTestId("confirm-proposal")).toBeTruthy();
    // the four-door workbench itself is intact underneath
    expect(screen.getByTestId("canvas")).toBeTruthy();
    expect(screen.getByTestId("chat-log")).toBeTruthy();
    expect(screen.getByTestId("properties-panel")).toBeTruthy();
  });

  it("other doors do NOT show the A1 overlay", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: "Prova materiale" }));

    expect(await screen.findByTestId("workbench")).toBeTruthy();
    expect(screen.queryByTestId("a1-overlay")).toBeNull();
  });
});
