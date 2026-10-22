import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Workbench from "../workbench/Workbench";
import { makeSampleSpec } from "../spec";

function renderChat() {
  render(
    <Workbench mode="material-test" spec={makeSampleSpec()} onBack={() => {}} />,
  );
}

describe("chat", () => {
  it("shows the door intro message first", () => {
    renderChat();
    const log = screen.getByTestId("chat-log");
    expect(log.textContent).toContain("griglia deterministica");
    expect(screen.getAllByTestId(/^chat-message-/)).toHaveLength(1);
  });

  it("accepts input and appends it to the message list", async () => {
    const user = userEvent.setup();
    renderChat();
    const input = screen.getByTestId("chat-input") as HTMLInputElement;

    await user.type(input, "griglia piu' fitta{Enter}");

    expect(screen.getByTestId("chat-log").textContent).toContain(
      "griglia piu' fitta",
    );
    // empty input clears for the next message
    expect(input.value).toBe("");
    // the append is preserved on follow-up messages
    await user.type(input, "secondo messaggio{Enter}");
    expect(screen.getByTestId("chat-log").textContent).toContain(
      "secondo messaggio",
    );
    expect(screen.getAllByTestId(/^chat-message-/)).toHaveLength(3);
  });

  it("appends nothing for empty input", async () => {
    const user = userEvent.setup();
    renderChat();
    const input = screen.getByTestId("chat-input") as HTMLInputElement;
    await user.type(input, "   ");
    await user.click(screen.getByTestId("chat-send"));
    expect(screen.getAllByTestId(/^chat-message-/)).toHaveLength(1);
    expect(input.value).toBe("   ");
  });

  it("the chat panel can be folded away (collapsible on tablet)", async () => {
    const user = userEvent.setup();
    renderChat();
    expect(screen.getByTestId("chat")).toBeTruthy();
    await user.click(screen.getByTestId("chat-toggle"));
    expect(screen.queryByTestId("chat")).toBeNull();
    await user.click(screen.getByTestId("chat-toggle"));
    expect(screen.getByTestId("chat")).toBeTruthy();
  });
});
