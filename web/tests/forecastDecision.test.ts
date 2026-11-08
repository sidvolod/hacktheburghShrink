import assert from 'node:assert/strict';
import test from 'node:test';
import { conservativeDecision } from '../src/forecastDecision.ts';
const evidence = { forecastPct: 2.3167, modelMaePp: 1.5747, baselineMaePp: 1.977, modelMonths: 33, baselineMonths: 33 };
test('conservative rule retains a better-scoring model without changing its forecast', () => {
  assert.deepEqual(conservativeDecision(evidence), {status:'model',outputPct:2.3167});
  assert.equal(evidence.forecastPct,2.3167);
});
test('conservative rule falls back on a worse or tied score, independently of forecast direction', () => {
  for (const modelMaePp of [1.35,1.26]) {
    assert.deepEqual(conservativeDecision({...evidence,modelMaePp,baselineMaePp:1.26,forecastPct:-.48}), {status:'baseline',outputPct:0});
  }
});
test('missing, nonfinite or mismatched evidence cannot produce a decision', () => {
  for (const patch of [{baselineMaePp:NaN},{forecastPct:Infinity},{modelMonths:0},{baselineMonths:32},{modelMaePp:-1}]) {
    assert.deepEqual(conservativeDecision({...evidence,...patch}), {status:'unavailable',outputPct:null});
  }
});
