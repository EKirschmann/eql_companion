"use client";

import { FormEvent, Fragment, memo, useEffect, useRef, useState } from "react";
import { apiGet, apiSend } from "@/lib/api";
import type { ChatMessage, Suggestions, SuggestionItem } from "@/lib/types";

/** Minimal markdown: **bold** and line breaks — no HTML injection. */
function renderContent(text: string) {
  return text.split("\n").map((line, li) => (
    <Fragment key={li}>
      {li > 0 && <br />}
      {line.split(/(\*\*[^*]+\*\*)/g).map((part, pi) =>
        part.startsWith("**") && part.endsWith("**") ? (
          <strong key={pi}>{part.slice(2, -2)}</strong>
        ) : (
          <Fragment key={pi}>{part}</Fragment>
        ),
      )}
    </Fragment>
  ));
}

function SuggestionGroup({ title, items }: { title: string; items: SuggestionItem[] }) {
  if (!items?.length) return null;
  return (
    <div className="suggestion-group">
      <h4>{title}</h4>
      {items.slice(0, 5).map((s, i) => (
        <div key={i} className="suggestion-item">
          <span className="suggestion-pri">P{s.priority}</span>
          <span className="suggestion-name">{s.name}</span>
          <span className="suggestion-reason">{s.reason}</span>
        </div>
      ))}
    </div>
  );
}

export const CompanionPanel = memo(function CompanionPanel() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    apiGet<{ messages: ChatMessage[] }>("/api/chat/history")
      .then((r) => setMessages(r.messages))
      .catch(() => {});
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, busy]);

  const send = async (e: FormEvent) => {
    e.preventDefault();
    const question = input.trim();
    if (!question || busy) return;
    setInput("");
    setError(null);
    setMessages((m) => [...m, { role: "user", content: question }]);
    setBusy(true);
    try {
      const res = await apiSend<{ response: string; suggestions: Suggestions }>(
        "/api/chat",
        { message: question },
      );
      setMessages((m) => [
        ...m,
        { role: "assistant", content: res.response, suggestions: res.suggestions },
      ]);
    } catch (err) {
      setError(
        "The companion is unreachable — check that the backend is running on port 8000.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel chat-panel">
      <div className="panel-title">Companion</div>
      <div className="chat-scroll" ref={scrollRef}>
        {messages.length === 0 && !busy && (
          <p className="chat-empty">
            Ask about spells to learn, AAs to train, or where to hunt next. The
            companion reads your live log for context.
          </p>
        )}
        {messages.map((m, i) => (
          <div key={i} className="chat-msg" data-role={m.role}>
            {m.role === "assistant" ? renderContent(m.content) : m.content}
            {m.suggestions && (
              <>
                <SuggestionGroup title="Spells" items={m.suggestions.spells} />
                <SuggestionGroup title="Alternative Advancements" items={m.suggestions.aas} />
                <SuggestionGroup title="Hunting grounds" items={m.suggestions.zones} />
              </>
            )}
          </div>
        ))}
        {busy && <p className="chat-status">The companion consults the archives…</p>}
        {error && <p className="chat-error">{error}</p>}
      </div>
      <form className="chat-input-row" onSubmit={send}>
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask the companion…"
          aria-label="Ask the companion"
          disabled={busy}
        />
        <button type="submit" disabled={busy || !input.trim()}>
          Send
        </button>
      </form>
    </section>
  );
});
