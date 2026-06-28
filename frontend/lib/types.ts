// Shared DTOs mirroring the FastAPI backend contract.
// Screen tasks (Home / Projects / Detail / Settings) import these.

export interface ProjectListItem {
  id: number;
  title: string | null;
  url: string | null;
  client_name: string | null;
  client_hiring_rate: number | null;
  budget_min: number | null;
  budget_max: number | null;
  currency: string | null;
  tier: number | null;
  tier_label: string | null;
  bids_count: number | null;
  posted_at: string | null;
  site_status: string;
  eval_status: string;
  qualified: boolean;
  // Feature 3 — personal projection (defaulted when no record exists).
  favorite: boolean;
  personal_status: string;
  personal_status_label: string;
  tags: string[];
  hidden: boolean;
}

export interface ProjectListResponse {
  items: ProjectListItem[];
  total: number;
  page: number;
  page_size: number;
}

export interface ClientPanel {
  id: number;
  name: string | null;
  hiring_rate: number | null;
  projects_posted: number | null;
  projects_open: number | null;
  hires_count: number | null;
  avg_rating: number | null;
  reviews_count: number | null;
  total_spent: number | null;
  country: string | null;
  member_since: string | null;
  verified: boolean;
}

export interface ProjectDetail extends ProjectListItem {
  description: string | null;
  category: string | null;
  skills: string[] | null;
  scraped_at: string | null;
  client: ClientPanel | null;
  same_client_projects: ProjectListItem[];
  // Feature 3 — the full personal record for the detail/workspace view.
  personal: PersonalRecord | null;
}

export interface HomeOverview {
  found_today: number;
  qualified_today: number;
  total_projects: number;
  total_clients: number;
  last_successful_scrape: string | null;
  latest_run_status: string | null;
  health: "green" | "red" | "unknown";
  // Feature 3 — intentional-idle state, distinct from a fault.
  paused: boolean;
}

// ---------------------------------------------------------------------------
// Feature 3 — personal pipeline & workspace DTOs (mirror api/schemas.py)
// ---------------------------------------------------------------------------

export interface PersonalRecord {
  project_id: number;
  favorite: boolean;
  status: string;
  status_label: string;
  tags: string[];
  applied_at: string | null;
  won_amount: number | null;
  lost_reason: string | null;
  notes: string;
  board_position: number;
  hidden: boolean;
  status_changed_at: string | null;
  reminder_at: string | null;
}

// Partial create-or-update body; any subset of fields.
export interface PersonalUpdate {
  favorite?: boolean;
  status?: string;
  tags?: string[];
  applied_at?: string | null;
  won_amount?: number | null;
  lost_reason?: string | null;
  notes?: string;
  hidden?: boolean;
  reminder_at?: string | null;
}

export interface BoardCard {
  project_id: number;
  title: string | null;
  url: string | null;
  client_hiring_rate: number | null;
  budget_min: number | null;
  budget_max: number | null;
  currency: string | null;
  tier: number | null;
  tier_label: string | null;
  bids_count: number | null;
  posted_at: string | null;
  tags: string[];
  status: string;
  board_position: number;
}

export interface BoardColumn {
  key: string;
  label: string;
  cards: BoardCard[];
}

export interface BoardResponse {
  columns: BoardColumn[];
}

export interface BoardMoveRequest {
  project_id: number;
  to_status: string;
  position: number;
}

export interface AttachmentItem {
  id: number;
  project_id: number;
  original_name: string;
  file_type: "pdf" | "docx" | "md";
  size_bytes: number;
  uploaded_at: string;
  can_preview: boolean;
}

export interface AttachmentListResponse {
  items: AttachmentItem[];
}

export interface ControlState {
  paused: boolean;
}

export interface UploadConfig {
  allowed_types: string[];
  max_bytes: number;
}

// A configured pipeline stage (from GET /api/board columns or the statuses config).
export interface PersonalStatusOption {
  key: string;
  label: string;
}

export interface SettingItem {
  key: string;
  value: number | string;
  type: "int" | "float";
  min: number | null;
  max: number | null;
  label: string;
}

export interface SettingsResponse {
  items: SettingItem[];
}

export interface AuthStatus {
  authenticated: boolean;
  auth_enabled: boolean;
}

// 422 validation error body shape returned by PUT /api/settings.
export interface SettingsValidationError {
  detail: string;
  errors: { key: string; message: string }[];
}
