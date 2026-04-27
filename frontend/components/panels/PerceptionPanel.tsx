"use client";
import { useState } from "react";
import { api, type RegionalPerception } from "@/lib/api";
import { Globe, RefreshCw } from "lucide-react";

const SENTIMENT_COLOR: Record<string, string> = {
  positive: "var(--green)",
  negative: "var(--red)",
  neutral: "var(--text-dim)",
  mixed: "var(--yellow)",
};

function BarMeter({ value }: { value: number }) {
  const pct = Math.round(Math.abs(value) * 100);
  const color = value > 0 ? "var(--green)" : value < 0 ? "var(--red)" : "var(--text-dim)";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1" style={{ background: "var(--border)" }}>
        <div style={{ width: `${pct}%`, height: "100%", background: color }} />
      </div>
      <span style={{ fontSize: 10, color, width: 38, textAlign: "right", fontWeight: 700 }}>
        {value > 0 ? "+" : ""}{value.toFixed(2)}
      </span>
    </div>
  );
}

export default function PerceptionPanel({ topicName }: { topicName: string }) {
  const [data, setData] = useState<{ total_posts: number; regions: RegionalPerception[] } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<RegionalPerception | null>(null);

  async function fetchPerception() {
    setLoading(true);
    setError("");
    try {
      const res = await api.perception.get(topicName);
      setData(res);
      if (res.regions.length > 0) setSelected(res.regions[0]);
    } catch (e: any) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  if (!data && !loading) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-4" style={{ background: "var(--bg)" }}>
        <Globe size={32} style={{ color: "var(--text-dim)" }} />
        <div style={{ color: "var(--text-dim)", fontSize: 11, letterSpacing: "0.1em" }}>GLOBAL PERCEPTION ANALYSIS</div>
        <div style={{ color: "var(--text-dim)", fontSize: 10, maxWidth: 300, textAlign: "center", lineHeight: 1.7 }}>
          Fetches live social media posts from 13 world regions and analyses regional sentiment toward this topic.
        </div>
        {error && <div style={{ color: "var(--red)", fontSize: 11 }}>{error}</div>}
        <button
          onClick={fetchPerception}
          className="flex items-center gap-2 px-4 py-2 text-xs border"
          style={{ borderColor: "var(--orange)", color: "var(--orange)", background: "transparent", cursor: "pointer", letterSpacing: "0.1em" }}
        >
          <Globe size={12} /> ANALYSE PERCEPTION
        </button>
      </div>
    );
  }

  if (loading) {
    return (
      <div className="h-full flex flex-col items-center justify-center gap-3" style={{ background: "var(--bg)" }}>
        <Globe size={24} style={{ color: "var(--orange)" }} className="pulse-orange" />
        <div style={{ color: "var(--text-dim)", fontSize: 11, letterSpacing: "0.15em" }}>
          SCANNING GLOBAL SOCIAL MEDIA<span className="cursor-blink">_</span>
        </div>
        <div style={{ color: "var(--text-dim)", fontSize: 10 }}>This may take 15–30 seconds</div>
      </div>
    );
  }

  const sorted = [...(data?.regions ?? [])].sort((a, b) => b.post_count - a.post_count);

  return (
    <div className="h-full flex overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Left — region list */}
      <div className="flex flex-col border-r overflow-y-auto" style={{ width: 260, borderColor: "var(--border)", background: "var(--panel)", flexShrink: 0 }}>
        <div className="flex items-center justify-between px-3 py-2 border-b" style={{ borderColor: "var(--border)" }}>
          <span style={{ color: "var(--text-dim)", fontSize: 10, letterSpacing: "0.1em" }}>
            {data?.total_posts} POSTS · {sorted.length} REGIONS
          </span>
          <button onClick={fetchPerception} style={{ background: "none", border: "none", color: "var(--text-dim)", cursor: "pointer" }}>
            <RefreshCw size={11} />
          </button>
        </div>
        {sorted.map((r) => (
          <div
            key={r.region}
            className="flex items-center justify-between px-3 py-3 border-b cursor-pointer"
            style={{
              borderColor: "var(--border)",
              background: selected?.region === r.region ? "var(--panel-hover)" : "transparent",
              borderLeft: selected?.region === r.region ? "2px solid var(--orange)" : "2px solid transparent",
            }}
            onClick={() => setSelected(r)}
          >
            <div>
              <div style={{ color: selected?.region === r.region ? "var(--text-bright)" : "var(--text)", fontSize: 12, fontWeight: 600 }}>
                {r.region}
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: 10 }}>{r.post_count} posts</div>
            </div>
            <div className="flex flex-col items-end gap-1">
              <span style={{ fontSize: 9, letterSpacing: "0.08em", color: SENTIMENT_COLOR[r.sentiment] ?? "var(--text-dim)" }}>
                {r.sentiment.toUpperCase()}
              </span>
              <BarMeter value={r.sentiment_score} />
            </div>
          </div>
        ))}
      </div>

      {/* Right — region detail */}
      {selected && (
        <div className="flex-1 overflow-y-auto p-6">
          <div className="flex items-center justify-between mb-4">
            <div>
              <div style={{ color: "var(--orange)", fontWeight: 700, fontSize: 14, letterSpacing: "0.1em" }}>{selected.region.toUpperCase()}</div>
              <div style={{ color: "var(--text-dim)", fontSize: 10 }}>Analysed: {selected.analysed_at}</div>
            </div>
            <div className="text-right">
              <div style={{ color: SENTIMENT_COLOR[selected.sentiment], fontWeight: 700, fontSize: 16 }}>
                {selected.sentiment_score > 0 ? "+" : ""}{selected.sentiment_score.toFixed(2)}
              </div>
              <div style={{ color: "var(--text-dim)", fontSize: 10 }}>{selected.sentiment.toUpperCase()}</div>
            </div>
          </div>

          <Section label="DOMINANT NARRATIVE">
            <p style={{ color: "var(--text)", fontSize: 12, lineHeight: 1.7 }}>{selected.dominant_narrative}</p>
          </Section>

          <Section label="KEY THEMES">
            <div className="flex flex-wrap gap-2">
              {selected.key_themes.map((t) => (
                <span key={t} className="px-2 py-1 border text-xs" style={{ borderColor: "var(--border-bright)", color: "var(--text)" }}>{t}</span>
              ))}
            </div>
          </Section>

          <Section label={`PLATFORM BREAKDOWN (${selected.post_count} posts)`}>
            <div className="flex flex-col gap-2">
              {Object.entries(selected.platform_breakdown).map(([platform, count]) => (
                <div key={platform} className="flex items-center gap-3">
                  <span style={{ width: 80, color: "var(--text-dim)", fontSize: 11 }}>{platform}</span>
                  <div className="flex-1 h-1" style={{ background: "var(--border)" }}>
                    <div style={{ width: `${(count / selected.post_count) * 100}%`, height: "100%", background: "var(--orange)" }} />
                  </div>
                  <span style={{ color: "var(--text)", fontSize: 11, width: 30, textAlign: "right" }}>{count}</span>
                </div>
              ))}
            </div>
          </Section>

          {selected.sample_quotes.length > 0 && (
            <Section label="SAMPLE POSTS">
              {selected.sample_quotes.map((q, i) => (
                <div key={i} className="px-3 py-2 border-l mb-2" style={{ borderColor: "var(--orange)", background: "var(--panel)", fontSize: 11, color: "var(--text)", lineHeight: 1.6 }}>
                  "{q}"
                </div>
              ))}
            </Section>
          )}
        </div>
      )}
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-5">
      <div style={{ color: "var(--text-dim)", fontSize: 10, letterSpacing: "0.1em", marginBottom: 8, borderBottom: "1px solid var(--border)", paddingBottom: 4 }}>
        {label}
      </div>
      {children}
    </div>
  );
}
