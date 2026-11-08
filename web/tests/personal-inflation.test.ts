import assert from 'node:assert/strict';
import test from 'node:test';
import { categoriseDemoTransaction, parseBankCsv, personalInflation, StatementError } from '../src/personalInflation.ts';
import type { InflationBundle } from '../src/personalInflation.ts';
const bundle: InflationBundle = { schema_version: 1, mode: 'synthetic_demo', categories: [
  { id: 'chocolate', name: 'Chocolate', coicop: '01.1.8.3', series_id: 'L79X', data_kind: 'observed_ons', values: { '2025-09': 100, '2026-09': 110 } },
  { id: 'crisps', name: 'Crisps', coicop: '01.1.7.5', series_id: 'L79R', data_kind: 'observed_ons', values: { '2025-09': 100, '2026-09': 120 } },
], benchmark: { id: 'demo_snack_basket', name: 'Synthetic 50/50 snack benchmark', synthetic: true, base_month: '2025-09', reference_weights: { chocolate: .5, crisps: .5 }, values: { '2025-09': 100, '2026-09': 115 } }, headline: null, cpih: null, samples: [], limitations: [] };
const csv = 'Date,Description,Amount\n01/09/2025,DEMO CHOCOLATE SHOP,-75.00\n30/09/2026,DEMO CRISPS SHOP,-25.00\n';
test('hand-computed basket returns 12.5% inflation and weights sum to one', () => {
  const result = personalInflation(csv, bundle, { syntheticInput: true });
  assert.ok(Math.abs(result.personal_rate - .125) < 1e-12);
  assert.ok(Math.abs(result.categories.reduce((sum, item) => sum + item.weight, 0) - 1) < 1e-12);
  assert.equal(result.input_is_synthetic, true); assert.equal(result.headline_rate, null);
  assert.equal(result.start_month, '2025-09'); assert.equal(result.end_month, '2026-09');
});
test('single category equals its rate and synthetic reference weights reproduce benchmark', () => {
  assert.ok(Math.abs(personalInflation('Date,Description,Amount\n01/01/2026,DEMO CRISPS CLUB,-20', bundle).personal_rate - .2) < 1e-12);
  const equal = personalInflation(csv.replace('-75.00', '-25.00'), bundle);
  assert.ok(Math.abs(equal.personal_rate - equal.benchmark_rate) < 1e-12);
});
test('generic groceries and brand names remain other', () => {
  for (const name of ['TESCO', 'Snickers', 'Rent', 'DEMO CHOCOLATE SHOPPING']) assert.equal(categoriseDemoTransaction(name), 'other');
  const result = personalInflation('Date,Description,Amount\n01/01/2026,TESCO,-100', bundle);
  assert.equal(result.other_share, 1); assert.ok(result.warnings.some(item => item.includes('unreliable')));
});
test('UK money and debit/credit columns work; non-spending is excluded', () => {
  const text = 'Date,Description,Money Out,Money In\n01/01/2026,DEMO CHOCOLATE SHOP,"Â£1,234.50",\n02/01/2026,SALARY,,2000\n03/01/2026,OWN ACCOUNT TRANSFER,500,\n04/01/2026,SAVINGS MOVE,50,\n05/01/2026,ATM CASH WITHDRAWAL,100,\n06/01/2026,REFUND,10,\n';
  const result = personalInflation(text, bundle);
  assert.equal(result.total_spending_gbp, 1234.5);
  for (const key of ['income', 'own_transfer', 'savings', 'cash_withdrawal', 'refund'] as const) assert.equal(result.exclusions[key].count, 1);
  assert.equal(result.categories.length, 1);
});
test('rent bank transfer is retained and negative DR amounts keep their sign', () => {
  const parsed = parseBankCsv('Date,Description,Amount,Type\n01/01/2026,BANK TRANSFER RENT,50,DEBIT\n02/01/2026,DEMO CRISPS SHOP,-1.00 DR,\n03/01/2026,SAVINGS SUPERMARKET,-2.00,');
  assert.deepEqual(parsed.map(item => item.spending_pence), [5000, 100, 200]);
  assert.ok(parsed.every(item => !item.exclusion));
});
test('recurring changes are separate and do not affect the inflation formula', () => {
  let text = 'Date,Description,Amount\n';
  for (let i = 0; i < 13; i++) { const date = new Date(Date.UTC(2025, 8 + i, 15)); text += `${date.toISOString().slice(0, 10)},DIRECT DEBIT DEMO SPOTIFY REF${10000 + i},-${i === 12 ? '12' : '10'}\n`; }
  const result = personalInflation(text, bundle); assert.equal(result.observed_price_changes.length, 1);
  assert.equal(result.observed_price_changes[0].merchant, 'DEMO SPOTIFY');
  assert.ok(Math.abs(result.observed_price_changes[0].change - .2) < 1e-12);
  assert.ok(Math.abs(result.personal_rate - .15) < 1e-12);
  assert.ok(!JSON.stringify(result).includes('REF10000'));
});
test('short periods and non-overlap warn; missing history fails', () => {
  const result = personalInflation('Date,Description,Amount\n31/01/2030,DEMO CRISPS SHOP,-1\n01/03/2030,DEMO CRISPS SHOP,-1', bundle);
  assert.ok(result.warnings.some(item => item.includes('less than three'))); assert.ok(result.warnings.some(item => item.includes('do not overlap')));
  assert.throws(() => personalInflation(csv, { ...bundle, categories: bundle.categories.map(item => ({ ...item, values: { '2026-09': 100 } })) }), StatementError);
});
test('malformed, empty, ambiguous and invalid inputs return readable errors', () => {
  for (const text of ['', 'Date,Description,Amount\n', 'Date,Description,Amount\n01/01/2026,TESCO,12', 'Date,Description,Amount\n32/01/2026,TESCO,-12', 'Date,Description,Amount\n01/01/2026,TESCO,-12.345', 'Date,Description,Amount\n01/01/2026,"Unclosed,-12']) assert.throws(() => personalInflation(text, bundle), StatementError);
});

test('timestamps reject invalid hours, minutes and seconds', () => {
  for (const date of ['2026-09-01 99:99:99', '2026-09-01T24:00:00', '2026-09-01 12:60:00', '2026-09-01T12:00:60']) assert.throws(() => parseBankCsv(`Date,Description,Amount\n${date},DEMO CRISPS SHOP,-1`), StatementError);
  assert.equal(parseBankCsv('Date,Description,Amount\n2026-09-01T23:59:59,DEMO CRISPS SHOP,-1')[0].date, '2026-09-01');
});

test('matching published headline reference supplies CPI/CPIH and other fallback with source provenance', () => {
  const reference = { start_month: '2025-09', end_month: '2026-09', cpi_rate: .035, cpih_rate: .036, release_date: '2026-10-21', source_url: 'https://www.ons.gov.uk/economy/inflationandpriceindices/bulletins/consumerpriceinflation/september2026', source_title: 'Consumer price inflation, UK: September 2026' };
  const result = personalInflation('Date,Description,Amount\n01/01/2026,TESCO,-100', { ...bundle, headline_reference: reference });
  assert.equal(result.personal_rate, .035); assert.equal(result.headline_rate, .035); assert.equal(result.cpih_rate, .036);
  assert.deepEqual(result.headline_reference, reference); assert.equal(result.categories[0].rate, .035);
  assert.ok(Math.abs(result.benchmark_rate - .15) < 1e-12);
  assert.match(result.summary, /3\.5% official headline CPI/); assert.match(result.warnings.join(' '), /aggregate fallback/);
  assert.ok(!result.warnings.some(warning => warning.includes('official all-items CPI and CPIH are absent')));
});

test('out-of-period or invalid fixed headline reference is ignored instead of applied to another year', () => {
  const reference = { start_month: '2024-09', end_month: '2025-09', cpi_rate: .035, cpih_rate: .036, release_date: '2026-10-21', source_url: 'https://www.ons.gov.uk/', source_title: 'Published reference' };
  for (const invalid of [reference, { ...reference, start_month: '2025-09', end_month: '2026-09', cpi_rate: Number.NaN }, { ...reference, start_month: '2025-09', end_month: '2026-09', cpih_rate: -1 }]) {
    const result = personalInflation('Date,Description,Amount\n01/01/2026,TESCO,-100', { ...bundle, headline_reference: invalid });
    assert.equal(result.headline_rate, null); assert.equal(result.cpih_rate, null); assert.equal(result.headline_reference, null);
    assert.ok(Math.abs(result.personal_rate - .15) < 1e-12); assert.ok(result.warnings.some(warning => warning.includes('was ignored')));
  }
});
