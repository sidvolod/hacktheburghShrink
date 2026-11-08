export type Transaction = { date: string; description: string; spending_pence: number; amount_pence: number; exclusion: 'income' | 'refund' | 'own_transfer' | 'savings' | 'cash_withdrawal' | null };
export class StatementError extends Error { constructor(message: string) { super(message); this.name = 'StatementError'; } }
const tidy = (value: string) => value.replace(/^\uFEFF/, '').trim();
const normalHeader = (value: string) => tidy(value).toLowerCase().replace(/[^a-z0-9]/g, '');
const aliases = {
  date: ['date', 'transactiondate', 'bookingdate', 'posteddate', 'valuedate', 'datetime'],
  description: ['description', 'transactiondescription', 'details', 'merchant', 'merchantname', 'narrative', 'payee', 'transactiondetails', 'name', 'memo'],
  amount: ['amount', 'transactionamount', 'amountgbp', 'gbpamount', 'amountsterling', 'value', 'gbp'],
  debit: ['debit', 'debits', 'debitamount', 'moneyout', 'paidout', 'withdrawal', 'withdrawals', 'out'],
  credit: ['credit', 'credits', 'creditamount', 'moneyin', 'paidin', 'deposit', 'deposits', 'in'],
  type: ['type', 'transactiontype', 'direction', 'debitcredit', 'creditdebit', 'drcr', 'transactioncode'],
};
function csvRows(text: string): string[][] {
  if (!tidy(text)) throw new StatementError('The CSV is empty. Choose a statement containing a header and transactions.');
  const firstLine = text.split(/\r?\n/, 1)[0];
  const delimiter = [',', ';', '\t'].sort((a, b) => firstLine.split(b).length - firstLine.split(a).length)[0];
  const rows: string[][] = []; let row: string[] = []; let field = ''; let quoted = false; let closed = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (quoted) { if (char === '"') { if (text[i + 1] === '"') { field += '"'; i++; } else { quoted = false; closed = true; } } else field += char; continue; }
    if (char === '"') { if (field.trim() || closed) throw new StatementError('Malformed CSV: a quote appears inside an unquoted field.'); quoted = true; continue; }
    if (char === delimiter) { row.push(tidy(field)); field = ''; closed = false; continue; }
    if (char === '\r' || char === '\n') { if (char === '\r' && text[i + 1] === '\n') i++; row.push(tidy(field)); if (row.some(Boolean)) rows.push(row); row = []; field = ''; closed = false; continue; }
    if (closed && char.trim()) throw new StatementError('Malformed CSV: unexpected text after a quoted field.');
    if (!closed) field += char;
  }
  if (quoted) throw new StatementError('Malformed CSV: a quoted field was not closed.');
  row.push(tidy(field)); if (row.some(Boolean)) rows.push(row);
  if (rows.length < 2) throw new StatementError('The CSV needs a header and at least one transaction.');
  const columns = rows[0].length;
  if (rows.some(value => value.length !== columns)) throw new StatementError('Malformed CSV: rows have different numbers of columns. Quote amounts containing commas.');
  return rows;
}
function parseDate(value: string, row: number): string {
  const raw = value.trim(); let year: number; let month: number; let day: number;
  const uk = raw.match(/^(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{2}|\d{4})$/);
  const iso = raw.match(/^(\d{4})-(\d{2})-(\d{2})(?:[ T](?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d)?$/);
  if (uk) { day = +uk[1]; month = +uk[2]; year = +uk[3]; if (uk[3].length === 2) year += year <= 68 ? 2000 : 1900; }
  else if (iso) { year = +iso[1]; month = +iso[2]; day = +iso[3]; }
  else throw new StatementError(`Row ${row}: use DD/MM/YYYY or YYYY-MM-DD dates.`);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (year < 1900 || year > 2200 || date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) throw new StatementError(`Row ${row}: the transaction date is invalid.`);
  return `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
}
function pence(value: string, row: number, blankAllowed = false): number {
  let raw = value.replace(/Â?£|GBP/gi, '').replaceAll('−', '-').trim(); if (!raw && blankAllowed) return 0;
  let sign = 1;
  if (/^\(.*\)$/.test(raw)) { sign = -1; raw = raw.slice(1, -1); }
  if (/\s*DR$/i.test(raw)) { sign = -1; raw = raw.replace(/\s*DR$/i, '').replace(/^[+-]/, ''); }
  else if (/\s*CR$/i.test(raw)) { sign = 1; raw = raw.replace(/\s*CR$/i, '').replace(/^[+-]/, ''); }
  raw = raw.replace(/\s/g, '');
  if (!/^[+-]?(?:(?:\d+|\d{1,3}(?:,\d{3})+)(?:\.\d{1,2})?|\.\d{1,2})$/.test(raw)) throw new StatementError(`Row ${row}: an amount is invalid. Use pounds with at most two decimal places.`);
  const result = Math.round(Number(raw.replaceAll(',', '')) * 100) * sign;
  if (!Number.isSafeInteger(result)) throw new StatementError(`Row ${row}: an amount is outside the supported range.`);
  return result;
}
export function parseBankCsv(text: string): Transaction[] {
  const rows = csvRows(text); const headers = rows[0].map(normalHeader);
  const index = (key: keyof typeof aliases) => { const found = headers.map((header, i) => aliases[key].includes(header) ? i : -1).filter(i => i >= 0); if (found.length > 1) throw new StatementError(`The CSV has multiple possible ${key} columns; keep one.`); return found[0] ?? -1; };
  const dateColumn = index('date'), descriptionColumn = index('description'), amountColumn = index('amount'), debitColumn = index('debit'), creditColumn = index('credit'), typeColumn = index('type');
  if (dateColumn < 0 || descriptionColumn < 0 || (amountColumn < 0 && debitColumn < 0 && creditColumn < 0)) throw new StatementError('Could not identify the columns. Include date, description, and amount (negative for spending), or separate debit and credit columns.');
  const transactions: Transaction[] = []; let signedEvidence = debitColumn >= 0 || creditColumn >= 0;
  for (let i = 1; i < rows.length; i++) {
    const row = rows[i], rowNumber = i + 1;
    const date = parseDate(row[dateColumn], rowNumber), description = row[descriptionColumn].trim();
    if (!description) throw new StatementError(`Row ${rowNumber}: the description is empty.`);
    let signed: number;
    if (debitColumn >= 0 || creditColumn >= 0) {
      const debit = debitColumn >= 0 ? Math.abs(pence(row[debitColumn], rowNumber, true)) : 0, credit = creditColumn >= 0 ? Math.abs(pence(row[creditColumn], rowNumber, true)) : 0;
      if (debit < 0 || credit < 0 || (debit > 0 && credit > 0)) throw new StatementError(`Row ${rowNumber}: debit and credit columns must contain positive amounts, with only one filled per row.`);
      signed = credit - debit;
    } else {
      signed = pence(row[amountColumn], rowNumber);
      const type = typeColumn >= 0 ? normalHeader(row[typeColumn]) : '';
      if (/^(debit|dr|deb|dd|directdebit|so|standingorder|fpo|pos|card|cardpayment|purchase|payment|out|moneyout|withdrawal)$/.test(type)) { signed = -Math.abs(signed); signedEvidence = true; }
      else if (/^(credit|cr|bgc|salary|income|deposit|in|moneyin|refund)$/.test(type)) { signed = Math.abs(signed); signedEvidence = true; }
      if (signed < 0) signedEvidence = true;
    }
    const lower = description.toLowerCase();
    let exclusion: Transaction['exclusion'] = null;
    if (/\b(ATM|CASH\s+WITHDRAWAL|CASH\s+MACHINE)\b/i.test(lower)) exclusion = 'cash_withdrawal';
    else if (/\b(REFUND|REVERSAL|CHARGEBACK)\b/i.test(lower)) exclusion = 'refund';
    else if (/\b(SALARY|PAYROLL|WAGES)\b/i.test(lower)) exclusion = 'income';
    else if (/\b(SAVINGS?\s+(?:MOVE|TRANSFER)|TRANSFER\s+TO\s+SAVINGS?|SAVINGS?\s+POT|ROUND\s*UP\s+SAVINGS?)\b/i.test(lower)) exclusion = 'savings';
    else if (/\b(OWN\s+ACCOUNT(?:\s+TRANSFER)?|INTERNAL\s+TRANSFER|TRANSFER\s+(?:TO|FROM)\s+(?:MY|OWN)|BETWEEN\s+(?:MY\s+)?ACCOUNTS)\b/i.test(lower)) exclusion = 'own_transfer';
    else if (signed >= 0) exclusion = 'income';
    transactions.push({ date, description, spending_pence: signed < 0 ? -signed : 0, amount_pence: Math.abs(signed), exclusion });
  }
  if (!signedEvidence) throw new StatementError('These amounts are all positive and their direction is unknown. Use negative amounts for spending, a debit/credit type column, or separate debit and credit columns.');
  return transactions;
}

export type HeadlineReference = { start_month: string; end_month: string; cpi_rate: number; cpih_rate: number; release_date: string; source_url: string; source_title: string };
export function headlineReferenceForPeriod(reference: HeadlineReference | undefined, start: string, end: string): HeadlineReference | null {
  return reference && reference.start_month === start && reference.end_month === end && typeof reference.cpi_rate === 'number' && typeof reference.cpih_rate === 'number' && Number.isFinite(reference.cpi_rate) && Number.isFinite(reference.cpih_rate) && reference.cpi_rate > -1 && reference.cpih_rate > -1 ? reference : null;
}
export type InflationBundle = {
  schema_version: number; mode: 'synthetic_demo';
  categories: { id: string; name: string; coicop: string; series_id: string; values: Record<string, number>; data_kind: 'observed_ons' }[];
  benchmark: { id: string; name: string; synthetic: boolean; base_month: string; reference_weights: Record<string, number>; values: Record<string, number> };
  headline: null; cpih: null; headline_reference?: HeadlineReference;
  samples: { id: string; name: string; path: string; synthetic: boolean; description: string }[];
  limitations: string[];
};
export type InflationResult = {
  schema_version: 1; mode: 'synthetic_demo'; input_is_synthetic: boolean;
  personal_rate: number; headline_rate: number | null; cpih_rate: number | null; headline_reference: HeadlineReference | null; benchmark_rate: number;
  start_month: string; end_month: string; csv_period: { first_date: string; last_date: string; calendar_months: number };
  total_spending_gbp: number; categories: { category_id: string; name: string; spending_gbp: number; weight: number; rate: number; contribution: number }[];
  other_share: number; observed_price_changes: { merchant: string; from_month: string; to_month: string; old_amount_gbp: number; new_amount_gbp: number; change: number; occurrences: number }[];
  warnings: string[]; exclusions: Record<'income' | 'refund' | 'own_transfer' | 'savings' | 'cash_withdrawal', { count: number; amount_gbp: number }>;
  summary: string;
};
const median = (values: number[]) => { const sorted = [...values].sort((a, b) => a - b), mid = Math.floor(sorted.length / 2); return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2; };
const monthIndex = (month: string) => Number(month.slice(0, 4)) * 12 + Number(month.slice(5, 7)) - 1;
const monthFromIndex = (month: number) => `${Math.floor(month / 12)}-${String(month % 12 + 1).padStart(2, '0')}`;
const monthName = (month: string) => new Date(`${month}-15T12:00:00Z`).toLocaleDateString('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' });
export function categoriseDemoTransaction(description: string): string {
  if (/\bDEMO\s+CHOCOLATE\s+(?:SHOP|CLUB)\b/i.test(description)) return 'chocolate';
  if (/\bDEMO\s+CRISPS\s+(?:SHOP|CLUB)\b/i.test(description)) return 'crisps';
  return 'other';
}
function merchantLabel(description: string): string {
  return description.toUpperCase().replace(/\bREF\s*\w+|\b\d{4,}\b/g, ' ').replace(/^(?:CARD\s+PAYMENT|DIRECT\s+DEBIT|STANDING\s+ORDER)\s+/, '').replace(/[^A-Z0-9 ]/g, ' ').replace(/\s+/g, ' ').trim();
}
function recurring(transactions: Transaction[], first: string, last: string): InflationResult['observed_price_changes'] {
  if (monthIndex(last.slice(0, 7)) - monthIndex(first.slice(0, 7)) + 1 < 13) return [];
  const endMonth = last.slice(0, 7), startMonth = monthFromIndex(monthIndex(endMonth) - 12);
  const groups = new Map<string, Transaction[]>();
  transactions.filter(item => !item.exclusion).forEach(item => { const label = merchantLabel(item.description); if (label) groups.set(label, [...(groups.get(label) ?? []), item]); });
  const output: InflationResult['observed_price_changes'] = [];
  for (const [merchant, items] of groups) {
    const months = new Map<string, Transaction[]>(); items.forEach(item => { const month = item.date.slice(0, 7); months.set(month, [...(months.get(month) ?? []), item]); });
    if (months.size < 6 || [...months.values()].some(values => values.length !== 1) || !months.has(startMonth) || !months.has(endMonth)) continue;
    const ordered = [...items].sort((a, b) => a.date.localeCompare(b.date));
    const gaps = ordered.slice(1).map((item, i) => monthIndex(item.date.slice(0, 7)) - monthIndex(ordered[i].date.slice(0, 7)));
    const days = ordered.slice(1).map((item, i) => (Date.parse(item.date) - Date.parse(ordered[i].date)) / 86400000);
    const amounts = ordered.map(item => item.spending_pence);
    if (gaps.some(gap => gap > 2) || gaps.filter(gap => gap === 1).length / gaps.length < .75 || median(days) < 25 || median(days) > 35 || Math.max(...amounts) / Math.min(...amounts) > 1.5) continue;
    const old = months.get(startMonth)![0].spending_pence, current = months.get(endMonth)![0].spending_pence;
    output.push({ merchant, from_month: startMonth, to_month: endMonth, old_amount_gbp: old / 100, new_amount_gbp: current / 100, change: current / old - 1, occurrences: ordered.length });
  }
  return output.sort((a, b) => b.change - a.change || a.merchant.localeCompare(b.merchant));
}
export function personalInflation(csvText: string, bundle: InflationBundle, options: { syntheticInput?: boolean } = {}): InflationResult {
  if (!bundle || bundle.schema_version !== 1 || !Array.isArray(bundle.categories) || !bundle.categories.length || !bundle.benchmark?.synthetic) throw new StatementError('The prepared demonstration indices are incomplete.');
  const common = Object.keys(bundle.benchmark.values).filter(month => bundle.categories.every(category => Number.isFinite(category.values[month]) && category.values[month] > 0)).sort();
  const end = common.at(-1); if (!end) throw new StatementError('No common price-index month is available.');
  const start = monthFromIndex(monthIndex(end) - 12);
  if (!common.includes(start) || !(bundle.benchmark.values[start] > 0) || !(bundle.benchmark.values[end] > 0)) throw new StatementError('The existing indices do not contain the matching month twelve months earlier.');
  const reference = bundle.headline_reference;
  const headlineReference = headlineReferenceForPeriod(reference, start, end);
  const transactions = parseBankCsv(csvText), sorted = [...transactions].sort((a, b) => a.date.localeCompare(b.date));
  const first = sorted[0].date, last = sorted.at(-1)!.date;
  const exclusions: InflationResult['exclusions'] = { income: { count: 0, amount_gbp: 0 }, refund: { count: 0, amount_gbp: 0 }, own_transfer: { count: 0, amount_gbp: 0 }, savings: { count: 0, amount_gbp: 0 }, cash_withdrawal: { count: 0, amount_gbp: 0 } };
  const spending = new Map<string, number>(); let total = 0;
  for (const item of transactions) {
    if (item.exclusion) { exclusions[item.exclusion].count++; exclusions[item.exclusion].amount_gbp += item.amount_pence / 100; continue; }
    const category = categoriseDemoTransaction(item.description); spending.set(category, (spending.get(category) ?? 0) + item.spending_pence); total += item.spending_pence;
  }
  if (!total) throw new StatementError('No eligible spending remains after excluding income, refunds, transfers, savings and cash withdrawals.');
  for (const item of Object.values(exclusions)) item.amount_gbp = Math.round(item.amount_gbp * 100) / 100;
  const benchmarkRate = bundle.benchmark.values[end] / bundle.benchmark.values[start] - 1;
  const otherRate = headlineReference?.cpi_rate ?? benchmarkRate;
  const categories: InflationResult['categories'] = [...spending].map(([id, pence]) => {
    const price = bundle.categories.find(category => category.id === id), rate = price ? price.values[end] / price.values[start] - 1 : otherRate;
    const weight = pence / total;
    return { category_id: id, name: price?.name ?? (headlineReference ? 'Other · all-items CPI fallback' : 'Other · demo fallback'), spending_gbp: pence / 100, weight, rate, contribution: weight * rate };
  }).sort((a, b) => b.contribution - a.contribution || a.category_id.localeCompare(b.category_id));
  const personalRate = categories.reduce((sum, category) => sum + category.contribution, 0), otherShare = (spending.get('other') ?? 0) / total;
  const threeMonthDate = new Date(`${monthFromIndex(monthIndex(first.slice(0, 7)) + 3)}-01T00:00:00Z`); threeMonthDate.setUTCDate(Math.min(Number(first.slice(8, 10)), new Date(Date.UTC(threeMonthDate.getUTCFullYear(), threeMonthDate.getUTCMonth() + 1, 0)).getUTCDate()));
  const calendarMonths = monthIndex(last.slice(0, 7)) - monthIndex(first.slice(0, 7)) + 1;
  const warnings = [
    headlineReference ? 'Demonstration spending and category rules remain synthetic. Official CPI and CPIH are fixed published annual rates for the stated period, not live data or a full index history.' : 'Demonstration only: no matching official all-items CPI or CPIH reference is available. The benchmark is a synthetic 50/50 chocolate-and-crisps basket, not headline inflation.',
    'Only explicit DEMO CHOCOLATE SHOP/CLUB and DEMO CRISPS SHOP/CLUB labels are categorised. This is a demonstration rule set, not a general bank merchant classifier.',
    headlineReference ? 'Other spending receives the official all-items CPI rate. This is an aggregate fallback, not a category-specific household inflation mapping.' : 'Other spending receives the synthetic snack-basket rate. It has no valid household-category inflation mapping.',
  ];
  if (reference && !headlineReference) warnings.push('The fixed official headline reference does not match the selected index year or contains invalid rates and was ignored.');
  if (Date.parse(last) < threeMonthDate.getTime()) warnings.push('The CSV covers less than three months. Spending weights may be skewed by seasonality or one-off purchases.');
  if (otherShare > .25) warnings.push('More than 25% of eligible spending is in other. This result is unreliable as a personal inflation estimate.');
  if (last.slice(0, 7) < common[0] || first.slice(0, 7) > end) warnings.push('The CSV dates do not overlap the available price-index data. The calculation still uses the latest index year and the supplied spending weights.');
  if (exclusions.cash_withdrawal.count) warnings.push('Cash withdrawals are excluded and reported separately because their eventual purchases cannot be categorised.');
  const observed = recurring(transactions, first, last);
  if (observed.length) warnings.push('Observed recurring-payment changes are separate from inflation: changed amounts can reflect usage, package or service changes.');
  const syntheticColumn = csvRows(csvText)[0].map(normalHeader).indexOf('synthetic');
  const inputSynthetic = !!options.syntheticInput || (syntheticColumn >= 0 && csvRows(csvText).slice(1).every(row => /^(true|yes|1)$/i.test(row[syntheticColumn])));
  const drivers = categories.slice(0, 2).map(category => `${category.name} (${category.contribution >= 0 ? '+' : ''}${(category.contribution * 100).toFixed(1)}pp)`).join(' and ');
  return { schema_version: 1, mode: 'synthetic_demo', input_is_synthetic: inputSynthetic, personal_rate: personalRate, headline_rate: headlineReference?.cpi_rate ?? null, cpih_rate: headlineReference?.cpih_rate ?? null, headline_reference: headlineReference, benchmark_rate: benchmarkRate, start_month: start, end_month: end,
    csv_period: { first_date: first, last_date: last, calendar_months: calendarMonths }, total_spending_gbp: total / 100, categories, other_share: otherShare, observed_price_changes: observed, warnings, exclusions,
    summary: `Your demo-weighted inflation over ${monthName(start)} to ${monthName(end)} was ${(personalRate * 100).toFixed(1)}%, ${headlineReference ? `versus ${(headlineReference.cpi_rate * 100).toFixed(1)}% official headline CPI and ${(headlineReference.cpih_rate * 100).toFixed(1)}% CPIH.` : `versus ${(benchmarkRate * 100).toFixed(1)}% for the synthetic snack benchmark. Headline CPI is unavailable.`} The largest contributions were ${drivers}.` };
}
