import type { ComparisonGroup, ComparisonItem } from './types';

export const MIN_TARGET_GRAMS = 50;
export const MAX_TARGET_GRAMS = 1000;
const MILLIGRAMS_PER_GRAM = 1000;
const MAX_STATES = 250_000;

export interface WholePackLine {
  item: ComparisonItem;
  count: number;
  packMassGrams: number;
  packPricePence: number;
  totalPricePence: number;
}

export interface WholePackPlan {
  status: 'ready';
  retailer: string;
  date: string;
  lines: WholePackLine[];
  targetGrams: number;
  totalGrams: number;
  excessGrams: number;
  totalPricePence: number;
  packCount: number;
  pricePer100gPence: number;
  consideredProducts: number;
  massQuantumMilligrams: number;
}

export type WholePackResult = WholePackPlan | { status: 'unavailable'; reason: string };

function integerMilligrams(grams: number): number | null {
  if (!Number.isFinite(grams) || grams <= 0) return null;
  const scaled = grams * MILLIGRAMS_PER_GRAM;
  const integer = Math.round(scaled);
  // Accept only binary floating-point noise around a genuine milligram value.
  // This recovers e.g. the exported 9 × 20.7g = 186.29999999999998g,
  // without rounding a genuinely finer declared quantity.
  if (!Number.isSafeInteger(integer) || Math.abs(scaled - integer) > 0.000001) return null;
  return integer > 0 ? integer : null;
}

function integerPence(pounds: number): number | null {
  if (!Number.isFinite(pounds) || pounds <= 0) return null;
  const scaled = pounds * 100;
  const pence = Math.round(scaled);
  return Number.isSafeInteger(pence) && pence > 0 && Math.abs(scaled - pence) <= 0.000001 ? pence : null;
}

function validSnapshotDate(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T12:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

function gcd(a: number, b: number): number {
  while (b) [a, b] = [b, a % b];
  return a;
}

/** Minimum checkout cost for one given historical retailer/category/date snapshot.
 * Ties: less excess mass, then fewer packs. Equal remaining ties are deterministic
 * by item ID/name. Prices are fixed per pack; quantity discounts are not inferred.
 */
export function optimizeWholePacks(group: ComparisonGroup, targetGrams: number): WholePackResult {
  const unavailable = (reason: string): WholePackResult => ({ status: 'unavailable', reason });
  if (!Number.isInteger(targetGrams) || targetGrams < MIN_TARGET_GRAMS || targetGrams > MAX_TARGET_GRAMS || targetGrams % 50 !== 0) {
    return unavailable('Choose a target between 50g and 1,000g in 50g steps.');
  }
  if (!group.retailer?.trim() || !validSnapshotDate(group.date)) {
    return unavailable('This calculation needs one named retailer and one dated price snapshot.');
  }
  if (!group.items.length) return unavailable('This snapshot has no packs to compare.');
  if (group.items.length > 100) return unavailable('This snapshot has too many pack options for this exact demo calculation.');
  const seen = new Set<string>();
  const packs: Array<{ item: ComparisonItem; mass: number; price: number }> = [];
  for (const item of group.items) {
    if (!item.id || seen.has(item.id)) return unavailable('This snapshot contains missing or duplicated product identities.');
    seen.add(item.id);
    const mass = integerMilligrams(item.mass_g);
    if (mass === null) return unavailable(`A valid pack mass, to at most 0.001g precision, is needed for “${item.name}”. No pack has been silently excluded.`);
    const price = integerPence(item.price_gbp);
    if (price === null) return unavailable(`A positive pack price in whole pennies is needed for “${item.name}”. No pack has been silently excluded.`);
    packs.push({ item, mass, price });
  }
  packs.sort((a, b) => a.item.id < b.item.id ? -1 : a.item.id > b.item.id ? 1 : a.item.name.localeCompare(b.item.name));
  const quantum = packs.reduce((value, pack) => gcd(value, pack.mass), 0);
  const target = Math.ceil(targetGrams * MILLIGRAMS_PER_GRAM / quantum);
  const maxPack = Math.max(...packs.map(pack => pack.mass / quantum));
  // A minimum-cost basket cannot have a removable pack: removing it would
  // strictly lower its cost while still reaching the target. Hence its mass
  // is strictly below target + largest pack. No arbitrary pack-count cutoff.
  const lastMass = target + maxPack - 1;
  if (!Number.isSafeInteger(lastMass) || lastMass > MAX_STATES) {
    return unavailable('These pack quantities need more precision or a larger search than this demo supports. No approximate basket is shown.');
  }
  const minPack = Math.min(...packs.map(pack => pack.mass / quantum));
  const maxPrice = Math.max(...packs.map(pack => pack.price));
  if (!Number.isSafeInteger((Math.ceil(target / minPack) + 1) * maxPrice)) {
    return unavailable('These prices exceed the safe exact calculation range.');
  }
  const costs = new Float64Array(lastMass + 1).fill(Infinity);
  const counts = new Uint32Array(lastMass + 1).fill(0xffffffff);
  const previousMass = new Int32Array(lastMass + 1).fill(-1);
  const previousItem = new Int16Array(lastMass + 1).fill(-1);
  costs[0] = 0;
  counts[0] = 0;
  for (let mass = 0; mass < target; mass += 1) {
    if (!Number.isFinite(costs[mass])) continue;
    for (let index = 0; index < packs.length; index += 1) {
      const pack = packs[index];
      const next = mass + pack.mass / quantum;
      const nextCost = costs[mass] + pack.price;
      const nextCount = counts[mass] + 1;
      if (nextCost < costs[next] || (nextCost === costs[next] && nextCount < counts[next])) {
        costs[next] = nextCost;
        counts[next] = nextCount;
        previousMass[next] = mass;
        previousItem[next] = index;
      }
    }
  }
  let best = -1;
  for (let mass = target; mass <= lastMass; mass += 1) {
    if (!Number.isFinite(costs[mass])) continue;
    // Ascending mass gives the lower-excess tie break before pack count.
    if (best < 0 || costs[mass] < costs[best]) best = mass;
  }
  if (best < 0) return unavailable('No whole-pack basket could be calculated for this snapshot.');
  const quantities = new Uint32Array(packs.length);
  for (let mass = best; mass > 0; mass = previousMass[mass]) {
    quantities[previousItem[mass]] += 1;
  }
  const totalMilligrams = best * quantum;
  const totalGrams = totalMilligrams / MILLIGRAMS_PER_GRAM;
  return {
    status: 'ready', retailer: group.retailer, date: group.date,
    lines: packs.flatMap((pack, index) => quantities[index] ? [{
      item: pack.item, count: quantities[index], packMassGrams: pack.mass / MILLIGRAMS_PER_GRAM,
      packPricePence: pack.price, totalPricePence: pack.price * quantities[index],
    }] : []),
    targetGrams, totalGrams,
    excessGrams: (totalMilligrams - targetGrams * MILLIGRAMS_PER_GRAM) / MILLIGRAMS_PER_GRAM,
    totalPricePence: costs[best], packCount: counts[best],
    pricePer100gPence: costs[best] * 100 / totalGrams,
    consideredProducts: packs.length, massQuantumMilligrams: quantum,
  };
}
