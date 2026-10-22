import { useState } from "react";

export interface ChatMessage {
  role: "user" | "assistant";
  text: string;
}

export interface ChatProps {
  messages: ChatMessage[];
  onAppend: (message: ChatMessage) => void;
}

/**
 * LLM chat: message list + input. No backend yet (API wiring is later);
 * the skeleton only appends the user's message deterministically.
 */
export default function Chat({ messages, onAppend }: ChatProps) {
  const [draft, setDraft] = useState("");

  const submit = () => {
    const text = draft.trim();
    if (!text) return;
    onAppend({ role: "user", text });
    setDraft("");
  };

  return (
    <div className="chat">
      <h3>Chat</h3>
      <ul className="chat-log" data-testid="chat-log">
        {messages.map((m, i) => (
          <li key={i} data-testid={`chat-message-${i}`} className={`msg-${m.role}`}>
            <b>{m.role}</b> {m.text}
          </li>
        ))}
      </ul>
      <form
        className="chat-form"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <label className="visually-hidden" htmlFor="chat-input">
          Messaggio per l'LLM
        </label>
        <input
          id="chat-input"
          data-testid="chat-input"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder="Scrivi all'LLM (es. «griglia più fitta»)"
        />
        <button type="submit" data-testid="chat-send">
          Invia
        </button>
      </form>
    </div>
  );
}
