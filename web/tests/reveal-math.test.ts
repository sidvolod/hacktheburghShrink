import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { inflationReceipt } from '../src/revealMath.ts';
import type { SnackCase } from '../src/types.ts';

const cases: SnackCase[] = JSON.parse(readFileSync(new URL('../../data/app-public/data/demo.json', import.meta.url), 'utf8')).cases;
const revels = cases.find(snack => snack.id === 'revels-uk-pouch-2025')!;
const close = (actual: number, expected: number) => assert.ok(Math.abs(actual - expected) < 1e-12, `${actual} != ${expected}`);

test('Revels receipt preserves exact arithmetic, then displays 33.0%, not 33.1%', () => {
  const receipt = inflationReceipt(revels)!;
  close(receipt.constantWeightCost, 3.3 * 205 / 185);
  close(receipt.missingQuantityCost, 3.3 * 20 / 185);
  close(receipt.effectiveChangeFraction, 0.32972972972972975);
  close(receipt.stickerChangeFraction, .2);
  close(receipt.shrinkContributionFraction, 0.12972972972972975);
  assert.equal((receipt.effectiveChangeFraction * 100).toFixed(1), '33.0');
  assert.equal(receipt.constantWeightCost.toFixed(2), '3.66');
  assert.equal(receipt.missingQuantityCost.toFixed(2), '0.36');
  assert.equal(receipt.removedGrams, 20);
});

test('every eligible case reconciles shelf-price and missing-quantity contributions without rounding', () => {
  let count = 0;
  for (const snack of cases) {
    const receipt = inflationReceipt(snack);
    if (!receipt) continue;
    count++;
    close(receipt.stickerChangeFraction + receipt.shrinkContributionFraction, receipt.effectiveChangeFraction);
    close(receipt.newPrice + receipt.missingQuantityCost, receipt.constantWeightCost);
    close(receipt.constantWeightCost / receipt.oldMass, receipt.newPrice / receipt.newMass);
    close(receipt.effectiveChangeFraction, snack.unit_price_change_fraction!);
  }
  assert.ok(count >= 5);
});

test('a shelf-price fall remains signed and can offset the missing grams', () => {
  const receipt = inflationReceipt({ ...revels,
    old: { ...revels.old, mass_g: 100, price_gbp: 2 },
    new: { ...revels.new, mass_g: 90, price_gbp: 1.5 },
    unit_price_change_fraction: -1 / 6,
  })!;
  close(receipt.stickerChangeFraction, -.25);
  close(receipt.shrinkContributionFraction, 1 / 12);
  close(receipt.effectiveChangeFraction, -1 / 6);
});

test('unknown, incomparable and invalid evidence never prints an invented receipt', () => {
  assert.equal(inflationReceipt({ ...revels, unit_price_change_fraction: null }), null);
  assert.equal(inflationReceipt({ ...revels, old: { ...revels.old, price_gbp: null } }), null);
  assert.equal(inflationReceipt({ ...revels, new: { ...revels.new, price_gbp: 0 } }), null);
  assert.equal(inflationReceipt({ ...revels, new: { ...revels.new, price_basis: 'different_basis' } }), null);
  assert.equal(inflationReceipt({ ...revels, new: { ...revels.new, mass_g: Infinity } }), null);
  assert.equal(inflationReceipt({ ...revels, new: { ...revels.new, mass_g: revels.old.mass_g } }), null);
  assert.equal(inflationReceipt({ ...revels, new: { ...revels.new, mass_g: revels.old.mass_g + 10 } }), null);
});
