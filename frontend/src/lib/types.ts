export interface User {
  id: string;
  email: string;
  display_name: string;
  role: string;
  mfa_enabled: boolean;
  simple_mode: boolean;
  ai_consent: boolean;
  app_name: string;
  environment: string;
}

export interface Household {
  id: string;
  name: string;
  filing_status: "single" | "mfj";
  state: string;
  onboarding_complete: boolean;
  is_demo: boolean;
  role: string;
  member_count: number;
  current_year: number;
  states: string[];
  no_income_tax_states: string[];
}

export interface MemberRow {
  id: string;
  name: string;
  relationship_kind: "self" | "spouse";
  birth_year: number;
  retirement_age: number;
  life_expectancy: number;
  age: number;
  ss_monthly_benefit: number;
  ss_basis: "at_fra" | "as_claimed";
  ss_claim_age: number;
}

export interface HoldingRow {
  id: string;
  symbol: string;
  name: string;
  value: number;
  cost_basis: number | null;
  quantity: number | null;
  asset_class_key: string;
  is_fund: boolean;
}

export interface AccountRow {
  id: string;
  name: string;
  tax_type: "cash" | "taxable" | "traditional" | "roth" | "hsa";
  member_id: string | null;
  institution: string | null;
  balance: number;
  cost_basis: number | null;
  annual_contribution: number;
  employer_match: number;
  annual_fee: number;
  value: number;
  allocation: Record<string, number>;
  allocation_preset: string | null;
  holdings: HoldingRow[];
  has_holdings: boolean;
  source: string;
  balance_as_of: string | null;
}

export interface Row {
  year: number;
  ages: Record<string, number | null>;
  filing_status: string;
  price_index: number;
  [key: string]: number | string | Record<string, number | null>;
}

export interface Summary {
  funded: boolean;
  first_shortfall_year: number | null;
  first_shortfall_age: number | null;
  shortfall_years: number;
  total_shortfall_real: number;
  plan_end_year: number;
  plan_end_age_oldest: number;
  lifetime_taxes_nominal: number;
  lifetime_taxes_real: number;
  lifetime_medicare_premiums_real: number;
  lifetime_spending_real: number;
  total_roth_conversions_nominal: number;
  ending_portfolio_nominal: number;
  ending_portfolio_real: number;
  ending_net_worth_nominal: number;
  ending_net_worth_real: number;
  peak_portfolio_nominal: number;
  max_marginal_rate: number;
}

export interface Meta {
  engine_version: string;
  plan_hash: string;
  plan_name: string;
  start_year: number;
  end_year: number;
  tax_rule_versions: string[];
  inflation_assumption: number;
  seed?: number;
  n_paths?: number;
  distribution?: string;
  numpy_version?: string;
  success_definition?: string;
}

export interface Projection {
  id?: string;
  created_at?: string;
  meta: Meta;
  summary: Summary;
  years: number[];
  price_index: number[];
  rows: Row[];
  accounts: { id: string; name: string; tax_type: string; balances: number[] }[];
  members: { id: string; name: string; birth_year: number }[];
  warnings: string[];
  notes: string[];
}

export type Bands = { p10: number[]; p25: number[]; p50: number[]; p75: number[]; p90: number[] };

export interface MonteCarlo {
  id?: string;
  created_at?: string;
  meta: Meta;
  years: number[];
  price_index: number[];
  n_paths: number;
  success_probability: number;
  essential_success_probability: number;
  failed_paths: number;
  median_failure_year: number | null;
  median_failure_age: number | null;
  cumulative_failure_probability: number[];
  portfolio_nominal: Bands;
  portfolio_real: Bands;
  net_worth_real: Bands;
  spending_real: Bands;
  taxes_real: Bands;
  ending_portfolio_real: Record<string, number>;
  ending_portfolio_real_histogram: { edges: number[]; counts: number[] };
  lifetime_taxes_real: Record<string, number>;
  guardrails: {
    enabled: boolean;
    paths_with_a_cut: number;
    paths_with_a_raise: number;
    average_multiplier_by_year: number[];
    lowest_multiplier_p10: number;
  };
  warnings: string[];
  notes: string[];
  cached?: boolean;
  duration_ms?: number;
}

export interface Insights {
  status: "on_track" | "watch" | "at_risk";
  headline: string;
  points: { kind: string; text: string }[];
  numbers: {
    investments_today: number;
    success_probability: number | null;
    plan_end_age: number;
    plan_end_year: number;
    funded_in_projection: boolean;
    ending_portfolio_real: number;
    lifetime_taxes_real: number;
  };
  thresholds: { comfortable: number; watch: number; note: string };
  disclaimer: string;
  notes: string[];
  simulation: { seed: number; n_paths: number; distribution: string };
  chart: {
    years: number[];
    price_index: number[];
    projection_real: number[];
    p10_real: number[];
    p50_real: number[];
    p90_real: number[];
  };
  meta: Meta;
}

export interface Assumptions {
  inflation: number;
  healthcare_inflation: number;
  ss_cola: number | null;
  ss_reduction_pct: number;
  ss_reduction_year: number | null;
  spousal_benefits: boolean;
  withdrawal_strategy: "taxable_first" | "traditional_first" | "roth_first" | "proportional";
  roth_conversion: {
    mode: "none" | "fixed" | "fill_bracket" | "fill_magi";
    amount: number;
    bracket_rate: number;
    start_year: number | null;
    end_year: number | null;
  };
  guardrails: {
    enabled: boolean;
    upper_band: number;
    lower_band: number;
    cut_pct: number;
    raise_pct: number;
    min_multiplier: number;
    max_multiplier: number;
  };
  state_tax: { state: string; rate: number; taxes_social_security: boolean; exempts_retirement_income: boolean };
  model_medicare_premiums: boolean;
  prior_magi: number[] | null;
  survivor_expense_pct: number;
  heir_tax_rate: number;
  tax_rule_year: number | null;
}

export interface AssetClassRow {
  key: string;
  name: string;
  expected_return: number;
  volatility: number;
  income_yield: number;
  qualified_ratio: number;
  proxy: string;
}

export interface PlanInfo {
  plan: { id: string; name: string; start_year: number };
  assumptions: Assumptions;
  assumption_version: number;
  assumption_note: string | null;
  assumption_saved_at: string;
  defaults: Assumptions;
  asset_classes: AssetClassRow[];
  correlations: Record<string, Record<string, number>>;
  strategy_labels: Record<string, string>;
  tax_rules: { tax_year: number; version: string; sources: string[] }[];
  state_tax_note: string;
  engine_version: string;
}
