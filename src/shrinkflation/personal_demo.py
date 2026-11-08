"""Generate explicitly synthetic statement fixtures from the saved grocery evidence.

No network requests, personal records or learned transaction labels are created.
The category indices remain original ONS observations; published headline annual
rates are copied from a dated, source-linked local reference without inventing
an all-items index history.
"""
from __future__ import annotations

import csv
import io
import json
from datetime import date
from pathlib import Path


def _csv(headers: list[str], rows: list[list[str]], delimiter: str = ',') -> str:
    output = io.StringIO(newline='')
    writer = csv.writer(output, delimiter=delimiter, lineterminator='\n')
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue()


def _month(start: date, offset: int) -> date:
    number = start.year * 12 + start.month - 1 + offset
    return date(number // 12, number % 12 + 1, 1)


def build_demo(root: Path) -> dict:
    # Reuse the repository's ONS monthly parser; annual/quarterly rows stay excluded.
    from .category_data import _parse_ons
    root = Path(root)
    categories = []
    for key, name, series in [('chocolate', 'Chocolate', 'l79x'), ('crisps', 'Crisps', 'l79r')]:
        pointer = json.loads((root / f'data/raw/ons-category/latest-{series}.json').read_text())
        values, metadata = _parse_ons(root / pointer['snapshot_path'])
        categories.append({'id': key, 'name': name, 'series_id': series.upper(),
            'coicop': '01.1.8.3' if key == 'chocolate' else '01.1.7.5',
            'data_kind': 'observed_ons', 'source_file': pointer['snapshot_path'],
            'source_url': pointer['url'], 'source_sha256': pointer['sha256'],
            'source_title': metadata['Title'],
            'values': {month.strftime('%Y-%m'): value for month, value in values.items()}})
    common = set(categories[0]['values']) & set(categories[1]['values'])
    latest = max(common)
    target = date.fromisoformat(latest + '-01')
    base = date(target.year - 1, target.month, 1).strftime('%Y-%m')
    if base not in common:
        raise ValueError('Saved price data has no same-month observation twelve months earlier.')
    benchmark_values = {month: sum(.5 * 100 * c['values'][month] / c['values'][base] for c in categories)
                        for month in sorted(common)}
    reference = json.loads((root / 'data/curated/uk-inflation-reference.json').read_text())
    samples = [
        {'id': 'snack-club', 'name': 'Snack clubs · 13 months', 'path': '/data/personal-samples/snack-club.csv',
         'synthetic': True, 'description': 'Fictional monthly subscriptions, income, refunds, transfers, savings and cash. Chocolate amounts reuse reported Revels prices; other spending is invented.'},
        {'id': 'mixed-household', 'name': 'Mixed household · debit / credit', 'path': '/data/personal-samples/mixed-household.csv',
         'synthetic': True, 'description': 'Fictional household costs with a high other share. Rent and supermarket spending have no suitable real index in this repository.'},
        {'id': 'short-statement', 'name': 'Short statement · warning example', 'path': '/data/personal-samples/short-statement.csv',
         'synthetic': True, 'description': 'A fictional two-month, semicolon-delimited statement with UK currency formatting.'},
    ]
    bundle = {'schema_version': 1, 'mode': 'synthetic_demo',
        'title': 'Synthetic bank-statement demonstration', 'categories': categories,
        'benchmark': {'id': 'demo_snack_basket', 'name': 'Synthetic 50/50 snack benchmark',
            'synthetic': True, 'base_month': base, 'reference_weights': {'chocolate': .5, 'crisps': .5},
            'values': benchmark_values,
            'method': f'Each saved ONS series is rebased to {base}=100; the benchmark is a fictional fixed 50/50 basket.',
            'scope': 'Not official all-items CPI, CPIH, or a representative household cost-of-living index.'},
        'headline': None, 'cpih': None, 'headline_reference': reference, 'samples': samples,
        'classification': {'kind': 'local_demo_rules',
            'description': 'Only explicit DEMO CHOCOLATE SHOP/CLUB and DEMO CRISPS SHOP/CLUB descriptions map to snack indices. General supermarkets and household costs map to other.'},
        'limitations': ['All example statements and payment histories are synthetic; no real bank records are included.',
            'Chocolate and crisps indices are saved ONS observations. Broader household category indices and official expenditure weights are unavailable.',
            'September 2026 headline CPI (3.5%) and CPIH (3.6%) are fixed, published ONS annual-rate references, released 21 October 2026; no all-items index history is supplied.',
            'For a matching comparison period, other spending uses the published all-items CPI annual rate as a proxy. The fictional 50/50 snack benchmark remains separate.',
            'This demonstration cannot establish broad household personal inflation from real bank statements.',
            'Recurring payment amount changes may reflect usage, quantities or plan changes; they are reported separately.']}
    cases = json.loads((root / 'data/curated/snack-cases.json').read_text())['cases']
    revels = next(c for c in cases if c['id'] == 'revels-uk-pouch-2025')
    old = revels['old']['price_gbp']
    new = revels['new']['price_gbp']
    rows = []
    start = date(target.year - 1, target.month, 1)
    for offset in range(13):
        m = _month(start, offset)
        d = lambda day: f'{day:02d}/{m.month:02d}/{m.year}'
        rows += [[d(15), 'DEMO CHOCOLATE CLUB', f'-£{new if offset == 12 else old:.2f}', 'DEBIT', 'true'],
                 [d(18), 'DEMO CRISPS CLUB', '-£1.50', 'DEBIT', 'true'],
                 [d(25), 'DEMO EMPLOYER PAYROLL', '£2,400.00', 'CREDIT', 'true'],
                 [d(26), 'OWN ACCOUNT TRANSFER', '-£200.00', 'TRANSFER', 'true'],
                 [d(27), 'TRANSFER TO SAVINGS', '-£300.00', 'TRANSFER', 'true'],
                 [d(28), 'ATM CASH WITHDRAWAL', '-£20.00', 'CASH', 'true']]
    rows.append([f'20/{target.month:02d}/{target.year}', 'DEMO SHOP REFUND', '£1.50', 'CREDIT', 'true'])
    texts = {'snack-club.csv': '\ufeff' + _csv(['Date', 'Description', 'Amount', 'Type', 'Synthetic'], rows)}
    rows = []
    for offset in range(12):
        m = _month(start, offset + 1)
        d = lambda day: f'{day:02d}/{m.month:02d}/{m.year}'
        for day, merchant, debit, credit, kind in [(1, 'DEMO RENT', '£925.00', '', 'BANK TRANSFER'),
            (3, 'TESCO STORES', '£80.00', '', 'DEBIT'), (6, 'DEMO ENERGY BILL', '£85.00', '', 'DIRECT DEBIT'),
            (10, 'DEMO CHOCOLATE SHOP', f'£{new:.2f}', '', 'DEBIT'), (12, 'DEMO CRISPS SHOP', '£1.50', '', 'DEBIT'),
            (25, 'DEMO EMPLOYER PAYROLL', '', '£3,100.00', 'CREDIT'),
            (26, 'TRANSFER TO OWN ACCOUNT', '£250.00', '', 'TRANSFER'),
            (27, 'ATM CASH WITHDRAWAL', '£30.00', '', 'CASH')]:
            rows.append([d(day), merchant, debit, credit, kind, 'true'])
    texts['mixed-household.csv'] = _csv(['Transaction Date', 'Details', 'Money Out (£)', 'Money In (£)', 'Transaction Type', 'Synthetic'], rows)
    # Deliberate mojibake currency prefix exercises bank-export decoding without real data.
    previous = _month(target, -1)
    texts['short-statement.csv'] = _csv(['Booking Date', 'Transaction Description', 'Amount GBP', 'Type', 'Synthetic'], [
        [f'05/{previous.month:02d}/{previous.year}', 'DEMO CHOCOLATE SHOP', '-Â£3.30', 'DEBIT', 'true'],
        [f'06/{previous.month:02d}/{previous.year}', 'DEMO CRISPS SHOP', '(£1.50)', 'DEBIT', 'true'],
        [f'02/{target.month:02d}/{target.year}', 'SAVINGS SUPERMARKET', '-£10.00', 'DEBIT', 'true'],
        [f'07/{target.month:02d}/{target.year}', 'DEMO CRISPS SHOP', '£1.50 DR', 'DEBIT', 'true'],
        [f'25/{target.month:02d}/{target.year}', 'DEMO EMPLOYER PAYROLL', '£1,500.00 CR', 'CREDIT', 'true'],
    ], delimiter=';')
    for folder in [root / 'data/synthetic/personal-inflation', root / 'data/app-public/data/personal-samples']:
        folder.mkdir(parents=True, exist_ok=True)
        for name, text in texts.items():
            (folder / name).write_text(text, encoding='utf-8')
    for path in [root / 'data/curated/personal-inflation-demo.json', root / 'data/app-public/data/personal-inflation-demo.json']:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(bundle, indent=2, allow_nan=False) + '\n')
    return {'latest_month': latest, 'comparison_month': base, 'samples': len(samples),
            'benchmark_rate': benchmark_values[latest] / benchmark_values[base] - 1,
            'official_headline_available': reference.get('start_month') == base and reference.get('end_month') == latest}


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    print(json.dumps(build_demo(args.root.resolve())))


if __name__ == '__main__':
    main()
