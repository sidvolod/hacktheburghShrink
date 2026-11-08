"""Conservative declared-quantity extraction. No density assumptions."""
from __future__ import annotations

import re
import math

NUMBER = r"\d+(?:[.,]\d+)?"
UNIT = r"(?:kilograms?|kgs?|grams?|gms?|g|millilitres?|milliliters?|ml|centilitres?|cl|litres?|liters?|ltr|lt|l)"
MEASURE = re.compile(rf"(?<![\w.])({NUMBER})\s*({UNIT})(?![\w])", re.I)
MULTI = re.compile(rf"(?<!\w)(\d+)\s*[x×*]\s*({NUMBER})\s*({UNIT})(?!\w)", re.I)
REVERSE = re.compile(rf"(?<!\w)({NUMBER})\s*({UNIT})\s*[x×*]\s*(\d+)(?!\w)", re.I)
COUNTS = re.compile(r"(?<!\w)(\d+)\s*(?:pack|pk|bars?|eggs?|pieces?|pcs|rolls?|sachets?|bags?|cans?|bottles?)(?!\w)", re.I)


def measure(value: str, unit: str) -> tuple[float, str]:
    number = float(value.replace(",", "."))
    unit = unit.lower()
    if unit.startswith("k"):
        return number * 1000, "mass"
    if unit.startswith("g"):
        return number, "mass"
    if unit.startswith("m"):
        return number, "volume"
    if unit.startswith("c"):
        return number * 10, "volume"
    return number * 1000, "volume"


def parse_quantity(text: str | None) -> dict:
    result = {"raw_quantity": text, "total_mass_g": None, "total_volume_ml": None,
        "item_mass_g": None, "item_volume_ml": None, "pack_count": None,
        "quantity_status": "missing"}
    if not text or not str(text).strip():
        return result
    text = str(text).lower()
    result["quantity_status"] = "unparsed"
    # Do not guess bundle arithmetic, range endpoints or ambiguous thousands separators.
    if (len(list(MULTI.finditer(text))) + len(list(REVERSE.finditer(text))) > 1
        or re.search(r"\d+\s*[x×*]\s*\d+\s*[x×*]", text)
        or re.search(rf"-\s*{NUMBER}\s*{UNIT}(?!\w)", text, re.I)
        or re.search(rf"\d+,\d{{3}}(?:[.,]\d+)?\s*{UNIT}(?!\w)", text, re.I)):
        result["quantity_status"] = "ambiguous"
        return result
    found = list(MEASURE.finditer(text))
    multi = MULTI.search(text)
    reverse = REVERSE.search(text) if not multi else None
    if multi or reverse:
        if multi:
            count, amount, unit = multi.groups()
            span = multi.span()
        else:
            amount, unit, count = reverse.groups()
            span = reverse.span()
        count = int(count)
        value, dimension = measure(amount, unit)
        total = value * count
        extras = [measure(*m.groups()) for m in found if not (m.start() >= span[0] and m.end() <= span[1])]
        if count <= 0 or value <= 0 or not math.isfinite(total) or any(d != dimension or abs(v - total) > 0.01 for v, d in extras):
            result["quantity_status"] = "ambiguous"
            return result
        result["pack_count"] = count
        result["item_mass_g" if dimension == "mass" else "item_volume_ml"] = value
    elif found:
        values = [measure(*m.groups()) for m in found]
        value, dimension = values[0]
        if value <= 0 or not math.isfinite(value) or any(d != dimension or abs(v - value) > 0.01 for v, d in values[1:]):
            result["quantity_status"] = "ambiguous"
            return result
        total = value
        count_match = COUNTS.search(text)
        if count_match:
            # e.g. '4 pack 100g' does not establish whether 100g is per item or total.
            result["pack_count"] = int(count_match.group(1))
            if result["pack_count"] > 1:
                result["quantity_status"] = "ambiguous"
                return result
    else:
        count_match = COUNTS.search(text)
        if count_match and int(count_match.group(1)) > 0:
            result["pack_count"] = int(count_match.group(1))
            result["quantity_status"] = "count_only"
        return result
    result["total_mass_g" if dimension == "mass" else "total_volume_ml"] = total
    result["quantity_status"] = "parsed"
    return result
