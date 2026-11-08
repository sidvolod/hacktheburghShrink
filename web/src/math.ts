export function unitPrice(price: number | null, mass: number | null): number | null {
  if (price == null || mass == null || !Number.isFinite(price) || !Number.isFinite(mass) || price <= 0 || mass <= 0) return null;
  return 100 * price / mass;
}

export function unitPriceChange(oldPrice: number | null, oldMass: number | null, newPrice: number | null, newMass: number | null): number | null {
  const before = unitPrice(oldPrice, oldMass);
  const after = unitPrice(newPrice, newMass);
  return before == null || after == null ? null : after / before - 1;
}

export function massChange(oldMass: number, newMass: number): number | null {
  return Number.isFinite(oldMass) && Number.isFinite(newMass) && oldMass > 0 && newMass > 0 ? newMass / oldMass - 1 : null;
}

export function observationIndex(requested: number | null, count: number): number {
  if (!Number.isInteger(count) || count < 1) throw new RangeError('Observation selection requires a nonempty history.');
  if (requested == null || !Number.isFinite(requested)) return count - 1;
  return Math.min(count - 1, Math.max(0, Math.floor(requested)));
}

interface PriceVersion {
  price_gbp: number | null;
  mass_g: number;
  price_basis: string;
}

export function comparableUnitPriceChange(before: PriceVersion, after: PriceVersion, reportedChange: number | null | undefined): number | null {
  const beforeBasis = before.price_basis.trim();
  const afterBasis = after.price_basis.trim();
  if (reportedChange == null || !Number.isFinite(reportedChange) || !beforeBasis || beforeBasis !== afterBasis || /^(not[_ ]reported|unknown|unavailable)$/i.test(beforeBasis)) return null;
  return unitPriceChange(before.price_gbp, before.mass_g, after.price_gbp, after.mass_g);
}

export function isReviewedReplacementPair(link: { status: string; old_barcode: string | null; new_barcode: string | null }): boolean {
  return Boolean(link.old_barcode && link.new_barcode && ['manually_supported_replacement_pair', 'reviewed_reported_pair'].includes(link.status));
}
