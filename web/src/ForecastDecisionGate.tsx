import type { CategoryForecast } from './types';
import { conservativeDecision } from './forecastDecision';
import './forecast-decision.css';

const percent = (value: number) => `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
const error = (value: unknown) => typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(2)} pp` : 'Unavailable';

export function ForecastDecisionGate({ category }: { category: CategoryForecast }) {
  const baseline = category.baseline_metrics;
  const decision = conservativeDecision({ forecastPct: category.forecast.change_pct,
    modelMaePp: category.test_metrics.mae_pp, baselineMaePp: typeof baseline.mae_pp === 'number' ? baseline.mae_pp : NaN,
    modelMonths: category.test_metrics.n, baselineMonths: typeof baseline.n === 'number' ? baseline.n : NaN });
  const label = decision.status === 'model' ? 'Model retained' : decision.status === 'baseline' ? 'No-change fallback' : 'Evidence unavailable';
  return <section className={`forecast-decision ${decision.status}`} aria-label="Conservative forecast decision">
    <div className="forecast-decision-copy"><span className="eyebrow">An explicit decision rule</span><h2>Use the signal.<br />Know when to fall back.</h2>
      <span className="forecast-decision-badge">{label}</span>
      <p className="forecast-decision-evidence">Reported test error: model <strong>{error(category.test_metrics.mae_pp)}</strong> · no change <strong>{error(baseline.mae_pp)}</strong>.</p>
      <p>{decision.status === 'model' ? 'The model had lower average error than no change in this evaluation, so this rule retains its estimate.' : decision.status === 'baseline' ? 'The model did not improve on no change in this evaluation, so this rule uses the zero-change reference.' : 'Matching model and baseline scores are needed before this rule can choose an output.'}</p>
    </div>
    <div className="forecast-decision-output"><span className="eyebrow">Conservative output</span><strong>{decision.outputPct == null ? '—' : percent(decision.outputPct)}</strong><span>{decision.status === 'model' ? 'Uses the model estimate' : decision.status === 'baseline' ? 'Uses the no-change reference' : 'No output'}</span><p>The raw model estimate is {percent(category.forecast.change_pct)}. Category index change; no individual product decision is implied.</p></div>
    <p className="forecast-decision-note">Rule added after reviewing these test results; future performance is untested. This is an error comparison, not a confidence probability or a detected market regime. Historical forecasts and scores remain unchanged.</p>
  </section>;
}
