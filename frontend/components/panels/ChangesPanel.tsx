"use client";
import { useEffect, useState } from "react";
import { api, type NarrativeChange } from "@/lib/api";
import { AlertTriangle, CheckCircle, TrendingUp, Zap } from "lucide-react";

const CHANGE_ICON: Record<string, React.ReactNode> = {
  new_event: <Zap size={12} style={{ color: "var(--yellow)" }} />,
  escalation: <TrendingUp size={12} style={{ color: "var(--red)" }} />,
  confirmed: <CheckCircle size={12} style={{ color: "var(--green)" }} />,
  state_change: <AlertTriangle size={12} style={{ color: "var(--orange)" }} />,
};

const CHANGE_COLOR: Record<string, string> = {
  new_event: "var(--yellow)",
  escalation: "var(--red)",
  confirmed: "var(--green)",
  state_change: "var(--orange)",
};

export default function ChangesPanel({
  topicName,
  liveChanges,
}: {
  topicName: string;
  liveChanges: NarrativeChange[];
}) {
  const [stored, setStored] = useState<NarrativeChange[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.pipeline.changes(topicName).then(setStored).finally(() => setLoading(false));
  }, [topicName]);

  async function markDelivered() {
    await api.pipeline.markDelivered(topicName);
    setStored((prev) => prev.map((c) => ({ ...c, delivered: true })));
  }

  // Merge live + stored, deduplicate by id
  const allChanges = [
    ...liveChanges,
    ...stored.filter((s) => !liveChanges.find((l) => l.id === s.id)),
  ].sort((a, b) => new Date(b.detected_at).getTime() - new Date(a.detected_at).getTime());

  const unread = allChanges.filter((c) => !c.delivered).length;

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-2 border-b shrink-0" style={{ borderColor: "var(--border)", background: "var(--panel)" }}>
        <div className="flex items-center gap-3">
          <span style={{ color: "var(--orange)", fontSize: 11, letterSpacing: "0.1em" }}>NARRATIVE SHIFTS</span>
          {unread > 0 && (
            <span className="px-2 py-0" style={{ background: "var(--orange)", color: "#000", fontSize: 10, fontWeight: 700 }}>
              {unread} NEW
            </span>
          )}
        </div>
        {unread > 0 && (
          <button
            onClick={markDelivered}
            className="text-xs px-3 py-1 border"
            style={{ borderColor: "var(--border-bright)", color: "var(--text-dim)", background: "transparent", cursor: "pointer" }}
          >
            MARK ALL READ
          </button>
        )}
      </div>

      {/* Changes list */}
      <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-2">
        {loading ? (
          <div style={{ color: "var(--text-dim)", fontSize: 11, letterSpacing: "0.15em" }}>
            LOADING<span className="cursor-blink">_</span>
          </div>
        ) : allChanges.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-48 gap-3">
            <div style={{ color: "var(--text-dim)", fontSize: 11, letterSpacing: "0.15em" }}>NO NARRATIVE CHANGES DETECTED</div>
            <div style={{ color: "var(--text-dim)", fontSize: 10 }}>Changes appear here when the story evolves significantly</div>
          </div>
        ) : (
          allChanges.map((ch) => (
            <div
              key={ch.id}
              className="border px-4 py-3"
              style={{
                borderColor: ch.delivered ? "var(--border)" : CHANGE_COLOR[ch.change_type] ?? "var(--border)",
                background: ch.delivered ? "var(--panel)" : "var(--panel-hover)",
                borderLeft: `3px solid ${CHANGE_COLOR[ch.change_type] ?? "var(--border)"}`,
              }}
            >
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center gap-2">
                  {CHANGE_ICON[ch.change_type]}
                  <span style={{ fontSize: 10, letterSpacing: "0.1em", color: CHANGE_COLOR[ch.change_type] ?? "var(--text-dim)", fontWeight: 700 }}>
                    {ch.change_type.replace("_", " ").toUpperCase()}
                  </span>
                  {!ch.delivered && (
                    <span style={{ fontSize: 9, padding: "0 4px", background: "var(--orange)", color: "#000" }}>NEW</span>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <span style={{ fontSize: 10, color: "var(--red)", fontWeight: 700 }}>
                    SIG: {(ch.significance * 100).toFixed(0)}%
                  </span>
                  <span style={{ fontSize: 10, color: "var(--text-dim)" }}>
                    {new Date(ch.detected_at).toLocaleString()}
                  </span>
                </div>
              </div>
              <div style={{ color: "var(--text-bright)", fontSize: 13, fontWeight: 600, marginBottom: 4 }}>{ch.headline}</div>
              <div style={{ color: "var(--text)", fontSize: 12, lineHeight: 1.6 }}>{ch.description}</div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
