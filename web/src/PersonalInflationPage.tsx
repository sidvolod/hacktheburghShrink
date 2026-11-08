import { useEffect, useRef, useState } from 'react';
import { headlineReferenceForPeriod, personalInflation, StatementError } from './personalInflation';
import type { InflationBundle, InflationResult } from './personalInflation';
import './personal-inflation.css';

const money = (value: number) => new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(value);
const percent = (value: number, signed = false) => `${signed && value > 0 ? '+' : ''}${(value * 100).toFixed(1)}%`;
const month = (value: string) => new Date(`${value}-15T12:00:00Z`).toLocaleDateString('en-GB', { month: 'short', year: 'numeric', timeZone: 'UTC' });
const exclusions: Record<string, string> = { income: 'Income', refund: 'Refunds / reversals', own_transfer: 'Own-account transfers', savings: 'Savings movements', cash_withdrawal: 'Cash withdrawals · uncategorised' };

export function PersonalInflationPage() {
  const [bundle, setBundle] = useState<InflationBundle | null>(null);
  const [loadError, setLoadError] = useState('');
  const [error, setError] = useState('');
  const [sampleId, setSampleId] = useState('');
  const [result, setResult] = useState<InflationResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [inputLabel, setInputLabel] = useState('');
  const fileInput = useRef<HTMLInputElement>(null);
  const request = useRef(0);
  useEffect(() => {
    const controller = new AbortController();
    fetch('/data/personal-inflation-demo.json', { signal: controller.signal }).then(response => {
      if (!response.ok) throw new Error('The prepared demo price indices could not be loaded.');
      return response.json();
    }).then((value: InflationBundle) => {
      if (value.schema_version !== 1 || !value.categories?.length || !value.samples?.length) throw new Error('The prepared demo data is incomplete.');
      setBundle(value); setSampleId(value.samples[0].id);
    }).catch(reason => { if (reason.name !== 'AbortError') setLoadError('The demonstration data could not be loaded. Try refreshing this page.'); });
    return () => { controller.abort(); request.current++; };
  }, []);
  async function loadSample() {
    if (!bundle) return;
    const sample = bundle.samples.find(item => item.id === sampleId); if (!sample) return;
    const token = ++request.current; setBusy(true); setError('');
    try {
      const response = await fetch(sample.path); if (!response.ok) throw new StatementError('This synthetic CSV could not be loaded.');
      const text = await response.text(); const value = personalInflation(text, bundle, { syntheticInput: true });
      if (token === request.current) { setResult(value); setInputLabel(sample.name); if (fileInput.current) fileInput.current.value = ''; }
    } catch (reason) { if (token === request.current) { setError(reason instanceof StatementError ? reason.message : 'The synthetic statement could not be read.'); setResult(null); } }
    finally { if (token === request.current) setBusy(false); }
  }
  async function loadFile(file: File | undefined) {
    if (!file || !bundle) return;
    const token = ++request.current; setBusy(true); setError(''); setResult(null);
    try {
      if (file.size > 2 * 1024 * 1024) throw new StatementError('Choose a CSV smaller than 2 MB. No file was uploaded.');
      const text = await file.text(); const value = personalInflation(text, bundle);
      if (token === request.current) { setResult(value); setInputLabel('Your local CSV'); }
    } catch (reason) { if (token === request.current) setError(reason instanceof StatementError ? reason.message : 'This CSV could not be read. Check its date, description and amount columns.'); }
    finally { if (token === request.current) setBusy(false); }
  }
  function clear() { request.current++; setResult(null); setError(''); setInputLabel(''); setBusy(false); if (fileInput.current) fileInput.current.value = ''; }
  function download() {
    if (!result) return;
    const blob = new Blob([JSON.stringify(result, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob), anchor = document.createElement('a'); anchor.href = url; anchor.download = 'personal-inflation-demo-result.json'; anchor.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  const latestMonth = bundle ? Object.keys(bundle.benchmark.values).filter(date => bundle.categories.every(category => category.values[date] > 0)).sort().at(-1) : null;
  const officialReference = result ? result.headline_reference : latestMonth ? headlineReferenceForPeriod(bundle?.headline_reference, `${Number(latestMonth.slice(0, 4)) - 1}${latestMonth.slice(4)}`, latestMonth) : null;
  return <div className="page-shell personal-page">
    <section className="hero"><div><p className="eyebrow"><span className="tiny-cross">✳</span> Same prices. Different baskets.</p><h1>Your basket.<br /><em>Your inflation?</em></h1><p className="hero-description">Explore how spending weights change the answer.<br />A clearly labelled demo using two real snack indices.</p></div><div className="personal-hero-note"><span className="note-number">04 / PERSONAL INFLATION · DEMO</span><strong>A working calculation.<br />A deliberately narrow dataset.</strong>Chocolate and crisps are observed ONS indices. Bank statements are synthetic examples. Broader household inflation needs broader price data.</div></section>
    <div className="personal-demo-note">{officialReference ? <><strong>Demo spending, published headline reference.</strong> The statements and merchant rules are synthetic; the only category indices are chocolate and crisps. For {month(officialReference.start_month)} → {month(officialReference.end_month)}, official CPI is <strong>{percent(officialReference.cpi_rate)}</strong> and CPIH is <strong>{percent(officialReference.cpih_rate)}</strong>. Other spending uses CPI as an aggregate fallback. This narrow demonstration cannot tell you your real household inflation.</> : <><strong>Demo reference, not official personal inflation.</strong> No matching official CPI or CPIH reference is available. The comparison is a <strong>synthetic 50/50 chocolate-and-crisps benchmark</strong>. Unmapped spending uses that demo rate. This cannot tell you your real household inflation.</>}</div>
    {loadError ? <div className="personal-error" role="alert">{loadError}</div> : !bundle ? <p role="status" className="personal-empty">Loading the existing price indices…</p> : <>
      <section className="personal-input" aria-labelledby="personal-input-title"><div><span className="eyebrow">Start with a sample</span><h2 id="personal-input-title">Try a synthetic statement.</h2><p>Three made-up spending patterns, priced against the real chocolate and crisps histories already in this project.</p><label>Synthetic example<select value={sampleId} onChange={event => setSampleId(event.target.value)}>{bundle.samples.map(sample => <option key={sample.id} value={sample.id}>{sample.name}</option>)}</select></label><p>{bundle.samples.find(sample => sample.id === sampleId)?.description}</p><div className="personal-input-actions"><button className="button dark" onClick={loadSample} disabled={busy}>Calculate sample</button><a className="button" href={bundle.samples.find(sample => sample.id === sampleId)?.path} download>Download sample CSV</a></div></div>
      <div><span className="eyebrow">Or inspect your own format</span><h2>Keep it on your device.</h2><p>A local CSV can test the parser. Only explicit demo snack labels are mapped; a normal bank statement will mostly be “other”.</p><label>Choose bank statement CSV<input ref={fileInput} type="file" accept=".csv,text/csv" onChange={event => { void loadFile(event.target.files?.[0]); }} /></label><p className="personal-private">Processed in browser memory. No transaction upload, external categorisation, raw-description logs or saved statement. Max 2 MB. Clear removes the result from this page.</p><div className="personal-input-actions"><button className="button" onClick={clear}>Clear statement</button></div></div></section>
      {busy && <p className="personal-empty" role="status">Calculating locally…</p>}{error && <div className="personal-error" role="alert">{error}</div>}
      {result && <section className="personal-results" aria-labelledby="personal-result-title"><div className="personal-result-header"><div><span className="personal-result-label">{result.input_is_synthetic ? 'Synthetic statement' : 'Local statement'} · demo reference</span><h2 id="personal-result-title">One year. Your spending mix.</h2><p>{inputLabel} · weights from {result.csv_period.first_date} to {result.csv_period.last_date}<br />Price comparison: {month(result.start_month)} → {month(result.end_month)}</p></div><button className="button" onClick={download}>Download aggregate result</button></div>
      <div className="personal-metrics"><div><span className="eyebrow">Your demo-weighted rate</span><strong data-testid="personal-rate">{percent(result.personal_rate)}</strong><p>Weighted category price-index changes.<br />{money(result.total_spending_gbp)} of eligible spending.</p></div><div><span className="eyebrow">Synthetic snack benchmark</span><strong>{percent(result.benchmark_rate)}</strong><p>50% chocolate + 50% crisps.<br />Not official CPI expenditure weights.</p></div><div><span className="eyebrow">Official headline CPI</span><strong data-testid="personal-headline-rate">{result.headline_rate == null ? 'Unavailable' : percent(result.headline_rate)}</strong>{result.headline_reference ? <p>CPIH: <strong className="personal-inline-rate">{percent(result.cpih_rate!)}</strong><br />Fixed published annual rates, not live data.<br /><a href={result.headline_reference.source_url} target="_blank" rel="noreferrer">ONS · released {result.headline_reference.release_date}</a></p> : <p>No matching all-items annual reference is available. No official comparison is claimed.</p>}</div></div>
      <p className="personal-summary">{result.summary}</p><ul className="personal-warning-list" aria-label="Calculation warnings">{result.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>
      <section className="personal-contributions"><h3>What drives the result?</h3><p>Weights use all eligible spending across your CSV. Contributions sum to the rate above. Other spending: <strong data-testid="personal-other-share">{percent(result.other_share)}</strong>.</p>{result.categories.map(category => <article className="personal-category" key={category.category_id}><div className="personal-category-head"><h4>{category.name}</h4><strong>{category.contribution > 0 ? '+' : ''}{(category.contribution * 100).toFixed(2)}pp</strong></div><div className="personal-category-bar" aria-hidden="true"><span style={{ width: `${category.weight * 100}%` }} /></div><dl><div><dt>Spending</dt><dd>{money(category.spending_gbp)}</dd></div><div><dt>Basket weight</dt><dd>{percent(category.weight)}</dd></div><div><dt>Year-on-year index rate</dt><dd>{percent(category.rate, true)}</dd></div></dl>{category.category_id === 'other' && <small>{result.headline_reference ? 'Official all-items CPI fallback; no category-specific household index is available.' : 'Synthetic benchmark fallback; no household category index is available.'}</small>}</article>)}</section>
      <div className="personal-secondary"><section className="personal-observed"><h3>Observed payment changes</h3><p>Separate from the inflation calculation. Matching monthly payments a year apart may change because of price, usage or package.</p>{result.observed_price_changes.length ? <ul>{result.observed_price_changes.map(item => <li key={item.merchant}><span>{item.merchant}<small>{money(item.old_amount_gbp)} → {money(item.new_amount_gbp)}<br />{month(item.from_month)} → {month(item.to_month)} · {item.occurrences} payments</small></span><strong>{percent(item.change, true)}</strong></li>)}</ul> : <p className="personal-empty">No qualifying recurring payment found. Detection needs 13+ calendar months and a consistent monthly pattern present in both matching months.</p>}</section><section className="personal-exclusions"><h3>Left out of the basket</h3><p>These amounts do not affect the spending weights. Cash is flagged because its eventual purchases are unknown.</p><ul>{Object.entries(result.exclusions).map(([key, item]) => <li key={key}><span>{exclusions[key]}<small>{item.count} transaction{item.count === 1 ? '' : 's'}</small></span><strong>{money(item.amount_gbp)}</strong></li>)}</ul></section></div>
      </section>}
      <details className="personal-method"><summary>How this demo works, and its limits</summary><p><code>weight = category spending / all eligible spending</code><br /><code>category rate = index(latest month) / index(12 months earlier) − 1</code><br /><code>demo-weighted rate = sum(weight × category rate)</code></p><p>Spending growth is not inflation. The whole CSV supplies a spending mix; the existing price indices supply the annual changes. This is descriptive weighting, not a trained forecasting model.</p>{officialReference && <p>The official comparison is a fixed annual CPI/CPIH reference for {month(officialReference.start_month)} to {month(officialReference.end_month)}, published {officialReference.release_date}. It is not a fetched live feed or an all-items index history. <a href={officialReference.source_url} target="_blank" rel="noreferrer">{officialReference.source_title}</a>. Other spending receives the all-items CPI rate; the synthetic snack basket remains a separate secondary benchmark.</p>}<ul>{bundle.categories.map(category => <li key={category.id}>{category.name}: ONS {category.series_id}, COICOP {category.coicop}; {Object.keys(category.values).sort()[0]} to {Object.keys(category.values).sort().at(-1)}.</li>)}{bundle.limitations.map(note => <li key={note}>{note}</li>)}</ul><p>Only descriptions containing DEMO CHOCOLATE SHOP/CLUB or DEMO CRISPS SHOP/CLUB are mapped. Tesco, rent, transport, subscriptions and all other merchants remain other. No transaction descriptions leave this page. Downloaded aggregate results include normalised recurring merchant labels, but no raw transaction rows.</p></details>
    </>}
  </div>;
}
