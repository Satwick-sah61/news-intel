"use client";
import { useEffect, useState } from "react";
import { api, type Article } from "@/lib/api";
import { ExternalLink, ChevronLeft, ChevronRight } from "lucide-react";

const SENT_COLOR: Record<string, string> = {
  positive: "var(--green)",
  negative: "var(--red)",
  neutral: "var(--text-dim)",
  mixed: "var(--yellow)",
};

const TIER_COLOR = ["", "var(--orange)", "var(--yellow)", "var(--text-dim)"];

export default function ArticlesPanel({ topicName }: { topicName: string }) {
  const [data, setData] = useState<{ total: number; items: Article[] } | null>(null);
  const [page, setPage] = useState(1);
  const [sentiment, setSentiment] = useState("");
  const [minRel, setMinRel] = useState(0);
  const [loading, setLoading] = useState(true);
  const [expanded, setExpanded] = useState<number | null>(null);
  const LIMIT = 25;

  const load = () => {
    setLoading(true);
    api.articles.list(topicName, page, LIMIT, sentiment || undefined, minRel || undefined)
      .then(setData)
      .finally(() => setLoading(false));
  };

  useEffect(() => { setPage(1); }, [sentiment, minRel]);
  useEffect(() => { load(); }, [topicName, page, sentiment, minRel]);

  const totalPages = data ? Math.ceil(data.total / LIMIT) : 1;

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Filters */}
      <div className="flex items-center gap-4 px-4 py-2 border-b shrink-0" style={{ borderColor: "var(--border)", background: "var(--panel)" }}>
        <span style={{ color: "var(--text-dim)", fontSize: 10, letterSpacing: "0.1em" }}>FILTER:</span>
        <select
          value={sentiment}
          onChange={(e) => setSentiment(e.target.value)}
          style={{ background: "var(--bg)", border: "1px solid var(--border-bright)", color: "var(--text)", fontSize: 11, padding: "2px 6px", fontFamily: "inherit" }}
        >
          <option value="">ALL SENTIMENT</option>
          <option value="positive">POSITIVE</option>
          <option value="negative">NEGATIVE</option>
          <option value="neutral">NEUTRAL</option>
        </select>
        <select
          value={minRel}
          onChange={(e) => setMinRel(Number(e.target.value))}
          style={{ background: "var(--bg)", border: "1px solid var(--border-bright)", color: "var(--text)", fontSize: 11, padding: "2px 6px", fontFamily: "inherit" }}
        >
          <option value={0}>MIN RELEVANCE: ANY</option>
          <option value={0.5}>MIN RELEVANCE: 0.5+</option>
          <option value={0.7}>MIN RELEVANCE: 0.7+</option>
          <option value={0.9}>MIN RELEVANCE: 0.9+</option>
        </select>
        {data && (
          <span style={{ color: "var(--text-dim)", fontSize: 10, marginLeft: "auto" }}>
            {data.total} ARTICLES
          </span>
        )}
      </div>

      {/* Column headers */}
      <div className="flex items-center gap-2 px-4 py-1 border-b shrink-0 text-xs" style={{ borderColor: "var(--border)", color: "var(--text-dim)", letterSpacing: "0.1em", background: "var(--panel)" }}>
        <span style={{ width: 30 }}>TIER</span>
        <span style={{ width: 110 }}>SOURCE</span>
        <span style={{ width: 60 }}>REGION</span>
        <span className="flex-1">TITLE</span>
        <span style={{ width: 70, textAlign: "right" }}>RELEVANCE</span>
        <span style={{ width: 80 }}>SENTIMENT</span>
        <span style={{ width: 90 }}>DATE</span>
      </div>

      {/* Rows */}
      <div className="flex-1 overflow-y-auto">
        {loading ? (
          <div className="flex items-center justify-center h-32">
            <span style={{ color: "var(--text-dim)", fontSize: 11, letterSpacing: "0.15em" }}>LOADING<span className="cursor-blink">_</span></span>
          </div>
        ) : (
          data?.items.map((a) => (
            <div key={a.id}>
              <div
                className="flex items-center gap-2 px-4 py-2 border-b cursor-pointer"
                style={{
                  borderColor: "var(--border)",
                  background: expanded === a.id ? "var(--panel-hover)" : "transparent",
                }}
                onClick={() => setExpanded(expanded === a.id ? null : a.id)}
              >
                <span style={{ width: 30, fontSize: 10, fontWeight: 700, color: TIER_COLOR[a.source_tier] ?? "var(--text-dim)" }}>
                  T{a.source_tier}
                </span>
                <span style={{ width: 110, fontSize: 10, color: "var(--text-dim)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {a.source}
                </span>
                <span style={{ width: 60, fontSize: 10, color: "var(--text-dim)" }}>{a.region ?? "—"}</span>
                <span className="flex-1 text-xs" style={{ color: "var(--text-bright)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {a.title}
                </span>
                <span style={{ width: 70, textAlign: "right", fontSize: 11, color: scoreColor(a.relevance_score), fontWeight: 700 }}>
                  {(a.relevance_score * 100).toFixed(0)}%
                </span>
                <span style={{ width: 80, fontSize: 10, color: SENT_COLOR[a.sentiment] ?? "var(--text-dim)" }}>
                  {a.sentiment.toUpperCase()}
                </span>
                <span style={{ width: 90, fontSize: 10, color: "var(--text-dim)" }}>
                  {a.published_at ? a.published_at.slice(0, 10) : "—"}
                </span>
              </div>

              {expanded === a.id && (
                <div className="px-6 py-3 border-b" style={{ borderColor: "var(--border)", background: "var(--panel)" }}>
                  <p style={{ color: "var(--text)", fontSize: 12, lineHeight: 1.7, marginBottom: 10 }}>{a.summary}</p>
                  {a.key_claims.length > 0 && (
                    <div className="mb-3">
                      <div style={{ color: "var(--text-dim)", fontSize: 10, letterSpacing: "0.1em", marginBottom: 4 }}>KEY CLAIMS</div>
                      {a.key_claims.map((c, i) => (
                        <div key={i} className="flex gap-2 mb-1">
                          <span style={{ color: "var(--orange)" }}>›</span>
                          <span style={{ color: "var(--text)", fontSize: 11 }}>{c}</span>
                        </div>
                      ))}
                    </div>
                  )}
                  <div className="flex gap-4 mb-3">
                    {a.entities_people.length > 0 && <Chips label="PEOPLE" items={a.entities_people} />}
                    {a.entities_locations.length > 0 && <Chips label="LOCATIONS" items={a.entities_locations} />}
                    {a.entities_orgs.length > 0 && <Chips label="ORGS" items={a.entities_orgs} />}
                  </div>
                  <a href={a.url} target="_blank" rel="noopener noreferrer" className="flex items-center gap-1 no-underline" style={{ color: "var(--blue)", fontSize: 11 }}>
                    <ExternalLink size={11} /> Open source
                  </a>
                </div>
              )}
            </div>
          ))
        )}
      </div>

      {/* Pagination */}
      <div className="flex items-center justify-between px-4 py-2 border-t shrink-0" style={{ borderColor: "var(--border)", background: "var(--panel)" }}>
        <button
          onClick={() => setPage((p) => Math.max(1, p - 1))}
          disabled={page === 1}
          className="flex items-center gap-1 px-3 py-1 border text-xs"
          style={{ borderColor: page === 1 ? "var(--border)" : "var(--border-bright)", color: page === 1 ? "var(--text-dim)" : "var(--text)", background: "transparent", cursor: page === 1 ? "not-allowed" : "pointer" }}
        >
          <ChevronLeft size={11} /> PREV
        </button>
        <span style={{ color: "var(--text-dim)", fontSize: 10 }}>
          PAGE {page} / {totalPages}
        </span>
        <button
          onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
          disabled={page >= totalPages}
          className="flex items-center gap-1 px-3 py-1 border text-xs"
          style={{ borderColor: page >= totalPages ? "var(--border)" : "var(--border-bright)", color: page >= totalPages ? "var(--text-dim)" : "var(--text)", background: "transparent", cursor: page >= totalPages ? "not-allowed" : "pointer" }}
        >
          NEXT <ChevronRight size={11} />
        </button>
      </div>
    </div>
  );
}

function Chips({ label, items }: { label: string; items: string[] }) {
  return (
    <div>
      <div style={{ color: "var(--text-dim)", fontSize: 10, letterSpacing: "0.1em", marginBottom: 3 }}>{label}</div>
      <div className="flex flex-wrap gap-1">
        {items.slice(0, 5).map((it) => (
          <span key={it} className="px-2 py-0 border" style={{ borderColor: "var(--border-bright)", color: "var(--text-dim)", fontSize: 10 }}>
            {it}
          </span>
        ))}
      </div>
    </div>
  );
}

function scoreColor(s: number) {
  if (s >= 0.8) return "var(--green)";
  if (s >= 0.5) return "var(--yellow)";
  return "var(--text-dim)";
}
