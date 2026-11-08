import assert from 'node:assert/strict';
import { unitPrice, unitPriceChange, massChange } from './src/math.ts';

assert.equal(unitPrice(6, 600), 1);
assert.ok(Math.abs(unitPrice(7, 550) - 1.2727272727) < 1e-9);
assert.ok(Math.abs(unitPriceChange(1, 100, 1, 90) - 1 / 9) < 1e-12);
assert.ok(Math.abs(massChange(100, 90) + .1) < 1e-12);
assert.equal(unitPrice(null, 100), null);
assert.equal(unitPrice(1, 0), null);
assert.equal(unitPrice(Infinity, 100), null);
assert.equal(unitPriceChange(1, 100, null, 90), null);
assert.ok(unitPriceChange(2, 100, 1, 100) < 0);
console.log('9 browser calculation checks passed. Synthetic inputs are test fixtures only.');
