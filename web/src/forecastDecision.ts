/** A prospective demonstration rule, added after inspecting the saved evaluation. */
export interface DecisionEvidence {
  forecastPct: number;
  modelMaePp: number;
  baselineMaePp: number;
  modelMonths: number;
  baselineMonths: number;
}
export interface ForecastDecision {
  status: 'model' | 'baseline' | 'unavailable';
  outputPct: number | null;
}
export function conservativeDecision(evidence: DecisionEvidence): ForecastDecision {
  const { forecastPct, modelMaePp, baselineMaePp, modelMonths, baselineMonths } = evidence;
  if (!Number.isFinite(forecastPct) || !Number.isFinite(modelMaePp) || !Number.isFinite(baselineMaePp)
    || modelMaePp < 0 || baselineMaePp < 0 || !Number.isInteger(modelMonths) || modelMonths <= 0
    || modelMonths !== baselineMonths) return { status: 'unavailable', outputPct: null };
  return modelMaePp < baselineMaePp ? { status: 'model', outputPct: forecastPct } : { status: 'baseline', outputPct: 0 };
}
