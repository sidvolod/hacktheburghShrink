import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { optimizeWholePacks } from '../src/wholePackMath.ts';

type Group = Parameters<typeof optimizeWholePacks>[0];
const item = (id: string, mass: number, price: number) => ({ id, name: `Pack ${id}`, mass_g: mass, price_gbp: price, price_per_100g_gbp: price * 100 / mass, price_basis: 'recorded_listing_price' });
const group = (items: Group['items'], retailer = 'Example retailer', date = '2024-04-13'): Group => ({ id: `${retailer}:${date}`, group: 'Chocolate', retailer, date, source_url: 'https://example.test/source', items });
function ready(snapshot: Group, target: number) {
  const result = optimizeWholePacks(snapshot, target);
  assert.equal(result.status, 'ready');
  if (result.status !== 'ready') throw new Error(result.reason);
  return result;
}

test('whole-pack combination beats every repeated-single-product option', () => {
  const plan = ready(group([item('a', 180, 1.60), item('b', 120, 1.10)]), 300);
  assert.equal(plan.totalPricePence, 270);
  assert.equal(plan.totalGrams, 300);
  assert.equal(plan.excessGrams, 0);
  assert.deepEqual(plan.lines.map(line => [line.item.id, line.count]), [['a', 1], ['b', 1]]);
  assert.ok(plan.lines.every(line => Number.isInteger(line.count)));
});

test('checkout cost comes before excess; equal-cost baskets prefer less excess', () => {
  const cheapest = ready(group([item('a', 310, 1), item('b', 300, 1.01)]), 300);
  assert.equal(cheapest.totalGrams, 310);
  assert.equal(cheapest.totalPricePence, 100);
  const tie = ready(group([item('a', 310, 1), item('b', 300, 1)]), 300);
  assert.equal(tie.totalGrams, 300);
  assert.equal(tie.lines[0].item.id, 'b');
});

test('equal price and weight prefer fewer packs, with stable identity ties', () => {
  const input = group([item('a', 150, .5), item('b', 300, 1), item('c', 300, 1)]);
  const plan = ready(input, 300);
  assert.equal(plan.packCount, 1);
  assert.equal(plan.lines[0].item.id, 'b');
  assert.deepEqual(ready({ ...input, items: [...input.items].reverse() }, 300).lines, plan.lines);
});

test('fractional grams remain exact, including exported multipack floating artifacts', () => {
  const plan = ready(group([item('a', 186.29999999999998, 1.35), item('b', 319.5, 3.4)]), 300);
  assert.equal(plan.totalGrams, 372.6);
  assert.equal(plan.excessGrams, 72.6);
  assert.equal(plan.totalPricePence, 270);
  assert.equal(plan.lines[0].packMassGrams, 186.3);
  const precise = ready(group([item('a', 100.125, .5)]), 300);
  assert.equal(precise.totalGrams, 300.375);
  assert.equal(precise.excessGrams, .375);
  assert.equal(ready(group([item('a', 300, 2.9)]), 300).totalPricePence, 290);
});

test('each call is isolated to its named retailer and date snapshot', () => {
  const first = group([item('a', 300, 3)], 'Tesco', '2024-04-13');
  const second = group([item('b', 300, .5)], 'Other retailer', '2024-04-12');
  const cheap = ready(second, 300);
  const plan = ready(first, 300);
  assert.equal(cheap.totalPricePence, 50);
  assert.equal(plan.totalPricePence, 300);
  assert.equal(plan.retailer, 'Tesco');
  assert.equal(plan.date, '2024-04-13');
  assert.deepEqual(plan.lines.map(line => line.item.id), ['a']);
  assert.deepEqual(first.items, [item('a', 300, 3)]);
});

test('invalid inputs and unsupported precision fail explicitly without silently dropping packs', () => {
  for (const price of [0, -.1, NaN, Infinity, .004, 1.005, .014]) assert.equal(optimizeWholePacks(group([item('ok', 300, 1), item('bad', 100, price)]), 300).status, 'unavailable');
  for (const mass of [0, -1, NaN, Infinity, 100.0001]) assert.equal(optimizeWholePacks(group([item('bad', mass, 1)]), 300).status, 'unavailable');
  for (const target of [0, 49, 51, 1050, NaN, Infinity]) assert.equal(optimizeWholePacks(group([item('a', 300, 1)]), target).status, 'unavailable');
  assert.equal(optimizeWholePacks(group([]), 300).status, 'unavailable');
  assert.equal(optimizeWholePacks(group([item('a', 300, 1), item('a', 300, 1)]), 300).status, 'unavailable');
  assert.equal(optimizeWholePacks({ ...group([item('a', 300, 1)]), retailer: '' }, 300).status, 'unavailable');
  assert.equal(optimizeWholePacks({ ...group([item('a', 300, 1)]), date: '2024-99-99' }, 300).status, 'unavailable');
  assert.equal(optimizeWholePacks({ ...group([item('a', 300, 1)]), date: '2024-02-30' }, 300).status, 'unavailable');
  const excessive = optimizeWholePacks(group([item('a', .001, 1), item('b', 999.999, 1)]), 1000);
  assert.equal(excessive.status, 'unavailable');
  if (excessive.status === 'unavailable') assert.match(excessive.reason, /No approximate basket/);
});

function exhaustive(snapshot: Group, target: number) {
  let best = { cost: Infinity, mass: Infinity, packs: Infinity };
  const maxCount = Math.ceil(target / Math.min(...snapshot.items.map(value => value.mass_g)));
  function visit(index: number, mass: number, cost: number, packs: number) {
    if (index === snapshot.items.length) {
      if (mass >= target && (cost < best.cost || (cost === best.cost && (mass < best.mass || (mass === best.mass && packs < best.packs))))) best = { cost, mass, packs };
      return;
    }
    const pack = snapshot.items[index];
    for (let n = 0; n <= maxCount; n += 1) visit(index + 1, mass + n * pack.mass_g, cost + n * Math.round(pack.price_gbp * 100), packs + n);
  }
  visit(0, 0, 0, 0);
  return best;
}

test('exact DP agrees with independent exhaustive enumeration across 80 varied small problems', () => {
  for (let seed = 0; seed < 20; seed += 1) {
    const input = group([
      item('a', (seed % 5 + 1) * 10, (seed % 7 + 1) / 100),
      item('b', ((seed * 3) % 7 + 1) * 10, ((seed * 5) % 11 + 1) / 100),
      item('c', ((seed * 7) % 9 + 1) * 10, ((seed * 2) % 13 + 1) / 100),
    ]);
    for (const target of [50, 100, 150, 200]) {
      const expected = exhaustive(input, target);
      const plan = ready(input, target);
      assert.deepEqual({ cost: plan.totalPricePence, mass: plan.totalGrams, packs: plan.packCount }, expected, `seed=${seed}, target=${target}`);
      assert.equal(plan.lines.reduce((sum, line) => sum + line.totalPricePence, 0), plan.totalPricePence);
      assert.equal(plan.lines.reduce((sum, line) => sum + line.count, 0), plan.packCount);
    }
  }
});

test('every real exported snapshot supports every slider target with audited exact reconstruction', () => {
  const input = process.env.WHOLE_PACK_DEMO_PATH ?? new URL('../../data/app-public/data/demo.json', import.meta.url);
  const data = JSON.parse(readFileSync(input, 'utf8'));
  assert.equal(data.comparisons.length, 4);
  for (const snapshot of data.comparisons as Group[]) {
    for (let target = 50; target <= 1000; target += 50) {
      const plan = ready(snapshot, target);
      assert.ok(plan.totalGrams >= target);
      assert.ok(plan.totalGrams < target + Math.max(...snapshot.items.map(value => value.mass_g)) + 1e-9);
      assert.equal(plan.totalPricePence, plan.lines.reduce((total, line) => total + line.count * line.packPricePence, 0));
      assert.equal(Math.round(plan.totalGrams * 1000), plan.lines.reduce((total, line) => total + line.count * Math.round(line.packMassGrams * 1000), 0));
      assert.ok(plan.lines.every(line => snapshot.items.some(value => value.id === line.item.id)));
    }
  }
});
