import type { CategoryForecast, CategoryModelScore } from './types';

export interface ErrorComparison {
  referenceMaePp: number;
  modelMaePp: number;
  absoluteReductionPp: number;
  relativeReductionPct: number | null;
}

export interface ForecastEvidence {
  testMonths: number;
  startMonth: string | null;
  endMonth: string | null;
  scope: 'original' | 'exploratory';
  noChange: ErrorComparison | null;
  seasonal: ErrorComparison | null;
  commodity: ErrorComparison | null;
  commodityUnavailableReason: string;
}

const validScore = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value) && value >= 0;

function compare(model: number, reference: number): ErrorComparison {
  return {
    modelMaePp: model,
    referenceMaePp: reference,
    absoluteReductionPp: reference - model,
    relativeReductionPct: reference > 0 ? 100 * (reference - model) / reference : null,
  };
}

function sameParameters(left: unknown, right: unknown): boolean {
  if (!left || !right || typeof left !== 'object' || typeof right !== 'object' || Array.isArray(left) || Array.isArray(right)) return false;
  const a = left as Record<string, unknown>, b = right as Record<string, unknown>;
  const keys = Object.keys(a);
  return keys.length > 0 && keys.length === Object.keys(b).length && keys.every(key => Object.hasOwn(b, key) && Object.is(a[key], b[key]));
}

/** Describe the saved evaluation without changing forecasts or selecting on test scores. */
export function getForecastEvidence(category: CategoryForecast, exploratory = false): ForecastEvidence {
  const months = category.test_predictions.map(item => item.target_month.slice(0, 7)).sort();
  const count = category.test_metrics.n;
  const result: ForecastEvidence = {
    testMonths: count,
    startMonth: months[0] ?? null,
    endMonth: months.at(-1) ?? null,
    scope: exploratory ? 'exploratory' : 'original',
    noChange: null,
    seasonal: null,
    commodity: null,
    commodityUnavailableReason: 'A matching history-only comparison is unavailable.',
  };
  const validMonths = months.every(value => /^\d{4}-(0[1-9]|1[0-2])$/.test(value));
  if (!Number.isInteger(count) || count <= 0 || count !== months.length || new Set(months).size !== count || !validMonths || !validScore(category.test_metrics.mae_pp)) {
    result.commodityUnavailableReason = 'The saved evaluation has incomplete month or error coverage.';
    return result;
  }
  const modelMae = category.test_metrics.mae_pp;
  const uniqueRow = (matches: (row: CategoryModelScore) => boolean): CategoryModelScore | null => {
    const rows = category.leaderboard.filter(row => matches(row) && row.test_n === count && validScore(row.test_mae_pp));
    return rows.length === 1 ? rows[0] : null;
  };
  const noChange = uniqueRow(row => ['no_change', 'zero', 'baseline_zero'].includes(row.model_id));
  const seasonal = uniqueRow(row => ['seasonal', 'baseline_seasonal'].includes(row.model_id));
  if (noChange) result.noChange = compare(modelMae, noChange.test_mae_pp!);
  if (seasonal) result.seasonal = compare(modelMae, seasonal.test_mae_pp!);

  if (exploratory) {
    result.commodityUnavailableReason = 'Rolling strategies do not isolate the contribution of commodity inputs.';
    return result;
  }
  if (!category.selected_feature_group.includes('commodit')) {
    result.commodityUnavailableReason = 'Price history won pre-test selection; no commodity-gain claim.';
    return result;
  }
  const selected = uniqueRow(row => row.model_id === category.selected_model_id && row.feature_group === category.selected_feature_group);
  const history = uniqueRow(row => row.model_id === category.selected_model_id && row.feature_group === 'history_only');
  if (selected && history && Math.abs(selected.test_mae_pp! - modelMae) < 1e-10 && sameParameters(selected.hyperparameters, history.hyperparameters)) {
    result.commodity = compare(modelMae, history.test_mae_pp!);
    result.commodityUnavailableReason = '';
  }
  return result;
}
