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
}

export interface HomeOverview {
  found_today: number;
  qualified_today: number;
  total_projects: number;
  total_clients: number;
  last_successful_scrape: string | null;
  latest_run_status: string | null;
  health: "green" | "red" | "unknown";
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
