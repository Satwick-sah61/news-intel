"use client";
import { useEffect, useState } from "react";
import { api, type TimelineEvent, type EventDetail } from "@/lib/api";
import { ChevronDown, ChevronRight, Users, MapPin, Building2, Shield } from "lucide-react";

const SENTIMENT_COLOR: Record<string, string> = {
  positive: "var(--green)",
  negative: "var(--red)",
  neutral: "var(--text-dim)",
  mixed: "var(--yellow)",
};

const STATE_COLOR: Record<string, string> = {
  Breaking: "var(--red)",
  Developing: "var(--yellow)",
  Confirmed: "var(--green)",
  Resolved: "var(--text-dim)",
};

const TYPE_COLOR: Record<string, string> = {
  Military: "var(--red)",
  Diplomatic: "var(--blue)",
  Economic: "var(--yellow)",
  Political: "var(--orange)",
  Social: "var(--green)",
};

export default function TimelinePanel({ topicName, refreshSignal }: { topicName: string; refreshSignal?: number }) {
  const [events, setEvents] = useState<TimelineEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [detail, setDetail] = useState<EventDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  useEffect(() => {
    api.timeline.list(topicName).then(setEvents).finally(() => setLoading(false));
  }, [topicName, refreshSignal]);

  async function toggleEvent(eventId: string) {
    if (expanded === eventId) { setExpanded(null); setDetail(null); return; }
    setExpanded(eventId);
    setDetail(null);
    setDetailLoading(true);
    try {
      const d = await api.timeline.get(topicName, eventId);
      setDetail(d);
    } finally {
      setDetailLoading(false);
    }
  }

  if (loading) return <Loader text="LOADING TIMELINE" />;

  return (
    <div className="h-full overflow-y-auto p-4" style={{ background: "var(--bg)" }}>
      {/* Header row */}
      <div
        className="flex items-center gap-3 px-3 py-2 mb-3 border-b text-xs"
        style={{ borderColor: "var(--border)", color: "var(--text-dim)", letterSpacing: "0.1em" }}
      >
        <span style={{ width: 80 }}>TYPE</span>
        <span style={{ width: 70 }}>STATE</span>
        <span className="flex-1">HEADLINE</span>
        <span style={{ width: 60, textAlign: "right" }}>SCORE</span>
        <span style={{ width: 60, textAlign: "right" }}>SOURCES</span>
        <span style={{ width: 90 }}>DATE</span>
      </div>

      {events.length === 0 && (
        <div style={{ color: "var(--text-dim)", fontSize: 11, padding: 16 }}>NO EVENTS — RUN PIPELINE FIRST</div>
      )}

      {events.map((ev) => (
        <div key={ev.event_id} className="mb-1">
          {/* Row */}
          <div
            className="flex items-center gap-3 px-3 py-2 border cursor-pointer"
            style={{
              borderColor: expanded === ev.event_id ? "var(--orange)" : "var(--border)",
              background: expanded === ev.event_id ? "var(--panel-hover)" : "var(--panel)",
            }}
            onClick={() => toggleEvent(ev.event_id)}
          >
            <span style={{ width: 80, fontSize: 10, letterSpacing: "0.05em", color: TYPE_COLOR[ev.event_type] ?? "var(--text-dim)" }}>
              {ev.event_type.toUpperCase()}
            </span>
            <span style={{ width: 70, fontSize: 10, color: STATE_COLOR[ev.narrative_state] ?? "var(--text-dim)" }}>
              {ev.narrative_state}
            </span>
            <span className="flex-1 text-xs" style={{ color: "var(--text-bright)" }}>
              {ev.headline}
            </span>
            <span style={{ width: 60, textAlign: "right", fontSize: 11, color: scoreColor(ev.significance_score), fontWeight: 700 }}>
              {(ev.significance_score * 100).toFixed(0)}
            </span>
            <span style={{ width: 60, textAlign: "right", fontSize: 11, color: "var(--text-dim)" }}>
              {ev.source_count} <span style={{ fontSize: 9 }}>(T1:{ev.tier1_count})</span>
            </span>
            <span style={{ width: 90, fontSize: 10, color: "var(--text-dim)" }}>
              {ev.first_seen ? ev.first_seen.slice(0, 10) : "—"}
            </span>
            {expanded === ev.event_id ? <ChevronDown size={12} style={{ color: "var(--orange)" }} /> : <ChevronRight size={12} style={{ color: "var(--text-dim)" }} />}
          </div>

          {/* Expanded detail */}
          {expanded === ev.event_id && (
            <div className="border border-t-0 px-4 py-3" style={{ borderColor: "var(--orange)", background: "var(--panel-hover)" }}>
              {detailLoading ? (
                <div style={{ color: "var(--text-dim)", fontSize: 11 }}>LOADING SOURCES...</div>
              ) : (
                <div className="flex gap-6">
                  {/* Left */}
                  <div className="flex-1">
                    <div style={{ color: "var(--text-dim)", fontSize: 10, letterSpacing: "0.1em", marginBottom: 6 }}>SUMMARY</div>
                    <p style={{ color: "var(--text)", fontSize: 12, lineHeight: 1.6, marginBottom: 12 }}>{ev.summary}</p>
                    <div className="flex gap-4">
                      <EntityList icon={<MapPin size={10} />} label="LOCATIONS" items={ev.locations} />
                      <EntityList icon={<Users size={10} />} label="PEOPLE" items={ev.people} />
                      <EntityList icon={<Building2 size={10} />} label="ORGS" items={ev.organizations} />
                    </div>
                  </div>
                  {/* Right — sources */}
                  <div style={{ width: 280 }}>
                    <div style={{ color: "var(--text-dim)", fontSize: 10, letterSpacing: "0.1em", marginBottom: 6 }}>
                      SOURCES ({detail?.sources.length ?? 0})
                    </div>
                    <div className="flex flex-col gap-1">
                      {detail?.sources.slice(0, 6).map((s, i) => (
                        <a
                          key={i}
                          href={s.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="flex items-center justify-between px-2 py-1 border no-underline"
                          style={{ borderColor: "var(--border)", background: "var(--bg)" }}
                        >
                          <div>
                            <div style={{ color: "var(--text)", fontSize: 11 }}>{s.source}</div>
                            <div style={{ color: "var(--text-dim)", fontSize: 10 }}>T{s.source_tier} · {s.region ?? "—"}</div>
                          </div>
                          <span style={{ fontSize: 9, color: SENTIMENT_COLOR[s.sentiment] ?? "var(--text-dim)" }}>
                            {s.sentiment.toUpperCase()}
                          </span>
                        </a>
                      ))}
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function EntityList({ icon, label, items }: { icon: React.ReactNode; label: string; items: string[] }) {
  if (!items?.length) return null;
  return (
    <div>
      <div className="flex items-center gap-1 mb-1" style={{ color: "var(--text-dim)", fontSize: 10 }}>
        {icon} {label}
      </div>
      {items.slice(0, 4).map((it) => (
        <div key={it} style={{ color: "var(--text)", fontSize: 11 }}>{it}</div>
      ))}
    </div>
  );
}

function scoreColor(s: number) {
  if (s >= 0.8) return "var(--red)";
  if (s >= 0.5) return "var(--yellow)";
  return "var(--green)";
}

function Loader({ text }: { text: string }) {
  return (
    <div className="h-full flex items-center justify-center">
      <span style={{ color: "var(--text-dim)", fontSize: 12, letterSpacing: "0.15em" }}>
        {text}<span className="cursor-blink">_</span>
      </span>
    </div>
  );
}
