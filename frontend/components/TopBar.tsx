"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { Activity, Radio } from "lucide-react";

export default function TopBar() {
  const [time, setTime] = useState("");

  useEffect(() => {
    const tick = () => {
      const now = new Date();
      setTime(
        now.toUTCString().replace(/.*(\d{2}:\d{2}:\d{2}).*/, "$1") + " UTC"
      );
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);

  return (
    <header
      className="flex items-center justify-between px-4 shrink-0 border-b"
      style={{
        height: 36,
        background: "var(--panel)",
        borderColor: "var(--border)",
      }}
    >
      {/* Left — brand */}
      <Link href="/" className="flex items-center gap-2 no-underline">
        <Activity size={14} style={{ color: "var(--orange)" }} />
        <span
          className="font-bold tracking-widest text-xs"
          style={{ color: "var(--orange)", letterSpacing: "0.2em" }}
        >
          NEWS·INTEL
        </span>
        <span
          className="text-xs px-1 border"
          style={{ color: "var(--text-dim)", borderColor: "var(--border-bright)", fontSize: 10 }}
        >
          TERMINAL v0.1
        </span>
      </Link>

      {/* Center — status indicators */}
      <div className="flex items-center gap-4">
        <StatusDot label="API" color="var(--green)" />
        <StatusDot label="SCHEDULER" color="var(--green)" />
        <StatusDot label="STREAM" color="var(--yellow)" pulse />
      </div>

      {/* Right — clock */}
      <div className="flex items-center gap-3">
        <Radio size={11} style={{ color: "var(--text-dim)" }} />
        <span className="tabular-nums" style={{ color: "var(--text-dim)", fontSize: 11 }}>
          {time}
        </span>
      </div>
    </header>
  );
}

function StatusDot({
  label,
  color,
  pulse,
}: {
  label: string;
  color: string;
  pulse?: boolean;
}) {
  return (
    <div className="flex items-center gap-1">
      <span
        className={`inline-block rounded-full ${pulse ? "pulse-orange" : ""}`}
        style={{ width: 6, height: 6, background: color }}
      />
      <span style={{ color: "var(--text-dim)", fontSize: 10, letterSpacing: "0.1em" }}>
        {label}
      </span>
    </div>
  );
}
