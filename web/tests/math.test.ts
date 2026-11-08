import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { comparableUnitPriceChange, isReviewedReplacementPair, massChange, observationIndex, unitPrice, unitPriceChange } from '../src/math.ts';

const close = (actual: number | null, expected: number) => {
  assert.notEqual(actual, null);
  assert.ok(Math.abs(actual! - expected) < 1e-12, `${actual} != ${expected}`);
};

test('10% less product at the same price costs 11.11% more per gram', () => {
  close(massChange(100, 90), -.1);
  close(unitPriceChange(1, 100, 1, 90), 1 / 9);
});

test('a lower shelf price can still mean a higher unit price', () => {
  close(unitPrice(1.10, 500), .22);
  close(unitPrice(1, 400), .25);
  close(unitPriceChange(1.10, 500, 1, 400), 3 / 22);
});

test('unknown and nonfinite inputs never become invented zero prices', () => {
  for (const price of [null, 0, -1, Infinity, NaN]) assert.equal(unitPrice(price, 100), null);
  for (const mass of [null, 0, -1, Infinity, NaN]) assert.equal(unitPrice(1, mass), null);
  assert.equal(unitPriceChange(null, 121, null, 103), null);
  assert.equal(massChange(0, 90), null);
});

test('every exported real case agrees with the UI calculations', () => {
  const data = JSON.parse(readFileSync(new URL('../../data/app-public/data/demo.json', import.meta.url), 'utf8'));
  assert.ok(data.cases.length >= 5);
  for (const item of data.cases) {
    for (const version of [item.old, item.new]) {
      const computed = unitPrice(version.price_gbp, version.mass_g);
      if (version.price_per_100g_gbp === null) assert.equal(computed, null);
      else close(computed, version.price_per_100g_gbp);
    }
    const computed = comparableUnitPriceChange(item.old, item.new, item.unit_price_change_fraction);
    if (item.unit_price_change_fraction === null) assert.equal(computed, null);
    else close(computed, item.unit_price_change_fraction);
  }
  for (const group of data.comparisons) {
    assert.match(group.date, /^\d{4}-\d{2}-\d{2}$/);
    assert.ok(group.retailer);
    for (const item of group.items) close(unitPrice(item.price_gbp, item.mass_g), item.price_per_100g_gbp);
  }
  assert.equal(data.evaluation.status, 'unavailable');
  assert.equal(data.evaluation.forecast, null);
});

test('switching an actual longer exported history to a shorter one resolves a valid observation', () => {
  const data = JSON.parse(readFileSync(new URL('../../data/app-public/data/demo.json', import.meta.url), 'utf8'));
  const histories = [...data.histories].sort((a, b) => b.points.length - a.points.length);
  const longer = histories[0];
  const shorter = histories.at(-1)!;
  assert.ok(longer.points.length > shorter.points.length, 'Fixture must exercise different actual export lengths.');
  const previousIndex = longer.points.length - 1;
  const safeIndex = observationIndex(previousIndex, shorter.points.length);
  assert.equal(safeIndex, shorter.points.length - 1);
  assert.ok(shorter.points[safeIndex]);
  assert.match(shorter.points[safeIndex].date, /^\d{4}-\d{2}-\d{2}$/);
  assert.equal(observationIndex(null, shorter.points.length), safeIndex);
  assert.equal(observationIndex(-5, shorter.points.length), 0);
  assert.equal(observationIndex(NaN, shorter.points.length), safeIndex);
  assert.throws(() => observationIndex(null, 0), RangeError);
});

test('a unit-price change requires comparable known bases and backend approval', () => {
  const before = { price_gbp: 1, mass_g: 100, price_basis: 'reported_shelf_price_same_retailer' };
  const after = { price_gbp: 1, mass_g: 90, price_basis: 'reported_shelf_price_same_retailer' };
  close(comparableUnitPriceChange(before, after, 1 / 9), 1 / 9);
  assert.equal(comparableUnitPriceChange(before, { ...after, price_basis: 'recommended_retail_price' }, 1 / 9), null);
  assert.equal(comparableUnitPriceChange({ ...before, price_basis: 'not_reported' }, { ...after, price_basis: 'not_reported' }, 1 / 9), null);
  assert.equal(comparableUnitPriceChange(before, after, null), null);
  assert.equal(comparableUnitPriceChange(before, after, undefined), null);
  assert.equal(comparableUnitPriceChange(before, after, NaN), null);
});

test('two candidate barcodes alone never become a reviewed replacement link', () => {
  const pair = { old_barcode: '8445290146434', new_barcode: '8445291609181' };
  assert.equal(isReviewedReplacementPair({ ...pair, status: 'needs_evidence_review' }), false);
  assert.equal(isReviewedReplacementPair({ ...pair, status: 'unknown' }), false);
  assert.equal(isReviewedReplacementPair({ ...pair, status: 'manually_supported_replacement_pair' }), true);
  assert.equal(isReviewedReplacementPair({ ...pair, status: 'reviewed_reported_pair' }), true);
  assert.equal(isReviewedReplacementPair({ ...pair, new_barcode: null, status: 'manually_supported_replacement_pair' }), false);
});
