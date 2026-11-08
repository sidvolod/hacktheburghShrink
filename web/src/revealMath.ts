import { comparableUnitPriceChange } from './math.ts';
import type { SnackCase } from './types';

export interface InflationReceipt {
  oldMass: number;
  newMass: number;
  removedGrams: number;
  oldPrice: number;
  newPrice: number;
  constantWeightCost: number;
  missingQuantityCost: number;
  stickerChangeFraction: number;
  shrinkContributionFraction: number;
  effectiveChangeFraction: number;
}

/** Attribute the shelf-price change first, then restore missing grams at the new rate. */
export function inflationReceipt(snack: SnackCase): InflationReceipt | null {
  const change = comparableUnitPriceChange(snack.old, snack.new, snack.unit_price_change_fraction);
  const oldMass = snack.old.mass_g;
  const newMass = snack.new.mass_g;
  const oldPrice = snack.old.price_gbp;
  const newPrice = snack.new.price_gbp;
  if (change == null || oldPrice == null || newPrice == null || !(oldMass > newMass)) return null;
  const constantWeightCost = newPrice * oldMass / newMass;
  const missingQuantityCost = constantWeightCost - newPrice;
  const stickerChangeFraction = (newPrice - oldPrice) / oldPrice;
  const shrinkContributionFraction = missingQuantityCost / oldPrice;
  return {
    oldMass, newMass, removedGrams: oldMass - newMass, oldPrice, newPrice,
    constantWeightCost, missingQuantityCost, stickerChangeFraction,
    shrinkContributionFraction, effectiveChangeFraction: constantWeightCost / oldPrice - 1,
  };
}
