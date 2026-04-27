"use client";
import { useEffect, useRef, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  api, type Topic, type NarrativeChange, type LiveStats,
  subscribeToStream,
} from "@/lib/api";
import { ArrowLeft, Play, Radio, Square, Zap, FileText, BarChart2, BellDot } from "lucide-react";
import Link from "next/link";
import TimelinePanel from "@/components/panels/TimelinePanel";
import ArticlesPanel from "@/components/panels/ArticlesPanel";
import ChatPanel from "@/components/panels/ChatPanel";
import PerceptionPanel from "@/components/panels/PerceptionPanel";
import ChangesPanel from "@/components/panels/ChangesPanel";

const TABS = ["TIMELINE", "ARTICLES", "CHAT", "PERCEPTION", "CHANGES"] as const;
type Tab = typeof TABS[number];

export default function TopicPage() {
  const { name } = useParams<{ name: string }>();
  const topicName = decodeURIComponent(name);
  const router = useRouter();

  const [topic, setTopic] = useState<Topic | null>(null);
  const [activeTab, setActiveTab] = useState<Tab>("TIMELINE");
  const [running, setRunning] = useState(false);
  const [monitoring, setMonitoring] = useState(false);
  const [togglingMonitor, setTogglingMonitor] = useState(false);
  const [liveChanges, setLiveChanges] = useState<NarrativeChange[]>([]);
  const [stats, setStats] = useState<LiveStats>({ articles: 0, events: 0 });
  const [ticker, setTicker] = useState<string[]>([]);
  const [runMsg, setRunMsg] = useState("");
  const prevArticles = useRef(0);

  useEffect(() => {
    api.topics.get(topicName)
      .then(setTopic)
      .catch(() => router.push("/"));
    api.pipeline.status(topicName).then((s) => setRunning(s.status === "running"));
    api.pipeline.schedule(topicName)
      .then((s) => setMonitoring(s.active))
      .catch(() => {});
  }, [topicName]);

  // SSE stream — always connected so we get live stats + changes
  useEffect(() => {
    const unsub = subscribeToStream(
      topicName,
      (ch) => {
        setLiveChanges((prev) => [ch, ...prev].slice(0, 30));
        addTicker(`[ALERT] ${ch.headline}`);
      },
      (s) => {
        setStats(s);
        if (prevArticles.current > 0 && s.articles > prevArticles.current) {
          const diff = s.articles - prevArticles.current;
          addTicker(`+${diff} new article${diff > 1 ? "s" : ""} ingested`);
        }
        prevArticles.current = s.articles;
      },
    );
    return unsub;
  }, [topicName]);

  function addTicker(msg: string) {
    setTicker((prev) => [`${new Date().toLocaleTimeString()} — ${msg}`, ...prev].slice(0, 8));
  }

  async function runPipeline() {
    setRunning(true);
    setRunMsg("Pipeline queued…");
    try {
      await api.pipeline.run(topicName);
      setRunMsg("Pipeline running in background");
      addTicker("Manual pipeline triggered");
    } catch (e: any) {
      setRunMsg(`Error: ${e.message}`);
    } finally {
      setTimeout(() => { setRunning(false); setRunMsg(""); }, 5000);
    }
  }

  async function toggleMonitoring() {
    setTogglingMonitor(true);
    try {
      const next = !monitoring;
      await api.pipeline.setMonitoring(topicName, next);
      setMonitoring(next);
      addTicker(next ? "Live monitoring STARTED — news flowing" : "Live monitoring PAUSED");
    } catch (e: any) {
      addTicker(`Monitor toggle error: ${(e as any).message}`);
    } finally {
      setTogglingMonitor(false);
    }
  }

  const unreadCount = liveChanges.filter((c) => !c.delivered).length;

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: "var(--bg)" }}>

      {/* ── Topic header ── */}
      <div
        className="flex items-center justify-between px-4 py-2 border-b shrink-0"
        style={{ borderColor: "var(--border)", background: "var(--panel)" }}
      >
        <div className="flex items-center gap-4">
          <Link href="/" style={{ color: "var(--text-dim)" }}><ArrowLeft size={14} /></Link>
          <div>
            <div className="flex items-center gap-3">
              <span style={{ color: "var(--orange)", fontWeight: 700, letterSpacing: "0.15em", fontSize: 12 }}>
                {topicName.toUpperCase()}
              </span>
              {monitoring && (
                <span style={{ fontSize: 9, letterSpacing: "0.1em", padding: "1px 6px", border: "1px solid var(--green)", color: "var(--green)" }}
                  className="pulse-orange">
                  ● LIVE
                </span>
              )}
            </div>
            {topic && (
              <div style={{ color: "var(--text-dim)", fontSize: 10 }}>
                Last scraped: {topic.last_scraped
                  ? new Date(topic.last_scraped + "Z").toLocaleString()
                  : "Never"}
              </div>
            )}
          </div>
        </div>

        {/* ── Controls ── */}
        <div className="flex items-center gap-2">
          {/* Live stats */}
          <div className="flex items-center gap-3 px-3 border-r" style={{ borderColor: "var(--border)" }}>
            <Stat icon={<FileText size={10} />} value={stats.articles} label="ARTS" />
            <Stat icon={<BarChart2 size={10} />} value={stats.events} label="EVTS" />
          </div>

          {/* ── MONITORING TOGGLE ── */}
          <button
            onClick={toggleMonitoring}
            disabled={togglingMonitor}
            className="flex items-center gap-2 px-4 py-1 border text-xs font-bold"
            style={{
              borderColor: monitoring ? "var(--green)" : "var(--text-dim)",
              color: monitoring ? "#000" : "var(--text-dim)",
              background: monitoring ? "var(--green)" : "transparent",
              cursor: togglingMonitor ? "wait" : "pointer",
              letterSpacing: "0.12em",
              transition: "all 0.2s",
            }}
          >
            {monitoring
              ? <><Square size={10} /> STOP FEED</>
              : <><Radio size={10} /> START FEED</>}
          </button>

          {/* Manual run */}
          <button
            onClick={runPipeline}
            disabled={running}
            className="flex items-center gap-2 px-3 py-1 border text-xs"
            style={{
              borderColor: running ? "var(--text-dim)" : "var(--border-bright)",
              color: running ? "var(--text-dim)" : "var(--text)",
              background: "transparent",
              cursor: running ? "not-allowed" : "pointer",
              letterSpacing: "0.1em",
            }}
          >
            <Play size={10} /> {running ? "RUNNING…" : "RUN ONCE"}
          </button>

          {unreadCount > 0 && (
            <div className="flex items-center gap-1 px-2 py-1 border"
              style={{ border: "1px solid var(--orange)", background: "rgba(255,102,0,0.08)" }}>
              <BellDot size={11} style={{ color: "var(--orange)" }} />
              <span style={{ color: "var(--orange)", fontSize: 10 }}>{unreadCount}</span>
            </div>
          )}
        </div>
      </div>

      {/* ── Live ticker ── */}
      {(ticker.length > 0 || runMsg) && (
        <div
          className="flex items-center gap-3 px-4 py-1 border-b shrink-0 overflow-hidden"
          style={{ borderColor: "var(--border)", background: "#0a0f08", minHeight: 26 }}
        >
          <Zap size={10} style={{ color: "var(--green)", flexShrink: 0 }} />
          <div className="flex gap-4 overflow-hidden" style={{ color: "var(--green)", fontSize: 10, letterSpacing: "0.05em", whiteSpace: "nowrap" }}>
            {runMsg && <span style={{ color: "var(--yellow)" }}>{runMsg}</span>}
            {ticker.slice(0, 4).map((t, i) => (
              <span key={i} style={{ opacity: i === 0 ? 1 : 0.5 }}>{t}</span>
            ))}
          </div>
        </div>
      )}

      {/* ── Tabs ── */}
      <div className="flex border-b shrink-0" style={{ borderColor: "var(--border)", background: "var(--panel)" }}>
        {TABS.map((tab) => (
          <button
            key={tab}
            onClick={() => setActiveTab(tab)}
            className="px-5 py-2 text-xs border-r relative"
            style={{
              borderColor: "var(--border)",
              color: activeTab === tab ? "var(--orange)" : "var(--text-dim)",
              background: activeTab === tab ? "var(--bg)" : "transparent",
              cursor: "pointer",
              letterSpacing: "0.12em",
              borderBottom: activeTab === tab ? "2px solid var(--orange)" : "2px solid transparent",
            }}
          >
            {tab}
            {tab === "CHANGES" && unreadCount > 0 && (
              <span className="absolute top-1 right-1 rounded-full text-center"
                style={{ fontSize: 8, background: "var(--orange)", color: "#000", width: 14, height: 14, lineHeight: "14px" }}>
                {unreadCount}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* ── Panel ── */}
      <div className="flex-1 overflow-hidden">
        {activeTab === "TIMELINE"   && <TimelinePanel   topicName={topicName} refreshSignal={stats.events} />}
        {activeTab === "ARTICLES"   && <ArticlesPanel   topicName={topicName} />}
        {activeTab === "CHAT"       && <ChatPanel       topicName={topicName} />}
        {activeTab === "PERCEPTION" && <PerceptionPanel topicName={topicName} />}
        {activeTab === "CHANGES"    && <ChangesPanel    topicName={topicName} liveChanges={liveChanges} />}
      </div>
    </div>
  );
}

function Stat({ icon, value, label }: { icon: React.ReactNode; value: number; label: string }) {
  return (
    <div className="flex items-center gap-1">
      <span style={{ color: "var(--text-dim)" }}>{icon}</span>
      <span style={{ color: "var(--text-bright)", fontSize: 11, fontWeight: 700 }}>{value}</span>
      <span style={{ color: "var(--text-dim)", fontSize: 9 }}>{label}</span>
    </div>
  );
}
