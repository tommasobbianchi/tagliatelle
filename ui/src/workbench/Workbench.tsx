import type { Mode } from "../doors/config";
import { findDoor } from "../doors/config";
import type { JobSpec } from "../spec";
import Canvas from "./Canvas";
import Chat, { type ChatMessage } from "./Chat";
import Properties from "./Properties";
import { useState } from "react";

export type PreviewLevel = "fast" | "accurate";

export interface WorkbenchProps {
  mode: Mode;
  /** The one shared document: the same spec object for every door. */
  spec: JobSpec;
  onBack: () => void;
}

/**
 * The single workbench (UX decision §15/§20): canvas centre with camera
 * overlay later, chat at the right, properties at the left. Layout fixed on
 * computer, collapsible on tablet (panels fold away with the toggle).
 */
export default function Workbench({ mode, spec, onBack }: WorkbenchProps) {
  const door = findDoor(mode);
  const [preview, setPreview] = useState<PreviewLevel>("fast");
  const [selectedId, setSelectedId] = useState<string | null>(() =>
    door.preselectId(spec),
  );
  const [chatOpen, setChatOpen] = useState(true);
  const [messages, setMessages] = useState<ChatMessage[]>([
    { role: "assistant", text: door.intro },
  ]);

  const appendMessage = (message: ChatMessage) =>
    setMessages((prev) => [...prev, message]);

  return (
    <div className="workbench" data-testid="workbench" data-mode={mode}>
      <header className="workbench-bar">
        <button type="button" onClick={onBack} data-testid="back">
          &larr; porte
        </button>
        <span className="workbench-label">{door.title}</span>
        <div className="preview-toggle" role="group" aria-label="anteprima">
          <button
            type="button"
            onClick={() => setPreview("fast")}
            aria-pressed={preview === "fast"}
          >
            Anteprima veloce
          </button>
          <button
            type="button"
            onClick={() => setPreview("accurate")}
            aria-pressed={preview === "accurate"}
          >
            Anteprima accurata
          </button>
        </div>
        <button
          type="button"
          onClick={() => setChatOpen((open) => !open)}
          aria-pressed={chatOpen}
          data-testid="chat-toggle"
        >
          Chat
        </button>
      </header>

      {preview === "accurate" && (
        <p className="preview-note" role="status" data-testid="preview-note">
          Anteprima accurata = replay delle traiettorie del G-code compilato
          (ordine, viaggi a vuoto, tempi per operazione). Qui è un
          segnaposto: il replay viene dal core (core/replay.py, lane L2) via
          API quando sarà agganciato.
        </p>
      )}

      <aside className="properties-panel" data-testid="properties">
        <Properties spec={spec} selectedId={selectedId} onSelect={setSelectedId} />
      </aside>

      <main className="canvas-panel" data-testid="canvas-panel">
        <Canvas spec={spec} selectedId={selectedId} preview={preview} />
      </main>

      {chatOpen && (
        <aside className="chat-panel" data-testid="chat">
          <Chat messages={messages} onAppend={appendMessage} />
        </aside>
      )}
    </div>
  );
}
