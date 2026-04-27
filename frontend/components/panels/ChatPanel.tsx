"use client";
import { useEffect, useRef, useState } from "react";
import { api, type ChatMessage } from "@/lib/api";
import { Send, Trash2, Terminal } from "lucide-react";

export default function ChatPanel({ topicName }: { topicName: string }) {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [loading, setLoading] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.chat.history(topicName).then(setMessages).finally(() => setLoading(false));
  }, [topicName]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function send() {
    const msg = input.trim();
    if (!msg || sending) return;
    setInput("");
    setSending(true);

    // Optimistic user message
    const tempId = Date.now();
    setMessages((prev) => [...prev, { id: tempId, role: "user", content: msg, created_at: new Date().toISOString() }]);

    try {
      const res = await api.chat.send(topicName, msg);
      setMessages((prev) => [...prev, { id: tempId + 1, role: "assistant", content: res.reply, created_at: new Date().toISOString() }]);
    } catch (e: any) {
      setMessages((prev) => [...prev, { id: tempId + 1, role: "assistant", content: `ERROR: ${e.message}`, created_at: new Date().toISOString() }]);
    } finally {
      setSending(false);
    }
  }

  async function clearHistory() {
    if (!confirm("Clear all chat history?")) return;
    await api.chat.clear(topicName);
    setMessages([]);
  }

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b shrink-0" style={{ borderColor: "var(--border)", background: "var(--panel)" }}>
        <div className="flex items-center gap-2">
          <Terminal size={12} style={{ color: "var(--orange)" }} />
          <span style={{ color: "var(--orange)", fontSize: 11, letterSpacing: "0.1em" }}>AI ANALYST — {topicName.toUpperCase()}</span>
        </div>
        <button
          onClick={clearHistory}
          className="flex items-center gap-1 text-xs px-2 py-1 border"
          style={{ borderColor: "var(--border-bright)", color: "var(--text-dim)", background: "transparent", cursor: "pointer" }}
        >
          <Trash2 size={10} /> CLEAR
        </button>
      </div>

      {/* System context message */}
      {!loading && messages.length === 0 && (
        <div className="px-6 py-4 border-b" style={{ borderColor: "var(--border)", background: "var(--panel-hover)" }}>
          <div style={{ color: "var(--text-dim)", fontSize: 11, lineHeight: 1.7 }}>
            <span style={{ color: "var(--orange)" }}>SYS › </span>
            Intelligence analyst online. I have access to all scraped articles and timeline events for <strong style={{ color: "var(--text)" }}>{topicName}</strong>. Ask me anything — I answer only from verified data.
          </div>
        </div>
      )}

      {/* Messages */}
      <div className="flex-1 overflow-y-auto px-6 py-4 flex flex-col gap-4">
        {loading && (
          <div style={{ color: "var(--text-dim)", fontSize: 11, letterSpacing: "0.15em" }}>
            LOADING HISTORY<span className="cursor-blink">_</span>
          </div>
        )}
        {messages.map((m) => (
          <MessageBubble key={m.id} msg={m} />
        ))}
        {sending && (
          <div style={{ color: "var(--text-dim)", fontSize: 11 }}>
            <span style={{ color: "var(--orange)" }}>AI › </span>
            <span className="cursor-blink">_</span>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      {/* Input */}
      <div className="flex border-t shrink-0" style={{ borderColor: "var(--border)" }}>
        <span className="flex items-center px-4" style={{ color: "var(--orange)", fontSize: 12, background: "var(--panel)", borderRight: "1px solid var(--border)" }}>›</span>
        <input
          className="flex-1 px-4 py-3 outline-none text-sm"
          style={{ background: "var(--panel)", color: "var(--text-bright)", fontFamily: "inherit", border: "none" }}
          placeholder="Ask about events, sources, timelines, implications..."
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && send()}
          disabled={sending}
        />
        <button
          onClick={send}
          disabled={sending || !input.trim()}
          className="px-4 flex items-center"
          style={{
            background: sending || !input.trim() ? "var(--panel)" : "var(--orange)",
            color: sending || !input.trim() ? "var(--text-dim)" : "#000",
            border: "none",
            borderLeft: "1px solid var(--border)",
            cursor: sending || !input.trim() ? "not-allowed" : "pointer",
          }}
        >
          <Send size={13} />
        </button>
      </div>
    </div>
  );
}

function MessageBubble({ msg }: { msg: ChatMessage }) {
  const isUser = msg.role === "user";
  return (
    <div className={`flex flex-col ${isUser ? "items-end" : "items-start"}`}>
      <div className="flex items-center gap-2 mb-1">
        <span style={{ fontSize: 9, letterSpacing: "0.1em", color: isUser ? "var(--blue)" : "var(--orange)" }}>
          {isUser ? "YOU" : "AI ANALYST"}
        </span>
        <span style={{ fontSize: 9, color: "var(--text-dim)" }}>
          {new Date(msg.created_at).toLocaleTimeString()}
        </span>
      </div>
      <div
        className="px-4 py-3 border max-w-2xl"
        style={{
          borderColor: isUser ? "var(--blue)" : "var(--border-bright)",
          background: isUser ? "rgba(74,158,255,0.05)" : "var(--panel)",
          color: "var(--text)",
          fontSize: 12,
          lineHeight: 1.7,
          whiteSpace: "pre-wrap",
        }}
      >
        {msg.content}
      </div>
    </div>
  );
}
