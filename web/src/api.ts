// Tiny typed client for the Python backend (api.py). Errors carry the backend's plain-English message.

export class ApiError extends Error {}

async function req<T>(method: string, url: string, body?: unknown): Promise<T> {
  const init: RequestInit = { method };
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) {
    init.body = JSON.stringify(body);
    init.headers = { "Content-Type": "application/json" };
  }
  let res: Response;
  try {
    res = await fetch(url, init);
  } catch {
    throw new ApiError("Can't reach PlateRank. Is the terminal running `python run.py` still open?");
  }
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const raw = typeof data.detail === "string" ? data.detail : "";
    // a missing route (old server still running) or raw HTTP text -> one plain sentence
    if ((res.status === 404 || res.status === 405) && (!raw || /^(not found|method not allowed)$/i.test(raw)))
      throw new ApiError("That action isn't available - restart PlateRank (Ctrl+C, then python run.py) and refresh the page.");
    throw new ApiError(raw || "Something went wrong - try again.");
  }
  return data as T;
}

export const api = {
  get: <T>(url: string) => req<T>("GET", url),
  post: <T>(url: string, body?: unknown) => req<T>("POST", url, body ?? {}),
  put: <T>(url: string, body: unknown) => req<T>("PUT", url, body),
};

// ---------------------------------------------------------------- shapes
export type Status = { claude_key: boolean; gemini_key: boolean; platforms: string[]; claude_model: string; discovery_model: string };

export type Competitor = { name: string; website?: string; aliases?: string[]; address?: string; source?: string };

export type Profile = {
  name: string;
  website?: string;
  cuisine: string;
  area: string;
  neighbourhood?: string;
  city?: string;
  state?: string;
  city_id?: string;
  address?: string;
  hours?: string;
  lat?: number;
  lon?: number;
  price_level?: number | null;
  landmarks?: string[];
  aliases?: string[];
  signature_terms?: string[];
  highlights?: string[];
  cuisine_alternates?: string[];
  area_nicknames?: string[];
  anchor_item?: string;
  phone?: string;
  year_opened?: number | null;
  menu?: { hero_dish_name?: string; hero_dish_price?: number | null; anchor_price?: number | null; source?: string };
  competitors?: Competitor[];
  competitor_menus?: Record<string, { entree_price?: number; anchor_price?: number; source?: string }>;
  facts_source?: Record<string, string>;
  pinned?: boolean;
};

export type RestaurantCard = { slug: string; name: string; cuisine: string; area: string; competitors?: number; last_run?: string | null; sample?: boolean; pinned?: boolean };

export type City = { id: string; name: string; state: string; state_name: string; lat: number; lon: number; population: number; radius_km: number };
export type PlaceHit = { name: string; osm_type: string; osm_id: number; kind: string; address: string; city: string; neighbourhood: string; lat: number; lon: number };
export type PlaceDetails = { name: string; cuisine: string; website: string; hours: string; phone: string; address: string; lat: number; lon: number; source: string };
export type Nearby = { name: string; cuisine: string; same_cuisine: boolean; website: string; address: string; distance_m: number | null; source: string };
export type NearbyResult = { results: Nearby[]; cached_at?: string | null; cached_radius?: number; map_unavailable?: boolean };
export type Source = { url: string; title: string };

export type Job = { id: string; state: "running" | "done" | "failed"; done: number; total: number; note: string; error: string | null; meta: RunMeta | null };
export type RunMeta = { when: string; platforms: string[]; runs: number; web_search: boolean; counts: Record<string, number>; cost_usd: number; questions: number };

export type Gap = { gap: string; evidence: string; affected_categories: string[]; action: "standard" | "creator" | "vfm"; priority: number };
export type Move = { title: string; evidence: string; quote?: string; route: "standard" | "creator" | "vfm"; priority: number | null; categories: string[] };

export type Results = {
  no_run?: boolean;
  headlines: Record<string, string>;
  todo: { id: string; title: string; why: string; link: string | null; tab: string; done: boolean }[];
  restaurant: string;
  slug: string;
  is_sample: boolean;
  meta: RunMeta;
  questions: Record<string, string>;
  approvals: Record<string, { at: string; text: string }>;
  mailto?: Record<string, string>;
  empty?: boolean;
  rank: {
    mention_rate: number; mentions: number; answers: number; avg_rank: number | null; share_of_voice: number;
    top_competitor: { name: string; mention_rate: number } | null;
    scorecard: { restaurant: string; mention_rate: number; mentions: number; avg_rank: number | null; share_of_voice: number }[];
    by_category: { category: string; queries: number; target_mentions: number; mention_rate: number }[];
    categories_at_zero: string[];
    answers_list: { query: string; category: string; platform: string; model: string; run: number; status: string; mentions: string[]; mentioned: boolean; rank: number | null; answer: string; note: string; sources: Source[] }[];
  };
  why: {
    ai_says: AiSays;
    gaps: Gap[]; site_gaps: string[]; site_audit: Record<string, { audit: Record<string, unknown>; source: string }>;
    ai_recommends_instead: { restaurant: string; answers_naming_it: number }[];
    competitor_frequency: { restaurant: string; appearances: number; share: number }[];
    sources_ai_used: { domain: string; answers: number }[];
    listings_note: string;
    listings: Record<string, { rating?: number; review_count?: number; price_level?: number; source?: string }>;
  };
  change: {
    moves: Move[]; lost_categories: string[]; vfm_needs_reviews: boolean;
    vfm: null | {
      benchmark_label: string; area_price_level: number | null; area_price_level_n: number;
      analyses: {
        restaurant: string; avg_rating: number; review_count: number; reviews_analysed: number; source: string;
        aspects: Record<string, { mentions: number; positive: number; negative: number; pos_ratio: number | null; pos_quotes: string[]; neg_quotes: string[] }>;
        vfm: { vfm_index: number; verdict: string; food_sentiment: number; price_sentiment: number };
        recommendations: { area: string; evidence: string; example_quote: string; recommendation: string }[];
      }[];
    };
  };
  make: {
    drafts: { key: string; title: string; kind: "text" | "code"; text: string }[];
    creators: { handle: string; name: string; platform: string; followers: number | null; relevance_score: number; why: string; verified?: boolean; source_url?: string;
      brief: { concept_title: string; hook: string; format: string; target_category: string; must_include_for_ai_citation: string[] }; outreach: string }[];
    creators_note: string;
    pack: ContentPack;
    housekeeping: Housekeeping;
  };
  improve: { history: { ts: number; platform: string; mention_rate: number; avg_rank: number | null; share_of_voice: number; answers: number }[]; note: string;
    compare: Compare };
};

export const pct = (x: number | null | undefined) => (x == null ? "—" : `${Math.round(x * 100)}%`);
export const usd = (x: number | null | undefined) => (x == null ? "—" : `$${x.toFixed(x < 1 ? 2 : 0)}`);
export const miles = (m: number | null) => (m == null ? "" : m < 160 ? `${m} m` : `${(m / 1609).toFixed(2)} mi`);

export type PackPiece = { key: string; title: string; kind: "json" | "text" | "code"; text: string; note: string; flags: string[] };
export type ContentPack = { pieces: PackPiece[]; is_sample: boolean; generated: { at: string; model: string } | null;
  facts_changed: boolean; can_generate: boolean };

type Snap = { when: string; mention_rate: number; avg_rank: number | null; share_of_voice: number; answers?: number };
export type Compare = { comparable: boolean; label: string; reason?: string; checks?: number; compared_checks?: number; skipped?: number;
  platforms?: string[]; first?: Snap; latest?: Snap; change?: { mention_rate: number | null; avg_rank: number | null; share_of_voice: number | null };
  by_category?: { category: string; first: number | null; latest: number | null; questions?: number }[];
  partial?: { when: string; first_when?: string; note: string; reason?: string; questions?: number;
    by_category: { category: string; first: number | null; latest: number | null; questions?: number }[] } | null };

export type Evidence = { id: string; status: "verified" | "unverified" | "rejected"; tier?: string; retrieved_at: string; source_url: string;
  page_title?: string; check_note?: string; found_by?: string; kind?: string; subject?: string; text?: string };

export type AiQuote = { quote: string; question: string; platform?: string; sources: string[] };
export type AiSays = { label: string; counts: Record<string, number>; groups: Record<"praised" | "criticised" | "described", AiQuote[]>; headline: AiQuote[] };
export type PublicQuote = { quote: string; rating?: string | number | null; date?: string | null; site?: string; source_url: string; evidence: Evidence };
export type PeopleSay = { can_search: boolean;
  saved: { at: string; items: PublicQuote[]; rejected: number; dropped_no_url: number } | null;
  business_value: { ready: boolean; reason?: string; sentiment?: string; counts?: Record<string, number>;
    actions?: { category: string; action: string; evidence: string; quote?: string; source_url?: string | null; kind?: "gap" | "complaint"; label?: string }[];
    aspects?: Record<string, { positive: number; negative: number; mentions: number; status: string }> } };

export type SiteNow = { at: string; url: string; ok: boolean; note?: string; title?: string;
  pieces: Record<string, { text: string; found: boolean; evidence: Evidence | null }> };
export type AisoItem = { key: string; title: string; strength: "Strong" | "Mixed" | "Weak"; file: string; kind: "text" | "code" | "json";
  before: string; before_url?: string | null; why: string; research: { text: string; url: string }[]; text: string; problems?: string[] };
export type Aiso = { researched: boolean; header: string; items: AisoItem[]; at?: string; url?: string; ok?: boolean; error?: string | null; lost?: string[];
  competitors?: { name: string; ok: boolean; url: string | null; error: string | null; title: string | null; schema: string[]; llms_txt?: boolean }[] };
export type Housekeeping = { site_now: SiteNow | null; aiso?: Aiso; reminders: Record<string, number>; pdf_keys: string[];
  social: { hashtags: string[]; keywords: string[]; checklist: string[]; note: string } };

export type RedditDraft = { key: string; type: "reply" | "post"; subreddit: string; title: string; text: string; flags: string[]; owner_note?: string;
  thread_url?: string; thread_title?: string; post_title?: string; rule?: string | null; flair_required?: boolean | null };
export type Farm = { at?: string; note: string; post_note: string; can_search: boolean;
  subreddits?: { name: string; url: string; evidence: Evidence; rules_url?: string; rule_quote?: string | null; rule_evidence?: Evidence | null;
    self_promotion: string; weekly_thread?: string | null; flair_required?: boolean | null }[];
  threads?: { subreddit: string; title: string; url: string; date?: string | null; asks_for?: string; evidence: Evidence }[];
  counts?: Record<string, number>; drafts?: RedditDraft[]; posted?: Record<string, { url: string; at: string }>;
  links: Record<string, { href: string; copy: string; kind: "post" | "reply" }>;
  cited: { status: string; note: string } | null };

export type RealCreator = { handle: string; name: string; platform: string; url: string; followers: number | null; local_to: string;
  niches: string[]; best_performing_format: string; photo_url: string | null; verified: boolean; evidence: Evidence;
  followers_evidence: Evidence | null; relevance_score: number; score_low: number | null; score_high: number | null; unknown: string[];
  why: string; brief: { concept_title: string; hook: string }; brief_text: string; outreach: string; outreach_key: string; saved: boolean };
export type CreatorsView = { at: string | null; creators: RealCreator[]; found: number; dropped_no_url: number; rejected: number;
  lost_categories: string[]; can_search: boolean };

export type AgentReview = { status: "ok" | "failed"; label: string; verdict: string; summary: string; cached: boolean; suggested_edit: string | null; reviewed_text: string; input_text: string;
  transcript: { agent: string; round: number; text: string; citations: string[]; note?: string }[];
  checklist: { rule: string; level: "hard" | "soft"; result: string; reason: string; cite: string; by: string }[];
  rejected_citations: { agent: string; round: number; id: string }[] };
