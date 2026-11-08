"""Local CSV expenditure weights applied to existing price indices.

Only explicitly named synthetic snack merchants have category rules. General
supermarket transactions remain ``other`` because a bank statement cannot reveal
its item-level basket. No transaction description is logged or returned.
"""
from __future__ import annotations

import argparse
import calendar
import csv
import io
import json
import math
import re
from statistics import median
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path


class PersonalInflationError(ValueError):
    """A readable input/coverage error that never contains bank descriptions."""


DEMO_RULES = (
    (re.compile(r"\bDEMO\s+CHOCOLATE\s+(?:SHOP|CLUB)\b", re.I), "chocolate"),
    (re.compile(r"\bDEMO\s+CRISPS\s+(?:SHOP|CLUB)\b", re.I), "crisps"),
)
HEADER_ALIASES = {
    "date": {"date", "transactiondate", "bookingdate", "posteddate", "valuedate", "datetime"},
    "description": {"description", "transactiondescription", "details", "transactiondetails", "merchant", "merchantname", "payee", "name", "memo", "narrative"},
    "amount": {"amount", "transactionamount", "amountgbp", "gbpamount", "amountsterling", "value", "gbp"},
    "debit": {"debit", "debits", "debitamount", "moneyout", "paidout", "withdrawal", "withdrawals", "out"},
    "credit": {"credit", "credits", "creditamount", "moneyin", "paidin", "deposit", "deposits", "in"},
    "type": {"type", "transactiontype", "transactioncode", "drcr", "creditdebit", "debitcredit", "direction"},
}
OUT_TYPES = {"debit", "dr", "deb", "dd", "directdebit", "so", "standingorder", "fpo", "pos", "card", "cardpayment", "purchase", "payment", "out", "moneyout", "withdrawal"}
IN_TYPES = {"credit", "cr", "bgc", "salary", "income", "deposit", "in", "moneyin", "refund"}


def _normalise(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower().lstrip("\ufeff"))


def _month(value: date) -> str:
    return value.strftime("%Y-%m")


def _shift_month(value: str, delta: int) -> str:
    try:
        year, month = map(int, value.split("-"))
        if not 1 <= month <= 12:
            raise ValueError
    except (ValueError, AttributeError):
        raise PersonalInflationError("Price-index dates must use YYYY-MM.") from None
    total = year * 12 + month - 1 + delta
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


def _date(value: str, row: int) -> date:
    value = value.strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d", "%d-%m-%Y", "%d.%m.%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(value, fmt).date()
            if not 1900 <= parsed.year <= 2200:
                continue
            return parsed
        except ValueError:
            pass
    raise PersonalInflationError(f"CSV row {row} has an invalid date; use DD/MM/YYYY or YYYY-MM-DD.")


def _money(value: str, row: int, *, blank_zero: bool = False) -> tuple[int, int | None]:
    value = value.strip().replace("Â£", "").replace("£", "").replace("GBP", "").replace("\u00a0", "").replace(" ", "")
    if not value and blank_zero:
        return 0, None
    direction = None
    if value.upper().endswith(("DR", "CR")):
        direction = -1 if value[-2:].upper() == "DR" else 1
        value = value[:-2]
    if value.startswith("(") and value.endswith(")"):
        value = "-" + value[1:-1]
    value = value.replace("−", "-")
    if not re.fullmatch(r"[+-]?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{1,2})?|\.\d{1,2})", value):
        raise PersonalInflationError(f"CSV row {row} has an invalid UK monetary amount; use 1,234.56 format.")
    value = value.replace(",", "")
    try:
        number = Decimal(value)
        if not number.is_finite():
            raise InvalidOperation
        pence = int((number * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError, OverflowError):
        raise PersonalInflationError(f"CSV row {row} has an invalid monetary amount.") from None
    if direction is not None:
        pence = abs(pence) * direction
    if abs(pence) > 9_007_199_254_740_991:
        raise PersonalInflationError(f"CSV row {row} has an amount outside the supported range.")
    return pence, direction


def _excluded_reason(description: str) -> str | None:
    if re.search(r"\b(ATM|CASHPOINT|CASH\s+WITHDRAWAL|CASH\s+MACHINE)\b", description, re.I):
        return "cash_withdrawal"
    if re.search(r"\b(REFUND|REVERSAL|CHARGEBACK|REIMBURSEMENT)\b", description, re.I):
        return "refund"
    if re.search(r"\b(SALARY|PAYROLL|WAGES)\b", description, re.I):
        return "income"
    if re.search(r"\b(SAVINGS?\s+(?:MOVE|TRANSFER)|TRANSFER\s+TO\s+SAVINGS?|MOVE\s+TO\s+(?:SAVINGS?|POT)|POT\s+TRANSFER|SAVINGS?\s+POT|ROUND\s*UP\s+SAVINGS?)\b", description, re.I):
        return "savings"
    if re.search(r"\b(OWN\s+ACCOUNTS?(?:\s+TRANSFER)?|INTERNAL\s+TRANSFER|TRANSFER\s+(?:TO|FROM)\s+(?:MY|OWN)|BETWEEN\s+(?:(?:MY|OWN)\s+)?ACCOUNTS)\b", description, re.I):
        return "own_transfer"
    return None


def _category(description: str) -> str:
    return next((category for pattern, category in DEMO_RULES if pattern.search(description)), "other")


def _merchant(description: str) -> str:
    # Used only transiently to match recurring payments; raw descriptions never
    # enter the structured result. Digits/card references are not retained.
    words = re.sub(r"\bREF\s*\w+|\b\d{4}-\d{2}-\d{2}\b|\b\d{4,}\b", " ", description.upper())
    words = re.sub(r"^(?:CARD(?:\s+PAYMENT)?|POS|DIRECT\s+DEBIT|DD|STANDING\s+ORDER)\s+", "", words)
    words = re.sub(r"[^A-Z0-9 ]", " ", words)
    words = re.sub(r"\s+", " ", words).strip()
    return words


def _parse_csv(text: str) -> tuple[list[dict], dict, list[str]]:
    if not text.strip():
        raise PersonalInflationError("The CSV is empty.")
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    try:
        reader = csv.reader(io.StringIO(text.lstrip("\ufeff")), dialect=dialect, strict=True)
        headers = next(reader)
    except (StopIteration, csv.Error):
        raise PersonalInflationError("The CSV has no readable header row.") from None
    normalised = [_normalise(header) for header in headers]
    fields = {}
    for field, aliases in HEADER_ALIASES.items():
        matches = [position for position, header in enumerate(normalised) if header in aliases]
        if len(matches) > 1:
            raise PersonalInflationError(f"The CSV has multiple possible {field} columns; keep one.")
        if matches:
            fields[field] = matches[0]
    if "date" not in fields or "description" not in fields:
        raise PersonalInflationError("The CSV needs a date and description/merchant column.")
    if "amount" not in fields and "debit" not in fields and "credit" not in fields:
        raise PersonalInflationError("The CSV needs an amount column, or debit/money-out and credit/money-in columns.")
    transactions = []
    exclusions = {key: {"count": 0, "amount_gbp": 0.0} for key in ("income", "refund", "own_transfer", "savings", "cash_withdrawal")}
    exclusion_pence = defaultdict(int)
    eligible_rows = 0
    ambiguous_positive = 0
    dates = []
    synthetic_column = next((position for position, header in enumerate(normalised) if header == "synthetic"), None)
    synthetic_flags = []
    try:
        for row in reader:
            number = reader.line_num
            if not row or not any(value.strip() for value in row):
                continue
            if len(row) != len(headers):
                raise PersonalInflationError(f"CSV row {number} has the wrong number of columns; check quoting and delimiters.")
            day = _date(row[fields["date"]], number)
            description = row[fields["description"]].strip()
            if not description:
                raise PersonalInflationError(f"CSV row {number} has an empty description/merchant.")
            dates.append(day)
            synthetic_flags.append(synthetic_column is not None and row[synthetic_column].strip().lower() in {"true", "yes", "1"})
            kind = _normalise(row[fields["type"]]) if "type" in fields else ""
            if "debit" in fields or "credit" in fields:
                debit = abs(_money(row[fields["debit"]], number, blank_zero=True)[0]) if "debit" in fields else 0
                credit = abs(_money(row[fields["credit"]], number, blank_zero=True)[0]) if "credit" in fields else 0
                if debit and credit:
                    raise PersonalInflationError(f"CSV row {number} has both a debit and credit; split it into separate transactions.")
                amount = credit - debit
            else:
                amount, explicit_direction = _money(row[fields["amount"]], number)
                if kind in OUT_TYPES:
                    amount = -abs(amount)
                elif kind in IN_TYPES:
                    amount = abs(amount)
                elif amount > 0 and explicit_direction is None:
                    ambiguous_positive += 1
            reason = _excluded_reason(description)
            if reason is None and amount >= 0:
                reason = "income"
            if reason:
                exclusions[reason]["count"] += 1
                exclusion_pence[reason] += abs(amount)
                continue
            eligible_rows += 1
            transactions.append({"date": day, "pence": -amount, "category": _category(description), "merchant_key": _merchant(description)})
    except csv.Error:
        raise PersonalInflationError("The CSV has malformed quoting or delimiters.") from None
    if not dates:
        raise PersonalInflationError("The CSV has no transaction rows.")
    if not transactions:
        if ambiguous_positive:
            raise PersonalInflationError("No spending found. Positive-only amount columns are ambiguous: use negative amounts for spending, a debit/money-out column, or a debit/credit type column.")
        raise PersonalInflationError("No eligible spending remains after excluding credits, refunds, transfers, savings and cash withdrawals.")
    for key, pence in exclusion_pence.items():
        exclusions[key]["amount_gbp"] = pence / 100
    warnings = []
    if ambiguous_positive:
        warnings.append("Positive amounts without a debit type were treated as credits; confirm the CSV sign convention.")
    if exclusions["cash_withdrawal"]["count"]:
        warnings.append("Cash withdrawals are excluded and flagged separately because their eventual purchases cannot be categorised.")
    return transactions, {"exclusions": exclusions, "first_date": min(dates).isoformat(), "last_date": max(dates).isoformat(), "transaction_rows": len(dates), "spending_rows": eligible_rows, "input_is_synthetic": bool(synthetic_flags) and all(synthetic_flags)}, warnings


def _values(spec: dict) -> dict[str, float]:
    if not isinstance(spec, dict):
        raise PersonalInflationError("A price-index series has an invalid format.")
    values = spec.get("values", {})
    if not isinstance(values, dict) or not values:
        raise PersonalInflationError("A price-index series has no monthly values.")
    clean = {}
    for month, value in values.items():
        _shift_month(month, 0)
        if not isinstance(value, (float, int)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise PersonalInflationError("Price-index levels must be finite positive numbers.")
        clean[month] = float(value)
    return clean


def _index_parts(bundle: dict) -> tuple[dict, dict | None, dict | None, dict | None]:
    if not isinstance(bundle, dict):
        raise PersonalInflationError("The price-index bundle has an invalid format.")
    raw = bundle.get("categories", [])
    if isinstance(raw, dict):
        categories = {key: {"id": key, **value} for key, value in raw.items()}
    elif isinstance(raw, list):
        if any(not isinstance(item, dict) or not isinstance(item.get("id"), str) for item in raw):
            raise PersonalInflationError("The price-index bundle has invalid category definitions.")
        categories = {item["id"]: item for item in raw}
    else:
        raise PersonalInflationError("The price-index bundle has invalid categories.")
    if not categories:
        raise PersonalInflationError("The price-index bundle has no category series.")
    headline = bundle.get("headline")
    cpih = bundle.get("cpih")
    benchmark = bundle.get("benchmark")
    if not headline and not benchmark:
        raise PersonalInflationError("All-items CPI or an explicitly labelled synthetic fallback benchmark is required for other spending.")
    if not headline and (not isinstance(benchmark, dict) or not benchmark.get("synthetic", False)):
        raise PersonalInflationError("A non-official fallback benchmark must be explicitly labelled synthetic.")
    return categories, headline, cpih, benchmark


def _observed_changes(transactions: list[dict], first: date, last: date) -> list[dict]:
    if (last.year - first.year) * 12 + last.month - first.month < 12:
        return []
    current_month = _month(last)
    previous_month = _shift_month(current_month, -12)
    grouped = defaultdict(list)
    for item in transactions:
        grouped[item["merchant_key"]].append(item)
    results = []
    for items in grouped.values():
        by_month = defaultdict(list)
        for item in items:
            by_month[_month(item["date"])].append(item)
        # Require one payment per occupied month and sustained monthly cadence.
        # Multiple variable purchases are not automatically treated as bills.
        if len(by_month) < 6 or any(len(month_items) != 1 for month_items in by_month.values()):
            continue
        if previous_month not in by_month or current_month not in by_month:
            continue
        ordered = sorted(items, key=lambda item: item["date"])
        intervals = [(b["date"] - a["date"]).days for a, b in zip(ordered, ordered[1:])]
        month_numbers = [item["date"].year * 12 + item["date"].month for item in ordered]
        month_gaps = [b - a for a, b in zip(month_numbers, month_numbers[1:])]
        median_interval = median(intervals) if intervals else 0
        if not month_gaps or max(month_gaps) > 2 or sum(gap == 1 for gap in month_gaps) / len(month_gaps) < .75 or not 25 <= median_interval <= 35:
            continue
        amounts = sorted(item["pence"] for item in ordered)
        if amounts[0] <= 0 or amounts[-1] / amounts[0] > 1.5:
            continue
        old = by_month[previous_month][0]
        new = by_month[current_month][0]
        # Display only the transiently normalised merchant label; card/reference
        # details and original descriptions never enter the result.
        merchant = new["merchant_key"]
        label = merchant if merchant and len(merchant) <= 60 else f"Recurring payment {len(results) + 1}"
        results.append({"merchant": label, "from_month": previous_month, "to_month": current_month, "old_amount_gbp": old["pence"] / 100,
            "new_amount_gbp": new["pence"] / 100, "change": new["pence"] / old["pence"] - 1,
            "occurrences": len(items), "note": "Observed payment amount change; quantity, plan and usage may also have changed. Not included in personal inflation."})
    return sorted(results, key=lambda item: item["change"], reverse=True)


def analyse_csv_text(text: str, indices: dict, *, synthetic_input: bool = False) -> dict:
    """Calculate annual index inflation using whole-CSV expenditure weights.

    Rates and contributions are fractions (0.05 = 5%; 0.02 = 2 percentage
    points). With demo categorisation this remains an illustrative weighting
    scenario, even when a sourced official annual headline rate is available.
    """
    transactions, statement, warnings = _parse_csv(text)
    synthetic_input = synthetic_input or statement.pop("input_is_synthetic")
    specs, headline, cpih, benchmark = _index_parts(indices)
    series = {key: _values(spec) for key, spec in specs.items()}
    fallback = headline or benchmark
    fallback_values = _values(fallback)
    participating = list(series.values()) + [fallback_values]
    if cpih:
        participating.append(_values(cpih))
    common = set.intersection(*(set(values) for values in participating))
    if not common:
        raise PersonalInflationError("Price-index series have no common month.")
    latest = max(common)
    previous = _shift_month(latest, -12)
    if previous not in common:
        raise PersonalInflationError(f"Price data does not reach back 12 months from {latest}; no data was downloaded.")
    rates = {key: values[latest] / values[previous] - 1 for key, values in series.items()}
    fallback_rate = fallback_values[latest] / fallback_values[previous] - 1
    headline_rate = fallback_rate if headline else None
    cpih_rate = (_values(cpih)[latest] / _values(cpih)[previous] - 1) if cpih else None
    headline_reference = None
    candidate = indices.get("headline_reference")
    if candidate:
        period_matches = isinstance(candidate, dict) and candidate.get("start_month") == previous and candidate.get("end_month") == latest
        cpi = candidate.get("cpi_rate") if isinstance(candidate, dict) else None
        cpih_reference = candidate.get("cpih_rate") if isinstance(candidate, dict) else None
        rates_valid = all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value > -1
                          for value in (cpi, cpih_reference))
        if period_matches and rates_valid:
            headline_reference = dict(candidate)
            if headline_rate is None:
                headline_rate = float(cpi)
                fallback_rate = headline_rate
            if cpih_rate is None:
                cpih_rate = float(cpih_reference)
        else:
            warnings.append("The saved headline reference does not match the calculation period or has invalid rates; it was not used.")
    spending = defaultdict(int)
    for item in transactions:
        category = item["category"] if item["category"] in specs else "other"
        spending[category] += item["pence"]
    total = sum(spending.values())
    categories = []
    for category, pence in spending.items():
        weight = pence / total
        rate = fallback_rate if category == "other" else rates[category]
        spec = specs.get(category, {})
        categories.append({"category_id": category, "name": spec.get("name", "Other · all-items CPI fallback" if headline_rate is not None else "Other · demo fallback"), "spending_gbp": pence / 100,
            "weight": weight, "rate": rate, "contribution": weight * rate,
            "index_id": ("ons_cpi_headline_reference" if headline_reference and not headline else fallback.get("id", "all_items")) if category == "other" else spec.get("series_id", spec.get("id", category)),
            "coicop": spec.get("coicop"), "fallback": category == "other"})
    categories.sort(key=lambda item: item["contribution"], reverse=True)
    personal = sum(item["contribution"] for item in categories)
    other_share = spending.get("other", 0) / total
    first = date.fromisoformat(statement["first_date"])
    last = date.fromisoformat(statement["last_date"])
    calendar_months = (last.year - first.year) * 12 + last.month - first.month + 1
    three_month_start = date.fromisoformat(_shift_month(_month(first), 3) + "-01")
    three_month_start = three_month_start.replace(day=min(first.day, calendar.monthrange(three_month_start.year, three_month_start.month)[1]))
    if last < three_month_start:
        warnings.append("The CSV covers fewer than three calendar months; expenditure weights may be skewed by seasonality or one-off purchases.")
    if other_share > .25:
        warnings.append("More than 25% of spending is other/unmapped; the result is unreliable as a personal inflation estimate.")
    all_price_months = sorted(common)
    price_first = date.fromisoformat(all_price_months[0] + "-01")
    price_last_month = date.fromisoformat(all_price_months[-1] + "-01")
    price_last = price_last_month.replace(day=calendar.monthrange(price_last_month.year, price_last_month.month)[1])
    if last < price_first or first > price_last:
        warnings.append("CSV dates do not overlap the price data; its spending weights are being applied to a different historical period.")
    mode = "synthetic_demo" if indices.get("mode") == "synthetic_demo" or not headline else "official_indices"
    if headline_rate is None:
        warnings.append("No matching official all-items CPI/CPIH is available. Other spending uses a synthetic 50/50 chocolate-and-crisps benchmark, not headline inflation.")
    else:
        warnings.append("Other/unmapped spending uses the official all-items CPI annual rate, rather than suitable category-specific indices; broad household-category coverage is still missing.")
    warnings.append("Only explicitly labelled demo chocolate/crisps merchants have category mappings; generic supermarkets and all other merchants remain other. Bank descriptions cannot reveal the contents of a grocery basket.")
    if synthetic_input:
        warnings.append("This input is a fabricated bank-statement scenario, not real transactions.")
    benchmark_rate = (_values(benchmark)[latest] / _values(benchmark)[previous] - 1) if benchmark else None
    prefix = "Demo-weighted inflation" if mode == "synthetic_demo" else "Personal index-weighted inflation"
    comparison = f" vs {headline_rate * 100:.1f}% headline CPI" if headline_rate is not None else f" vs {benchmark_rate * 100:.1f}% synthetic snack benchmark (not CPI)"
    drivers = ", ".join(f"{item['name']} ({item['contribution'] * 100:+.1f}pp)" for item in categories[:2])
    summary = f"{prefix} over {previous} to {latest}: {personal * 100:.1f}%{comparison}. Biggest contributions: {drivers}."
    return {"schema_version": 1, "mode": mode, "input_is_synthetic": synthetic_input, "personal_rate": personal,
        "headline_rate": headline_rate, "cpih_rate": cpih_rate, "benchmark_rate": benchmark_rate, "headline_reference": headline_reference,
        "benchmark_name": benchmark.get("name") if benchmark else None, "start_month": previous, "end_month": latest,
        "total_spending_gbp": total / 100, "categories": categories, "other_share": other_share,
        "observed_price_changes": _observed_changes(transactions, first, last), "warnings": warnings,
        "csv_period": {"first_date": statement["first_date"], "last_date": statement["last_date"], "calendar_months": calendar_months},
        "statement": statement, "exclusions": statement["exclusions"], "summary": summary,
        "method": "Whole-CSV spending weights × category annual index changes; no spending-growth calculation. Other uses the same-period all-items CPI annual rate where present, otherwise the explicitly synthetic demo benchmark. A sourced headline rate does not create missing monthly index levels or broad category mappings.",
        "privacy": "Parsed locally; no external API, raw descriptions or individual transactions are included in results."}


def personal_inflation(csv_path: str | Path, indices_path: str | Path | None = None, *, root: str | Path | None = None, synthetic_input: bool = False) -> dict:
    """Read a bank CSV locally and return JSON-serialisable calculated results."""
    path = Path(csv_path)
    base = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    index_path = Path(indices_path) if indices_path else base / "data/curated/personal-inflation-demo.json"
    try:
        raw = path.read_bytes()
        if len(raw) > 10_000_000:
            raise PersonalInflationError("The CSV is too large; use a file smaller than 10 MB.")
        try:
            text = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = raw.decode("cp1252")
            except UnicodeDecodeError:
                raise PersonalInflationError("The CSV has an unsupported text encoding; save it as UTF-8.") from None
    except OSError:
        raise PersonalInflationError("The bank CSV could not be read; check its path and permissions.") from None
    try:
        indices = json.loads(index_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raise PersonalInflationError("The local price-index bundle is missing or malformed.") from None
    return analyse_csv_text(text, indices, synthetic_input=synthetic_input)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Local personal-inflation calculation: illustrative demo with fixed sourced annual headline references.")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument("--indices", type=Path)
    parser.add_argument("--synthetic-input", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = personal_inflation(args.csv_path, args.indices, synthetic_input=args.synthetic_input)
    except PersonalInflationError as error:
        parser.exit(2, f"Error: {error}\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
