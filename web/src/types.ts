export type Period = string;
export interface Source {
  id?: string;
  title: string;
  url: string;
  published?: string | null;
  role?: string;
  raw_path?: string;
}
export interface CaseVersion {
  mass_g: number;
  price_gbp: number | null;
  price_basis: string;
  barcode: string | null;
  period: Period;
  transaction_date?: string | null;
  price_per_100g_gbp?: number | null;
}
export interface CasePhoto {
  role: string;
  local_path: string;
  source_url: string;
  attribution: string;
  license: string;
  evidence_note: string;
}
export interface RecipeHistory {
  status: string;
  scope_note: string;
  old: { period: string; mass_g: number | null; source_id: string; ingredients_summary: string[] };
  new: { period: string; mass_g: number | null; source_id: string; ingredients_summary: string[] };
  changes: Array<{ label: string; before: string; after: string; note?: string }>;
  limitations: string[];
  sources: Source[];
}
export interface SnackCase {
  id: string;
  name: string;
  format?: string;
  brand: string;
  category: string;
  market: string;
  reported_year?: number;
  retailer: string | null;
  old: CaseVersion;
  new: CaseVersion;
  mass_change_fraction: number;
  unit_price_change_fraction: number | null;
  evidence_status: string;
  event_date: string | null;
  event_date_precision: string;
  sources: Source[];
  limitations: string[];
  photos: CasePhoto[];
  recipe_history?: RecipeHistory;
  recipe_comparison_available?: boolean;
  family_link: { status: string; old_barcode: string | null; new_barcode: string | null; note: string; supporting_urls?: string[] };
}
export interface HistoryPoint { date: string; price_gbp: number; unit_price_gbp: number; mass_g?: number | null }
export interface ProductHistory {
  id: string; name: string; retailer: string; dimension: string; price_basis: string;
  points: HistoryPoint[]; source_url: string; identity_scope: string;
}
export interface ComparisonItem {
  id: string; name: string; mass_g: number; price_gbp: number;
  price_per_100g_gbp: number; price_basis: string;
}
export interface ComparisonGroup {
  id?: string; group: string; label?: string; date: string; retailer: string;
  items: ComparisonItem[]; source_url: string;
}
export interface ModelResult {
  name?: string; model?: string; status: string; mae?: number | null;
  rmse?: number | null; mae_percentage_points?: number | null; rmse_percentage_points?: number | null; reason?: string;
}
export interface ReferenceResult {
  mae?: number | null; mae_percentage_points?: number | null; rmse?: number | null;
  rmse_percentage_points?: number | null; observations?: number; rows?: number;
  label?: string; note?: string; interpretation?: string;
  [key: string]: unknown;
}
export interface Evaluation {
  status: string; reason: string[]; coverage: Record<string, unknown>;
  target_definition: string | Record<string, string>; models: ModelResult[];
  observed_nochange_reference: ReferenceResult | null;
  feature_ablations: Array<{name?: string; features?: string; status: string; reason?: string; [key: string]: unknown}>;
  [key: string]: unknown;
}
export interface DemoData {
  generated_at: string; cases: SnackCase[]; histories: ProductHistory[];
  comparisons: ComparisonGroup[]; evaluation: Evaluation;
  coverage: Record<string, unknown>;
  recipe_findings?: Array<{ id: string; name: string; brand: string; recipe_history: RecipeHistory }>;
  category_forecast?: CategoryForecastReport;
  category_tuning?: CategoryForecastReport;
  category_policy_tuning?: CategoryForecastReport;
}

export interface CategoryModelScore {
  model_id: string; feature_group: string; validation_mae_pp?: number | null;
  test_mae_pp: number | null; test_rmse_pp?: number | null;
  [key: string]: unknown;
}
export interface CategoryForecast {
  category_id: string; category_name: string;
  selected_model_id: string; selected_feature_group: string; selection_basis?: string;
  forecast: { as_of: string; target_month: string; change_pct: number; [key: string]: unknown };
  test_metrics: { mae_pp: number; rmse_pp: number; n: number; [key: string]: unknown };
  baseline_metrics: Record<string, unknown>;
  validation_metrics?: { mae_pp: number; rmse_pp: number; n: number };
  original_metrics?: { mae_pp: number; rmse_pp: number; n: number };
  leaderboard: CategoryModelScore[];
  test_predictions: Array<{ target_month: string; actual_pct: number; predicted_pct: number; baseline_pct: number; model_id?: string; selected_model_id?: string; candidate_id?: string }>;
  [key: string]: unknown;
}
export interface CategoryForecastReport {
  categories: CategoryForecast[];
  [key: string]: unknown;
}
