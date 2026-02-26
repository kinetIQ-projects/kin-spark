// ── Paginated response ───────────────────────────────────────────

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// ── Conversations ────────────────────────────────────────────────

export interface ConversationListItem {
  id: string;
  first_message_preview: string | null;
  turn_count: number;
  state: string;
  outcome: string | null;
  sentiment: string | null;
  created_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
}

export interface TranscriptMessage {
  id: string;
  role: string;
  content: string;
  created_at: string;
}

export interface LeadSummary {
  id: string;
  name: string | null;
  email: string | null;
  phone: string | null;
  status: string;
  created_at: string;
}

export interface ConversationDetail {
  id: string;
  client_id: string;
  turn_count: number;
  state: string;
  outcome: string | null;
  sentiment: string | null;
  sentiment_score: number | null;
  summary: string | null;
  created_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  messages: TranscriptMessage[];
  lead: LeadSummary | null;
}

// ── Leads ────────────────────────────────────────────────────────

export interface LeadListItem {
  id: string;
  client_id: string;
  conversation_id: string | null;
  name: string | null;
  email: string | null;
  phone: string | null;
  notes: string | null;
  status: string;
  admin_notes: string | null;
  created_at: string;
}

export interface LeadUpdate {
  status?: string;
  admin_notes?: string;
}

// ── Client Profile ───────────────────────────────────────────────

export interface ClientProfile {
  id: string;
  name: string;
  slug: string;
  active: boolean;
  max_turns: number;
  rate_limit_rpm: number;
  accent_color: string | null;
  widget_position: string | null;
  widget_title: string | null;
  greeting_message: string | null;
  notification_email: string | null;
  notifications_enabled: boolean;
  daily_conversation_cap: number | null;
  sessions_per_visitor_per_day: number | null;
  settling_config: Record<string, unknown>;
  created_at: string | null;
}

export interface SettingsUpdate {
  timezone?: string;
}

// ── Dashboard ───────────────────────────────────────────────────

export interface DashboardSummary {
  total_conversations: number;
  total_leads: number;
  conversion_rate: number;
  avg_turns: number;
  avg_duration_seconds: number | null;
  conversations_with_duration: number;
}

export interface TimeseriesPoint {
  date: string;
  conversations: number;
  leads: number;
}

export interface OutcomeBucket {
  outcome: string;
  count: number;
}

export interface SentimentBucket {
  sentiment: string;
  count: number;
}

export interface DashboardTimeseries {
  daily: TimeseriesPoint[];
  outcomes: OutcomeBucket[];
  sentiments: SentimentBucket[];
}

export type DateRange = 7 | 30 | 90;

// ── Knowledge ───────────────────────────────────────────────────

export type KnowledgeCategory =
  | "company"
  | "product"
  | "competitor"
  | "legal"
  | "team"
  | "fun";

export interface KnowledgeItem {
  id: string;
  client_id: string;
  title: string;
  content: string;
  category: KnowledgeCategory;
  subcategory: string | null;
  priority: number;
  active: boolean;
  embedding_model: string | null;
  content_hash: string;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeCreate {
  title: string;
  content: string;
  category: KnowledgeCategory;
  subcategory?: string;
  priority?: number;
  active?: boolean;
}

export interface KnowledgeUpdate {
  title?: string;
  content?: string;
  category?: KnowledgeCategory;
  subcategory?: string;
  priority?: number;
  active?: boolean;
}

export interface KnowledgeStats {
  total_items: number;
  active_items: number;
  categories: Record<string, number>;
}
