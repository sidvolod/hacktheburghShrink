import assert from 'node:assert/strict';
import test from 'node:test';
import { readFileSync } from 'node:fs';
import { getForecastEvidence } from '../src/forecastEvidence.ts';
import type { CategoryForecast, CategoryForecastReport } from '../src/types.ts';

const original: CategoryForecastReport = JSON.parse(readFileSync(new URL('../../data/app-public/data/category-forecast.json', import.meta.url), 'utf8'));
const tuned: CategoryForecastReport = JSON.parse(readFileSync(new URL('../../data/app-public/data/category-tuning.json', import.meta.url), 'utf8'));
const chocolate = () => structuredClone(original.categories.find(item => item.category_id === 'chocolate')!);
const close = (actual: number | null, expected: number, tolerance = 1e-9) => assert.ok(actual != null && Math.abs(actual - expected) < tolerance);

test('saved chocolate evaluation distinguishes total gain from incremental commodity gain', () => {
  const evidence = getForecastEvidence(chocolate());
  assert.equal(evidence.testMonths, 33);
  assert.equal(evidence.startMonth, '2024-01');
  assert.equal(evidence.endMonth, '2026-09');
  close(evidence.noChange!.relativeReductionPct, 20.3476, .0001);
  close(evidence.seasonal!.relativeReductionPct, 2.5427, .0001);
  close(evidence.commodity!.relativeReductionPct, 1.2559, .0001);
  close(evidence.commodity!.absoluteReductionPp, .020028284434025156);
});

test('a worse crisps result stays negative and never claims selected commodity inputs', () => {
  const evidence = getForecastEvidence(original.categories.find(item => item.category_id === 'crisps')!);
  assert.ok(evidence.noChange!.absoluteReductionPp < 0);
  close(evidence.noChange!.relativeReductionPct, -6.8962, .0001);
  assert.equal(evidence.commodity, null);
  assert.match(evidence.commodityUnavailableReason, /Price history won/);
});

test('rolling strategies never inherit a matched-family commodity claim', () => {
  for (const category of tuned.categories) {
    const evidence = getForecastEvidence(category, true);
    assert.equal(evidence.scope, 'exploratory');
    assert.equal(evidence.commodity, null);
    assert.match(evidence.commodityUnavailableReason, /do not isolate/);
    assert.ok(evidence.noChange);
  }
});

test('mismatched reference counts and ambiguous rows do not produce gains', () => {
  const category = chocolate();
  category.leaderboard.find(row => row.model_id === 'no_change')!.test_n = 12;
  category.leaderboard.push(structuredClone(category.leaderboard.find(row => row.model_id === 'seasonal')!));
  const evidence = getForecastEvidence(category);
  assert.equal(evidence.noChange, null);
  assert.equal(evidence.seasonal, null);
});

test('commodity comparisons require the same parameters and valid reference scores', () => {
  const category = chocolate();
  const history = category.leaderboard.find(row => row.model_id === category.selected_model_id && row.feature_group === 'history_only')!;
  history.hyperparameters = { max_iter: 999 };
  assert.equal(getForecastEvidence(category).commodity, null);
  history.hyperparameters = undefined;
  assert.equal(getForecastEvidence(category).commodity, null);
  category.leaderboard.find(row => row.model_id === 'no_change')!.test_mae_pp = NaN;
  assert.equal(getForecastEvidence(category).noChange, null);
});

test('a zero-error reference never produces an infinite percentage improvement', () => {
  const category = chocolate();
  category.leaderboard.find(row => row.model_id === 'no_change')!.test_mae_pp = 0;
  const evidence = getForecastEvidence(category);
  assert.equal(evidence.noChange!.relativeReductionPct, null);
  assert.ok(evidence.noChange!.absoluteReductionPp < 0);
});

test('missing or duplicate outcome months make comparisons unavailable', () => {
  const category = chocolate();
  category.test_predictions[1].target_month = category.test_predictions[0].target_month;
  const evidence = getForecastEvidence(category);
  assert.equal(evidence.noChange, null);
  assert.equal(evidence.seasonal, null);
  assert.equal(evidence.commodity, null);
});

test('evidence calculation leaves frozen forecasts and scores unchanged', () => {
  const category: CategoryForecast = chocolate();
  const before = JSON.stringify(category);
  getForecastEvidence(category);
  getForecastEvidence(category, true);
  assert.equal(JSON.stringify(category), before);
});
