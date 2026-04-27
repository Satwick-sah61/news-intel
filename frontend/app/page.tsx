"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { api, type Topic } from "@/lib/api";
import { Plus, Play, Trash2, Clock, AlertCircle, ChevronRight } from "lucide-react";

export default function HomePage() {
  const [topics, setTopics] = useState<Topic[]>([]);
  const [loading, setLoading] = useState(true);
  const [showAdd, setShowAdd] = useState(false);
  const [newName, setNewName] = useState("");
  const [intervalMin, setIntervalMin] = useState(30);
  const [adding, setAdding] = useState(false);
  const [running, setRunning] = useState<Set<string>>(new Set());
  const [error, setError] = useState("");

  const load = () =>
    api.topics.list().then(setTopics).catch(console.error).finally(() => setLoading(false));

  useEffect(() => { load(); }, []);

  async function addTopic() {
    if (!newName.trim()) return;
    setAdding(true);
    setError("");
    try {
      await api.topics.create(newName.trim(), intervalMin);
      setNewName("");
      setShowAdd(false);
      await load();
    } catch (e: any) {
      setError(e.message);
    } finally {
      setAdding(false);
    }
  }

  async function deleteTopic(name: string) {
    if (!confirm(`Delete topic "${name}"?`)) return;
    await api.topics.delete(name);
    await load();
  }

  async function runPipeline(name: string) {
    setRunning((s) => new Set(s).add(name));
    try {
      await api.pipeline.run(name);
    } finally {
      setTimeout(() => setRunning((s) => { const n = new Set(s); n.delete(name); return n; }), 3000);
    }
  }

  return (
    <div className="h-full flex flex-col overflow-hidden" style={{ background: "var(--bg)" }}>
      {/* Header bar */}
      <div
        className="flex items-center justify-between px-6 py-3 border-b shrink-0"
        style={{ borderColor: "var(--border)", background: "var(--panel)" }}
      >
        <div>
          <div className="flex items-center gap-3">
            <span style={{ color: "var(--orange)", fontWeight: 700, letterSpacing: "0.15em", fontSize: 11 }}>
              INTELLIGENCE BOARD
            </span>
            <span style={{ color: "var(--text-dim)", fontSize: 10 }}>// ACTIVE TOPICS</span>
          </div>
          <div style={{ color: "var(--text-dim)", fontSize: 10, marginTop: 2 }}>
            {topics.length} topic{topics.length !== 1 ? "s" : ""} under surveillance
          </div>
        </div>
        <button
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-2 px-3 py-1 border text-xs"
          style={{ borderColor: "var(--orange)", color: "var(--orange)", background: "transparent", cursor: "pointer", letterSpacing: "0.1em" }}
        >
          <Plus size={12} /> ADD TOPIC
        </button>
      </div>

      {/* Add Topic Modal */}
      {showAdd && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center"
          style={{ background: "rgba(0,0,0,0.85)" }}
          onClick={(e) => e.target === e.currentTarget && setShowAdd(false)}
        >
          <div className="border p-6 w-96" style={{ background: "var(--panel)", borderColor: "var(--border-bright)" }}>
            <div style={{ color: "var(--orange)", fontWeight: 700, letterSpacing: "0.15em", fontSize: 11, marginBottom: 16 }}>
              + NEW INTELLIGENCE TOPIC
            </div>
            {error && (
              <div className="flex items-center gap-2 mb-3 text-xs" style={{ color: "var(--red)" }}>
                <AlertCircle size={12} /> {error}
              </div>
            )}
            <div className="flex flex-col gap-3">
              <div>
                <label style={{ color: "var(--text-dim)", fontSize: 10, letterSpacing: "0.1em" }}>TOPIC NAME</label>
                <input
                  className="w-full mt-1 px-3 py-2 border text-sm outline-none"
                  style={{ background: "var(--bg)", borderColor: "var(--border-bright)", color: "var(--text-bright)", fontFamily: "inherit" }}
                  placeholder="e.g. Iran War"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && addTopic()}
                  autoFocus
                />
              </div>
              <div>
                <label style={{ color: "var(--text-dim)", fontSize: 10, letterSpacing: "0.1em" }}>SCRAPE INTERVAL (MIN)</label>
                <input
                  type="number"
                  className="w-full mt-1 px-3 py-2 border text-sm outline-none"
                  style={{ background: "var(--bg)", borderColor: "var(--border-bright)", color: "var(--text-bright)", fontFamily: "inherit" }}
                  value={intervalMin}
                  onChange={(e) => setIntervalMin(Number(e.target.value))}
                  min={5}
                />
              </div>
              <div className="flex gap-2 mt-2">
                <button
                  onClick={addTopic}
                  disabled={adding}
                  className="flex-1 py-2 text-xs font-bold"
                  style={{ background: "var(--orange)", color: "#000", cursor: adding ? "not-allowed" : "pointer", letterSpacing: "0.1em", border: "none" }}
                >
                  {adding ? "ADDING..." : "CONFIRM"}
                </button>
                <button
                  onClick={() => { setShowAdd(false); setError(""); }}
                  className="px-4 py-2 text-xs border"
                  style={{ borderColor: "var(--border-bright)", color: "var(--text-dim)", background: "transparent", cursor: "pointer" }}
                >
                  CANCEL
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Topic grid */}
      <div className="flex-1 overflow-y-auto p-6">
        {loading ? (
          <div style={{ color: "var(--text-dim)", fontSize: 12 }}>LOADING TOPICS<span className="cursor-blink">_</span></div>
        ) : topics.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 gap-3">
            <div style={{ color: "var(--text-dim)", fontSize: 11, letterSpacing: "0.15em" }}>NO ACTIVE TOPICS</div>
            <div style={{ color: "var(--text-dim)", fontSize: 10 }}>Click ADD TOPIC to begin surveillance</div>
          </div>
        ) : (
          <div className="grid gap-px" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 12 }}>
            {topics.map((t) => (
              <TopicCard key={t.id} topic={t} isRunning={running.has(t.name)} onRun={() => runPipeline(t.name)} onDelete={() => deleteTopic(t.name)} />
            ))}
          </div>
        )}
      </div>

      {/* Status bar */}
      <div
        className="flex items-center px-6 shrink-0 border-t"
        style={{ height: 28, borderColor: "var(--border)", background: "var(--panel)" }}
      >
        <span style={{ color: "var(--text-dim)", fontSize: 10, letterSpacing: "0.08em" }}>
          SYS:READY &nbsp;|&nbsp; TOPICS:{topics.length} &nbsp;|&nbsp; SCHEDULER:ACTIVE &nbsp;|&nbsp; DB:ONLINE
        </span>
      </div>
    </div>
  );
}

function TopicCard({ topic, isRunning, onRun, onDelete }: {
  topic: Topic; isRunning: boolean; onRun: () => void; onDelete: () => void;
}) {
  const scraped = topic.last_scraped
    ? new Date(topic.last_scraped + "Z").toLocaleString()
    : "Never";

  return (
    <div className="border flex flex-col" style={{ background: "var(--panel)", borderColor: "var(--border)" }}>
      <div className="flex items-center justify-between px-4 py-2 border-b" style={{ borderColor: "var(--border)", background: "var(--panel-hover)" }}>
        <div className="flex items-center gap-2">
          <span className="inline-block rounded-full" style={{ width: 6, height: 6, background: topic.active ? "var(--green)" : "var(--text-dim)" }} />
          <span style={{ color: "var(--text-bright)", fontWeight: 700, fontSize: 12, letterSpacing: "0.08em" }}>
            {topic.name.toUpperCase()}
          </span>
        </div>
        <span style={{ color: "var(--text-dim)", fontSize: 10 }}>#{String(topic.id).padStart(4, "0")}</span>
      </div>

      <div className="px-4 py-3 flex-1">
        <div className="flex items-center gap-2 mb-2">
          <Clock size={10} style={{ color: "var(--text-dim)" }} />
          <span style={{ color: "var(--text-dim)", fontSize: 10 }}>LAST SCRAPED</span>
        </div>
        <div style={{ color: "var(--text)", fontSize: 11 }}>{scraped}</div>
      </div>

      <div className="flex border-t" style={{ borderColor: "var(--border)" }}>
        <Link
          href={`/topics/${encodeURIComponent(topic.name)}`}
          className="flex-1 flex items-center justify-center gap-1 py-2 border-r no-underline"
          style={{ borderColor: "var(--border)", color: "var(--orange)", fontSize: 11, letterSpacing: "0.1em" }}
        >
          OPEN <ChevronRight size={10} />
        </Link>
        <button
          onClick={onRun}
          disabled={isRunning}
          className="flex items-center justify-center gap-1 px-4 py-2 border-r"
          style={{ borderColor: "var(--border)", color: isRunning ? "var(--text-dim)" : "var(--green)", background: "transparent", cursor: isRunning ? "not-allowed" : "pointer", fontSize: 11, letterSpacing: "0.1em" }}
        >
          <Play size={10} /> {isRunning ? "RUNNING" : "RUN"}
        </button>
        <button
          onClick={onDelete}
          className="flex items-center justify-center px-3 py-2"
          style={{ color: "var(--text-dim)", background: "transparent", cursor: "pointer", border: "none" }}
        >
          <Trash2 size={11} />
        </button>
      </div>
    </div>
  );
}
