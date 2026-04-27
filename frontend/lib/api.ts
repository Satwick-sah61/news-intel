const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${text}`);
  }
  return res.json();
}

// ── Types ─────────────────────────────────────────────────────────────────────

export interface Topic {
  id: number;
  name: string;
  created_at: string;
  last_scraped: string | null;
  active: boolean;
}

export interface Article {
  id: number;
  url: string;
  title: string;
  summary: string;
  source: string;
  source_tier: number;
  source_tier_label: string;
  trust_label: string;
  region: string | null;
  published_at: string | null;
  relevance_score: number;
  sentiment: string;
  sentiment_score: number;
  key_claims: string[];
  entities_people: string[];
  entities_locations: string[];
  entities_orgs: string[];
  source_type: string;
}

export interface PaginatedArticles {
  total: number;
  page: number;
  limit: number;
  items: Article[];
}

export interface TimelineEvent {
  id: number;
  event_id: string;
  headline: string;
  summary: string;
  event_type: string;
  narrative_state: string;
  significance_score: number;
  first_seen: string | null;
  last_updated: string | null;
  source_count: number;
  tier1_count: number;
  dominant_sentiment: string;
  trust_label: string;
  locations: string[];
  people: string[];
  organizations: string[];
}

export interface EventSource {
  url: string;
  title: string;
  source: string;
  source_tier: number;
  trust_label: string;
  region: string | null;
  published_at: string | null;
  sentiment: string;
}

export interface EventDetail extends TimelineEvent {
  sources: EventSource[];
}

export interface ChatMessage {
  id: number;
  role: string;
  content: string;
  created_at: string;
}

export interface RegionalPerception {
  region: string;
  sentiment: string;
  sentiment_score: number;
  dominant_narrative: string;
  key_themes: string[];
  post_count: number;
  platform_breakdown: Record<string, number>;
  sample_quotes: string[];
  analysed_at: string;
}

export interface PerceptionResponse {
  topic: string;
  total_posts: number;
  regions: RegionalPerception[];
}

export interface NarrativeChange {
  id: number;
  change_type: string;
  headline: string;
  description: string;
  significance: number;
  detected_at: string;
  delivered: boolean;
}

export interface PipelineStatus {
  topic: string;
  status: string;
  articles_saved?: number;
  events_saved?: number;
  changes_detected?: number;
  message: string;
}

// ── Topics ────────────────────────────────────────────────────────────────────

export const api = {
  topics: {
    list: () => req<Topic[]>("/topics"),
    get: (name: string) => req<Topic>(`/topics/${enc(name)}`),
    create: (name: string, interval_min = 30) =>
      req<Topic>("/topics", { method: "POST", body: JSON.stringify({ name, interval_min }) }),
    delete: (name: string) =>
      req<{ message: string }>(`/topics/${enc(name)}`, { method: "DELETE" }),
  },

  articles: {
    list: (topic: string, page = 1, limit = 20, sentiment?: string, minRelevance?: number) => {
      const p = new URLSearchParams({ page: String(page), limit: String(limit) });
      if (sentiment) p.set("sentiment", sentiment);
      if (minRelevance) p.set("min_relevance", String(minRelevance));
      return req<PaginatedArticles>(`/topics/${enc(topic)}/articles?${p}`);
    },
  },

  timeline: {
    list: (topic: string) => req<TimelineEvent[]>(`/topics/${enc(topic)}/timeline`),
    get: (topic: string, eventId: string) =>
      req<EventDetail>(`/topics/${enc(topic)}/timeline/${eventId}`),
  },

  chat: {
    send: (topic: string, message: string) =>
      req<{ reply: string; topic: string }>(`/topics/${enc(topic)}/chat`, {
        method: "POST",
        body: JSON.stringify({ message }),
      }),
    history: (topic: string) => req<ChatMessage[]>(`/topics/${enc(topic)}/chat/history`),
    clear: (topic: string) =>
      req<{ message: string }>(`/topics/${enc(topic)}/chat/history`, { method: "DELETE" }),
  },

  perception: {
    get: (topic: string) => req<PerceptionResponse>(`/topics/${enc(topic)}/perception`),
  },

  pipeline: {
    run: (topic: string) =>
      req<PipelineStatus>(`/topics/${enc(topic)}/run`, { method: "POST" }),
    status: (topic: string) => req<PipelineStatus>(`/topics/${enc(topic)}/pipeline/status`),
    schedule: (topic: string) => req<ScheduleOut>(`/topics/${enc(topic)}/schedule`),
    changes: (topic: string, undeliveredOnly = false) =>
      req<NarrativeChange[]>(
        `/topics/${enc(topic)}/changes?undelivered_only=${undeliveredOnly}`
      ),
    markDelivered: (topic: string) =>
      req<{ message: string }>(`/topics/${enc(topic)}/changes/mark-delivered`, {
        method: "POST",
      }),
    setMonitoring: (topic: string, active: boolean) =>
      req<ScheduleOut>(`/topics/${enc(topic)}/monitoring`, {
        method: "POST",
        body: JSON.stringify({ active }),
      }),
  },
};

export interface ScheduleOut {
  topic: string;
  interval_min: number;
  active: boolean;
}

function enc(s: string) {
  return encodeURIComponent(s);
}

// ── SSE stream helper ─────────────────────────────────────────────────────────

export interface LiveStats { articles: number; events: number; }

export function subscribeToStream(
  topic: string,
  onChange: (change: NarrativeChange) => void,
  onStats: (stats: LiveStats) => void,
): () => void {
  const es = new EventSource(`${BASE}/topics/${enc(topic)}/stream`);
  es.addEventListener("narrative_change", (e) => {
    try { onChange(JSON.parse(e.data)); } catch {}
  });
  es.addEventListener("stats", (e) => {
    try { onStats(JSON.parse(e.data)); } catch {}
  });
  return () => es.close();
}
