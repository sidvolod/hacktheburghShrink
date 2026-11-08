import { useEffect, useMemo, useRef, useState } from 'react';
import type { CSSProperties, ReactNode } from 'react';
import type { CaseVersion, ComparisonGroup, DemoData, ProductHistory, RecipeHistory, SnackCase, Source } from './types';
import { comparableUnitPriceChange, isReviewedReplacementPair, massChange, observationIndex, unitPrice } from './math';
import { CategoryForecastPage } from './CategoryForecastPage';
import { RevealChallenge, GhostWeightOverlay } from './RevealChallenge';
import { WholePackPlanner } from './WholePackPlanner';

type Page = 'history' | 'compare' | 'forecast';
const money = (value: number | null | undefined, digits = 2) => value == null || !Number.isFinite(value) ? 'Not reported' : new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP', minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
const formatMass = (value: number) => new Intl.NumberFormat('en-GB', { maximumFractionDigits: 3 }).format(value);
const percent = (value: number | null | undefined, signed = false) => value == null || !Number.isFinite(value) ? '—' : `${signed && value > 0 ? '+' : ''}${(value * 100).toFixed(1)}%`;
const number = (value: unknown) => typeof value === 'number' ? new Intl.NumberFormat('en-GB', { notation: value >= 1000000 ? 'compact' : 'standard', maximumFractionDigits: 1 }).format(value) : '—';
const date = (value: string, long = false) => {
  const parsed = new Date(value.slice(0, 10) + 'T12:00:00');
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleDateString('en-GB', { day: 'numeric', month: long ? 'long' : 'short', year: 'numeric' });
};
const readable = (value: string) => value.replaceAll('_', ' ').replaceAll('-', ' ');
const route = (): Page => ['history', 'compare', 'forecast'].includes(location.hash.slice(1)) ? location.hash.slice(1) as Page : 'history';

function Icon({ name, size = 20, ...props }: { name: 'arrow' | 'search' | 'external' | 'close' | 'check' | 'clock' | 'info' | 'chart' | 'chevron'; size?: number; className?: string }) {
  const paths = {
    arrow: <><path d="M4 12h15M13 5l7 7-7 7" /></>,
    search: <><circle cx="10.5" cy="10.5" r="6.5" /><path d="m16 16 5 5" /></>,
    external: <><path d="M14 4h6v6M20 4 10 14M10 4H5a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5" /></>,
    close: <path d="m5 5 14 14M19 5 5 19" />,
    check: <path d="m5 12 4 4L19 6" />,
    clock: <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>,
    info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v6M12 7v1" /></>,
    chart: <><path d="M4 4v16h17M7 15l4-5 4 3 5-7" /></>,
    chevron: <path d="m9 5 7 7-7 7" />,
  };
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name]}</svg>;
}

function Mark({ small = false }: { small?: boolean }) {
  return <span className={`brand-mark ${small ? 'small' : ''}`} aria-hidden="true"><i /><i /><i /><i /></span>;
}

function App() {
  const [data, setData] = useState<DemoData | null>(null);
  const [error, setError] = useState('');
  const [page, setPage] = useState<Page>(route);
  const [selected, setSelected] = useState('');
  const [evidence, setEvidence] = useState<{ snack: SnackCase; opener: HTMLButtonElement } | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    fetch('/data/demo.json', { signal: controller.signal }).then(response => {
      if (!response.ok) throw new Error(`The prepared data could not be loaded (${response.status}).`);
      return response.json();
    }).then((value: DemoData) => {
      if (!Array.isArray(value.cases) || !value.cases.length || !value.evaluation) throw new Error('The prepared demo data is incomplete. Run the local launch command to export it.');
      setData(value);
      setSelected(value.cases.find(item => item.id === 'maltesers-uk-pouch-2017')?.id ?? value.cases.find(item => /doritos/i.test(item.name))?.id ?? value.cases[0].id);
    }).catch(reason => { if (reason.name !== 'AbortError') setError(reason.message); });
    return () => controller.abort();
  }, []);
  useEffect(() => { const listener = () => setPage(route()); window.addEventListener('hashchange', listener); return () => window.removeEventListener('hashchange', listener); }, []);
  useEffect(() => { const listener = (event: KeyboardEvent) => { if (event.key === '/' && page === 'history' && !(event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement)) { event.preventDefault(); document.getElementById('case-search')?.focus(); } }; window.addEventListener('keydown', listener); return () => window.removeEventListener('keydown', listener); }, [page]);
  const navigate = (next: Page) => { setPage(next); location.hash = next; window.scrollTo({ top: 0, behavior: 'instant' }); };
  const closeEvidence = () => { const opener = evidence?.opener; setEvidence(null); requestAnimationFrame(() => { if (opener?.isConnected) opener.focus({ preventScroll: true }); }); };
  const activeCase = data?.cases.find(item => item.id === selected) ?? data?.cases[0];
  return <>
    <a className="skip-link" href="#main" onClick={event => { event.preventDefault(); const main = document.getElementById('main'); main?.focus({ preventScroll: true }); main?.scrollIntoView({ block: 'start' }); }}>Skip to content</a>
    <header className="site-header">
      <a className="wordmark" href="#history" onClick={() => navigate('history')} aria-label="shrincflationTrack home"><Mark /><span>shrincflation<span className="wordmark-track">Track</span><span className="brand-dot">.</span></span></a>
      <nav aria-label="Main navigation">
        <button aria-current={page === 'history' ? 'page' : undefined} onClick={() => navigate('history')}>The detective</button>
        <button aria-current={page === 'compare' ? 'page' : undefined} onClick={() => navigate('compare')}>Price comparison</button>
        <button aria-current={page === 'forecast' ? 'page' : undefined} onClick={() => navigate('forecast')}>Forecast lab<span className={`nav-status ${data?.category_forecast?.categories.length ? 'available' : ''}`} aria-label={data?.category_forecast?.categories.length ? 'category forecasts available' : 'forecast unavailable'} /></button>
      </nav>
      <span className="header-locale"><span className="live-dot" /> UK grocery evidence</span>
    </header>
    <main id="main" tabIndex={-1}>
      {error ? <div className="loading-state"><Icon name="info" size={32} /><h1>The evidence is taking a moment.</h1><p>{error}</p><button className="button primary" onClick={() => location.reload()}>Try again <Icon name="arrow" /></button></div> : !data || !activeCase ? <div className="loading-state" role="status"><Mark /><p>Opening the case files…</p></div> : <>
        {page === 'history' && <HistoryPage data={data} activeCase={activeCase} selected={selected} setSelected={setSelected} onEvidence={(snack, opener) => setEvidence({ snack, opener })} navigate={navigate} />}
        {page === 'compare' && <ComparePage groups={data.comparisons} />}
        {page === 'forecast' && <ForecastPage data={data} />}
      </>}
    </main>
    <footer className="site-footer"><div><Mark small /><span>Small changes. A clearer picture.</span></div><p>Monthly grocery outcomes. Weekly commodity inputs.</p><span>Built from public evidence · {data ? date(data.generated_at) : 'UK'}</span></footer>
    {evidence && <EvidenceDialog snack={evidence.snack} onClose={closeEvidence} />}
  </>;
}

function HistoryPage({ data, activeCase, selected, setSelected, onEvidence, navigate }: { data: DemoData; activeCase: SnackCase; selected: string; setSelected: (id: string) => void; onEvidence: (item: SnackCase, opener: HTMLButtonElement) => void; navigate: (page: Page) => void }) {
  const [query, setQuery] = useState('');
  const filtered = data.cases.filter(item => `${item.name} ${item.brand} ${item.retailer ?? ''} ${item.reported_year ?? ''}`.toLowerCase().includes(query.toLowerCase()));
  return <div className="page-shell">
    <section className="hero history-hero">
      <div><p className="eyebrow"><span className="tiny-cross">✳</span> A closer look at the everyday</p><h1>Your memory<br />was <em>right.</em></h1><p className="hero-description">That snack really did get smaller.<br className="desktop-only" /> Follow the evidence. See what your money buys.</p></div>
      <div className="hero-aside"><div className="editorial-note"><span className="note-number">01 / THE DETECTIVE</span><p>Same familiar names.<br />A different amount inside.</p><span className="note-rule" /><span>Reported changes, original sources,<br />and the price of every 100 grams.</span></div><div className="hero-data"><strong>{data.cases.length.toString().padStart(2, '0')}</strong><span>documented<br />case files</span><div className="round-arrow"><Icon name="arrow" size={27} /></div></div></div>
    </section>
    <RevealChallenge cases={data.cases} onEvidence={onEvidence} />
    <section className="detective-grid" aria-label="Historical shrinkflation cases">
      <aside className="case-sidebar">
        <div className="section-caption"><span>OPEN A CASE FILE</span><span>{data.cases.length.toString().padStart(2, '0')}</span></div>
        <label className="search-field"><Icon name="search" size={18} /><input id="case-search" value={query} onChange={event => setQuery(event.target.value)} placeholder="Find a familiar snack" aria-label="Search case files" /><kbd>/</kbd></label>
        <div className="case-list">
          {filtered.map((item, index) => <button className={`case-button ${selected === item.id ? 'selected' : ''}`} key={item.id} onClick={() => setSelected(item.id)} aria-pressed={selected === item.id}>
            <span className={`case-monogram ${brandClass(item.name)}`}>{initials(item.brand || item.name)}</span><span className="case-button-text"><strong>{shortName(item.name)}</strong><span>{formatMass(item.old.mass_g)}g <span aria-hidden="true">→</span> {formatMass(item.new.mass_g)}g <span className="case-type">{item.reported_year ? `${item.reported_year} report` : item.category}</span></span></span><Icon name="chevron" size={17} />
            <span className="sr-only">Case {index + 1}: {item.name}</span>
          </button>)}
          {!filtered.length && <p className="empty-search">No case matches “{query}”. Try a product or brand name.</p>}
        </div>
        <div className="sidebar-note"><Icon name="info" size={17} /><p>A case file records a reported change. It doesn’t mean every size on sale replaced another.</p></div>
      </aside>
      <CaseDetail snack={activeCase} onEvidence={opener => onEvidence(activeCase, opener)} />
    </section>
    {Boolean(data.recipe_findings?.length) && <section className="recipe-findings" aria-labelledby="recipe-detective-title"><div className="history-heading"><div><span className="eyebrow">The recipe detective</span><h2 id="recipe-detective-title">What changed inside?</h2><p>Compare historical ingredient declarations with a later source.</p></div></div>{data.recipe_findings?.map(finding => <article className="recipe-finding" key={finding.id}><div className="recipe-finding-heading"><span className={`case-monogram ${brandClass(finding.name)}`}>{initials(finding.brand)}</span><h3>{finding.name}</h3><span className="pill subtle">Ingredient declarations</span></div><RecipeComparison recipe={finding.recipe_history} /><details className="recipe-evidence-details"><summary>Evidence details</summary><ul className="limitations-list">{finding.recipe_history.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></details></article>)}</section>}
    <PriceHistory histories={data.histories} />
    <section className="next-step"><span className="eyebrow">The next useful question</span><h2>What does better value<br />look like on the shelf?</h2><button className="button dark" onClick={() => navigate('compare')}>Compare dated prices <Icon name="arrow" /></button></section>
  </div>;
}

function CaseDetail({ snack, onEvidence }: { snack: SnackCase; onEvidence: (opener: HTMLButtonElement) => void }) {
  const change = comparableUnitPriceChange(snack.old, snack.new, snack.unit_price_change_fraction);
  const shrink = massChange(snack.old.mass_g, snack.new.mass_g);
  const linked = isReviewedReplacementPair(snack.family_link);
  const priceStory = change == null ? 'A comparable price pair is unavailable. The size change is documented.' : snack.new.price_gbp === snack.old.price_gbp ? (/rrp|recommended/i.test(snack.new.price_basis) ? 'The recommended retail price stayed the same. Each gram cost more.' : 'The reported price stayed the same. Each gram cost more.') : (snack.new.price_gbp ?? 0) < (snack.old.price_gbp ?? 0) ? (change > 0 ? 'The pack price fell, but each gram still cost more.' : 'The reported pack price fell alongside the size.') : 'A smaller pack and a higher reported price add up.';
  return <article className="case-detail" key={snack.id}>
    <div className="case-heading"><div><p className="eyebrow muted">The evidence, unpacked</p><h2>{snack.name}</h2><p className="case-meta">{snack.format && <>{snack.format} <span>·</span> </>}{snack.retailer || 'UK reported change'}</p></div><button className="source-count" onClick={event => onEvidence(event.currentTarget)}><span className="source-check"><Icon name="check" size={14} /></span><span>{snack.sources.length} source{snack.sources.length === 1 ? '' : 's'}<small>Follow the evidence</small></span><Icon name="external" size={14} /></button></div>
    <div className="version-comparison">
      <VersionCard version={snack.old} role="old" snack={snack} relativeMass={1} />
      <div className="comparison-arrow" aria-hidden="true"><Icon name="arrow" size={22} /></div>
      <VersionCard version={snack.new} role="new" snack={snack} relativeMass={snack.new.mass_g / snack.old.mass_g} />
    </div>
    <GhostWeightOverlay oldMass={snack.old.mass_g} newMass={snack.new.mass_g} />
    <div className="reveal-strip"><div><span className="eyebrow">Less in the pack</span><strong>{percent(shrink)}</strong></div><div className="reveal-divider" /><div className="unit-change"><span className="eyebrow">Price per 100g</span><strong>{change == null ? 'Unknown' : percent(change, true)}</strong></div><p>{priceStory}</p></div>
    {snack.recipe_comparison_available && snack.recipe_history && <RecipeComparison recipe={snack.recipe_history} />}
    <div className="evidence-footnote"><span><span className="evidence-dot" /> {linked ? 'Old and new barcodes linked with evidence' : 'Reported size change · barcode chain incomplete'}</span><button className="text-button" onClick={event => onEvidence(event.currentTarget)}>Sources & date details <Icon name="arrow" size={16} /></button></div>
    <p className="date-caveat"><Icon name="clock" size={14} /> {snack.event_date_precision || 'Exact shelf-transition date is unknown.'}</p>
  </article>;
}

function RecipeComparison({ recipe }: { recipe: RecipeHistory }) {
  return <section className="recipe-comparison" aria-label="Ingredient label comparison">
    <span className="eyebrow">Inside the ingredients</span><h3>The label changed, too.</h3><p className="recipe-scope">{recipe.scope_note}</p>
    <div className="recipe-snapshots">{(['old', 'new'] as const).map(role => <div key={role}><span className="eyebrow">{role === 'old' ? 'Earlier declaration' : 'Later declaration'}</span><h4>{recipe[role].period}</h4>{recipe[role].mass_g != null && <span className="pill subtle">{formatMass(recipe[role].mass_g)}g pack</span>}<p>{recipe[role].ingredients_summary.join(' · ')}</p></div>)}</div>
    <div className="recipe-differences">{recipe.changes.map(change => <div key={change.label}><h4>{change.label}</h4><p><span>Before</span>{change.before}</p><p><span>After</span>{change.after}</p></div>)}</div>
    {recipe.changes.some(change => change.note) && <details className="recipe-evidence-details recipe-interpretation"><summary>How to read these changes</summary><ul className="limitations-list">{recipe.changes.filter(change => change.note).map(change => <li key={change.label}><strong>{change.label}: </strong>{change.note}</li>)}</ul></details>}
    <p className="recipe-label-note">Ingredient summaries; open the original documents for the complete declarations.</p><div className="recipe-source-links">{recipe.sources.map(source => <a key={source.id ?? source.url} href={source.url} target="_blank" rel="noreferrer">{source.title}<Icon name="external" size={13} /></a>)}</div>
  </section>;
}

function VersionCard({ version, role, snack, relativeMass }: { version: CaseVersion; role: 'old' | 'new'; snack: SnackCase; relativeMass: number }) {
  const photo = snack.photos?.find(item => item.role === role || item.role === `${role}_front`);
  const unit = unitPrice(version.price_gbp, version.mass_g);
  return <div className={`version-card ${role}`}><div className="version-top"><span>{role === 'old' ? 'THEN' : 'AFTER THE CHANGE'}</span><span>{version.period}</span></div>
    <div className="quantity-visual">
      {photo ? <img className="product-photo" src={photo.local_path} alt={`${snack.name}: ${role === 'old' ? 'earlier' : 'later'} source photograph`} /> : <div className={`mass-illustration ${brandClass(snack.name)}`} style={{ '--relative-mass': Math.min(1, Math.max(.25, relativeMass)) } as CSSProperties}><span className="illustration-brand">{snack.brand || shortName(snack.name)}</span><span className="illustration-mass">{formatMass(version.mass_g)}<small>grams</small></span><span className="illustration-rule" /><span className="illustration-caption">REPORTED NET WEIGHT</span></div>}
      {!photo && <span className="illustration-disclaimer">Size illustration · not a packaging photograph</span>}
    </div>
    <div className="version-numbers"><div><span>Pack size</span><strong>{formatMass(version.mass_g)}<small>g</small></strong></div><div><span>Reported price</span><strong className={version.price_gbp == null ? 'unknown-value' : ''}>{money(version.price_gbp)}</strong></div></div>
    <div className="unit-price-line"><span>Per 100g</span><strong>{money(unit)}</strong></div><p className="price-basis">{readable(version.price_basis)}</p>
  </div>;
}

function PriceHistory({ histories }: { histories: ProductHistory[] }) {
  const [id, setId] = useState(histories[0]?.id ?? '');
  const history = histories.find(item => item.id === id) ?? histories[0];
  const [activePoint, setActivePoint] = useState<number | null>(null);
  if (!history || !history.points.length) return <section className="history-section"><h2>Dated price history</h2><p>No dated retail listing is available in this export.</p></section>;
  const points = [...history.points].sort((a, b) => a.date.localeCompare(b.date));
  const activeIndex = observationIndex(activePoint, points.length);
  const active = points[activeIndex];
  const unitLabel = /volume|ml/i.test(history.dimension) ? '100ml' : '100g';
  const minValue = Math.min(...points.map(item => item.unit_price_gbp));
  const maxValue = Math.max(...points.map(item => item.unit_price_gbp));
  const margin = Math.max((maxValue - minValue) * .28, maxValue * .08, .02);
  const low = Math.max(0, minValue - margin);
  const high = maxValue + margin;
  const firstDate = Date.parse(points[0].date);
  const lastDate = Date.parse(points[points.length - 1].date);
  const x = (value: string) => 62 + (Date.parse(value) - firstDate) / Math.max(1, lastDate - firstDate) * 722;
  const y = (value: number) => 214 - (value - low) / (high - low) * 174;
  const path = points.map(item => `${x(item.date)},${y(item.unit_price_gbp)}`).join(' ');
  return <section className="history-section" aria-labelledby="price-history-title"><div className="section-topline"><span className="eyebrow">The price trail</span><span className="pill subtle"><Icon name="clock" size={13} /> Dated retail observations</span></div><div className="history-heading"><div><h2 id="price-history-title">A price has a history, too.</h2><p>Explore an observed retailer listing, separately from the reported changes above.</p></div><label className="listing-select"><span>Choose a retailer listing</span><select value={history.id} onChange={event => { setId(event.target.value); setActivePoint(null); }}>{histories.map(item => <option value={item.id} key={item.id}>{item.retailer} · {item.name}</option>)}</select></label></div>
    <div className="chart-card"><div className="chart-summary"><div><span className="eyebrow">{history.retailer}</span><h3>{history.name}</h3></div><div className="chart-value"><strong>{money(active.unit_price_gbp)}</strong><span>per {unitLabel} · {date(active.date)}</span></div></div>
      <svg className="price-chart" viewBox="0 0 820 252" role="img" aria-label={`Observed ${history.name} prices per ${unitLabel} from ${date(points[0].date)} to ${date(points[points.length - 1].date)}. Select a point for its date and price.`}>
        {[0, 1, 2, 3, 4].map(level => { const value = low + (high - low) * level / 4; return <g key={level}><line x1="62" x2="784" y1={y(value)} y2={y(value)} className="grid-line" /><text x="45" y={y(value) + 4} textAnchor="end" className="axis-label">{money(value)}</text></g>; })}
        <polygon points={`62,214 ${path} 784,214`} fill="url(#chart-fill)" /><defs><linearGradient id="chart-fill" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stopColor="#e75537" stopOpacity=".13" /><stop offset="1" stopColor="#e75537" stopOpacity="0" /></linearGradient></defs>
        <polyline points={path} fill="none" stroke="#dd4e32" strokeWidth="2.4" strokeLinejoin="round" />
        {points.map((point, index) => <g key={point.date} data-point={index} tabIndex={index === activeIndex ? 0 : -1} role="button" aria-label={`${date(point.date)}: ${money(point.unit_price_gbp)} per ${unitLabel}`} onFocus={() => setActivePoint(index)} onKeyDown={event => { if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') { event.preventDefault(); const next = Math.min(points.length - 1, Math.max(0, index + (event.key === 'ArrowRight' ? 1 : -1))); setActivePoint(next); event.currentTarget.ownerSVGElement?.querySelector<SVGGElement>(`[data-point="${next}"]`)?.focus(); } }} onMouseEnter={() => setActivePoint(index)} onClick={() => setActivePoint(index)}><circle cx={x(point.date)} cy={y(point.unit_price_gbp)} r="9" fill="transparent" /><circle cx={x(point.date)} cy={y(point.unit_price_gbp)} r={activeIndex === index ? 4.5 : 2.6} fill="#f7f4ed" stroke="#dd4e32" strokeWidth="1.7" /></g>)}
        {[points[0], points[Math.floor((points.length - 1) / 2)], points[points.length - 1]].map((point, index) => <text key={index} x={x(point.date)} y="244" textAnchor={index === 0 ? 'start' : index === 2 ? 'end' : 'middle'} className="axis-label">{date(point.date)}</text>)}
      </svg><div className="observation-inspector"><div className="observation-heading"><label htmlFor="history-observation">Inspect a recorded observation <span>{activeIndex + 1} of {points.length}</span></label><strong>{date(active.date)} <span>{money(active.unit_price_gbp)} / {unitLabel}</span></strong></div><input id="history-observation" type="range" min="0" max={points.length - 1} step="1" value={activeIndex} onChange={event => setActivePoint(Number(event.target.value))} aria-label="Select a recorded price observation" aria-valuetext={`${date(active.date)}: ${money(active.unit_price_gbp)} per ${unitLabel}`} /><div className="chart-date-range"><span><small>First observation</small>{date(points[0].date)}</span><span><small>Last observation</small>{date(points[points.length - 1].date)}</span></div><p>Each step selects one recorded observation. Gaps between dates have no implied prices.</p></div><div className="chart-footer"><span><i className="line-key" /> Observed unit price <span className="chart-observation-count">{points.length} dated points</span></span><a href={history.source_url} target="_blank" rel="noreferrer">View dataset <Icon name="external" size={13} /></a></div>
    </div><p className="data-note"><Icon name="info" size={15} /> Lines connect observations; gaps are unobserved. {readable(history.price_basis)}. Listing identity is provisional; this is not a verified barcode replacement chain.</p>
  </section>;
}

function ComparePage({ groups }: { groups: ComparisonGroup[] }) {
  const categories = [...new Set(groups.map(item => item.group ?? item.label ?? 'Snacks'))];
  const [category, setCategory] = useState(categories[0] ?? 'Snacks');
  const available = groups.filter(item => (item.group ?? item.label ?? 'Snacks') === category);
  const [snapshot, setSnapshot] = useState('');
  const group = available.find(item => comparisonKey(item) === snapshot) ?? available[0];
  const items = useMemo(() => [...(group?.items ?? [])].sort((a, b) => a.price_per_100g_gbp - b.price_per_100g_gbp), [group]);
  return <div className="page-shell"><section className="hero compact-hero"><div><p className="eyebrow"><span className="tiny-cross">✳</span> A fairer shelf comparison</p><h1>Look past<br />the <em>price tag.</em></h1><p className="hero-description">Different packs. Different prices.<br />One useful measure: what 100 grams costs.</p></div><div className="hero-aside"><div className="editorial-note"><span className="note-number">02 / PRICE COMPARISON</span><p>Compare the same date.<br />At the same retailer.</p><span className="note-rule" /><span>Actual observations, with price<br />conditions kept in view.</span></div></div></section>
    {!group ? <div className="empty-panel"><h2>No comparable snapshot is available.</h2><p>We need dated prices and valid gram quantities at the same retailer.</p></div> : <>
      <div className="compare-toolbar"><div className="segmented" aria-label="Snack category">{categories.map(item => <button key={item} className={item === category ? 'active' : ''} onClick={() => { setCategory(item); setSnapshot(''); }}>{item}</button>)}</div><label className="snapshot-select"><span>Price snapshot</span><select value={comparisonKey(group)} onChange={event => setSnapshot(event.target.value)}>{available.map(item => <option key={comparisonKey(item)} value={comparisonKey(item)}>{item.retailer} · {date(item.date)}</option>)}</select></label></div>
      <section className="comparison-board"><div className="comparison-board-header"><div><span className="eyebrow">One shelf, one moment</span><h2>{group.retailer}<span className="thin-heading"> / {group.group ?? group.label}</span></h2><p>{date(group.date, true)} · Historical prices, not today’s offers</p></div><a className="button outline" href={group.source_url} target="_blank" rel="noreferrer">Source dataset <Icon name="external" size={15} /></a></div>
        <div className="comparison-table-wrap"><table className="comparison-table"><thead><tr><th scope="col">Product</th><th scope="col">Pack size</th><th scope="col">Pack price</th><th scope="col">Per 100g</th><th scope="col"><span className="sr-only">Relative unit price</span></th></tr></thead><tbody>{items.map((item, index) => <tr key={item.id}><th scope="row"><div className="comparison-product"><span className={`table-monogram ${brandClass(item.name)}`}>{initials(item.name)}</span><span className="comparison-product-name">{item.name}<span className="mobile-pack-facts">{formatMass(item.mass_g)}g · {money(item.price_gbp)} per pack</span>{index === 0 && <small className="best-value">Lowest unit price in this set</small>}</span></div></th><td>{formatMass(item.mass_g)}<span className="unit">g</span></td><td>{money(item.price_gbp)}</td><td className="table-unit-price">{money(item.price_per_100g_gbp)}</td><td><div className="unit-bar"><i style={{ width: `${item.price_per_100g_gbp / Math.max(...items.map(value => value.price_per_100g_gbp)) * 100}%` }} /></div></td></tr>)}</tbody></table></div>
        <div className="comparison-note"><Icon name="info" size={17} /><p>Prices may include loyalty discounts. This compares cost by weight; ingredients, taste and dietary suitability are not treated as equivalent.</p></div>
      </section>
      <WholePackPlanner group={group} />
    </>}
  </div>;
}

function ForecastPage({ data }: { data: DemoData }) {
  if (data.category_forecast?.categories.length) return <CategoryForecastPage report={data.category_forecast} tuning={data.category_tuning} policy={data.category_policy_tuning} />;
  const evaluation = data.evaluation;
  const reference = evaluation.observed_nochange_reference;
  const mae = typeof reference?.mae_percentage_points === 'number' ? reference.mae_percentage_points : typeof reference?.mae === 'number' ? reference.mae * 100 : null;
  const rows = reference?.observations ?? reference?.rows ?? data.coverage.monthly_pairs;
  const rmse = typeof reference?.rmse_percentage_points === 'number' ? reference.rmse_percentage_points : typeof reference?.rmse === 'number' ? reference.rmse * 100 : null;
  const massPairs = typeof evaluation.coverage.eligible_mass_pairs === 'number' ? evaluation.coverage.eligible_mass_pairs : data.coverage.monthly_pairs;
  const models = evaluation.models.length ? evaluation.models : [{ name: 'No-change baseline', status: 'not_run' }, { name: 'Linear regression', status: 'not_run' }, { name: 'Boosted tree', status: 'not_run' }];
  return <div className="page-shell"><section className="hero compact-hero"><div><p className="eyebrow"><span className="tiny-cross">✳</span> The forecast lab</p><h1>Evidence first.<br /><em>Predictions</em> next.</h1><p className="hero-description">Monthly grocery-price changes.<br />Informed by weekly commodity movements.</p></div><div className="hero-aside"><div className="editorial-note"><span className="note-number">03 / WHAT COMES NEXT</span><p>Millions of prices.<br />Still a short time window.</p><span className="note-rule" /><span>We show what the evidence can<br />support, and where it stops.</span></div></div></section>
    <section className="forecast-status"><div className="status-icon"><Icon name="clock" size={26} /></div><div><span className="eyebrow">{evaluation.status === 'available' ? 'Evaluation available' : 'Forecast unavailable'}</span><h2>{evaluation.status === 'available' ? 'The evaluation is ready to inspect.' : 'A useful forecast needs more history.'}</h2><p>{evaluation.reason?.[0] ?? 'The available observations do not support a valid chronological model comparison.'}</p></div><span className="status-label">{evaluation.status === 'available' ? 'Evaluated' : 'Not enough evidence'}</span></section>
    <div className="forecast-coverage"><CoverageStat value={number(data.coverage.retail_observations)} label="retail price observations" note="Many products, a shared time window" /><CoverageStat value={number(massPairs)} label="eligible mass-price comparisons" note="Observed medians, with coverage rules" /><CoverageStat value={number(data.coverage.eligible_target_months)} label="fully covered target month" note="Insufficient for train / later-test periods" /><CoverageStat value={number(data.coverage.weekly_commodity_rows)} label="weekly commodity / FX rows" note="Historical publication timing still unknown" /></div>
    <section className="evaluation-section"><div className="history-heading"><div><span className="eyebrow">The comparison we owe you</span><h2>A fair test across time.</h2><p>A chronological backtest trains on the past, then tests on a later month.</p></div><span className="pill subtle">Target: next calendar month</span></div><div className="model-table-wrap"><table className="model-table"><thead><tr><th scope="col">Model</th><th scope="col">Chronological result</th><th scope="col">MAE</th></tr></thead><tbody>{models.map((model, index) => <tr key={model.name ?? model.model ?? index}><th scope="row"><span className="model-index">0{index + 1}</span>{model.name ?? readable(model.model ?? 'Model')}</th><td><span className="unrun-status"><span />{readable(model.status)}</span>{model.reason && <small>{model.reason}</small>}</td><td>{model.mae_percentage_points != null ? `${model.mae_percentage_points.toFixed(2)} pp` : model.mae == null ? <span className="metric-unavailable">—</span> : `${(model.mae * 100).toFixed(2)} pp`}</td></tr>)}</tbody></table></div>
      <div className="reference-card"><div><span className="eyebrow">Observed no-change reference</span><h3>{mae == null ? 'Not available' : `${mae.toFixed(2)} percentage points`}<small>{mae == null ? '' : 'mean absolute error'}</small></h3></div><p>{reference?.note ?? reference?.interpretation ?? 'This is a descriptive calculation on observed next-month changes. It is not a trained-model backtest or evidence of predictive skill.'}<span>{typeof rows === 'number' ? `${new Intl.NumberFormat('en-GB').format(rows)} observed pairs. ` : ''}It does not establish that commodity features improve predictions.</span>{rmse != null && <span>Root mean squared error: {rmse.toFixed(2)} percentage points.</span>}<a className="report-download" href="/data/evaluation.json" download>Download evaluation report <Icon name="external" size={13} /></a></p></div>
    </section>
    <section className="forecast-bottom"><div><span className="eyebrow">What is missing</span><h2>The path to a fair test.</h2><ol className="requirements-list">{evaluation.reason.map((reason, index) => <li key={index}><span>{(index + 1).toString().padStart(2, '0')}</span><p>{reason}</p></li>)}</ol></div><div className="feature-card"><Icon name="chart" size={27} /><h3>Do weekly costs explain<br />monthly shelf changes?</h3><p>That is a question to evaluate, not an assumption to bake in.</p><div className="feature-step"><span>01</span><p>Product-price history</p></div><div className="feature-step"><span>02</span><p>+ weekly commodity movements</p></div><div className="feature-step"><span>03</span><p>+ previous shrink / price responses</p></div><div className="feature-card-note">Commodity and response-pattern improvements are not established by the current data.</div></div></section>
  </div>;
}

function CoverageStat({ value, label, note }: { value: ReactNode; label: string; note: string }) { return <div><strong>{value}</strong><h3>{label}</h3><p>{note}</p></div>; }

function EvidenceDialog({ snack, onClose }: { snack: SnackCase; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => { const dialog = ref.current; dialog?.showModal(); return () => dialog?.close(); }, []);
  return <dialog className="evidence-dialog" ref={ref} onCancel={onClose} onClick={event => { if (event.target === event.currentTarget) onClose(); }} aria-labelledby="evidence-title"><div className="dialog-content"><div className="dialog-header"><div><span className="eyebrow">The paper trail</span><h2 id="evidence-title">{snack.name}</h2></div><button className="icon-button" onClick={onClose} aria-label="Close source evidence"><Icon name="close" /></button></div><div className="evidence-summary"><Icon name="check" size={18} /><p>{readable(snack.evidence_status)}</p></div><h3>Original sources</h3><div className="source-list">{snack.sources.map((source: Source, index) => <a key={source.id ?? index} href={source.url} target="_blank" rel="noreferrer"><span className="source-number">{(index + 1).toString().padStart(2, '0')}</span><span><strong>{source.title}</strong><span>{source.published ? `Published ${date(source.published)}` : 'Publication date not established'}{source.role ? ` · ${readable(source.role)}` : ''}</span></span><Icon name="external" size={17} /></a>)}</div><h3>What the dates establish</h3><p className="dialog-copy">{snack.event_date_precision}</p><div className="date-grid"><div><span>Earlier period</span><strong>{snack.old.period}</strong></div><div><span>Later period</span><strong>{snack.new.period}</strong></div><div><span>Exact shelf-transition day</span><strong>{snack.event_date ? date(snack.event_date) : 'Unknown'}</strong></div><div><span>Exact transaction dates</span><strong>{snack.old.transaction_date && snack.new.transaction_date ? `${date(snack.old.transaction_date)} / ${date(snack.new.transaction_date)}` : 'Unknown'}</strong></div></div><h3>Product identity</h3><div className="barcode-row"><div><span>Earlier barcode</span><code>{snack.family_link.old_barcode ?? snack.old.barcode ?? 'Not verified'}</code></div><Icon name="arrow" size={18} /><div><span>Later barcode</span><code>{snack.family_link.new_barcode ?? snack.new.barcode ?? 'Not verified'}</code></div></div><p className="dialog-copy">{snack.family_link.note}</p>{snack.family_link.supporting_urls?.length ? <div className="corroboration-links">{snack.family_link.supporting_urls.map((url, index) => <a href={url} key={url} target="_blank" rel="noreferrer">{url.includes("openfoodfacts.org") ? `Open Food Facts record ${index === 0 ? "(earlier)" : "(later)"}` : "Retailer quantity corroboration"}<Icon name="external" size={12} /></a>)}</div> : null}{snack.photos?.length > 0 && <><h3>Source photographs</h3><div className="source-photos">{snack.photos.map((photo, index) => <figure key={index}><a href={photo.source_url} target="_blank" rel="noreferrer"><img src={photo.local_path} alt={`${snack.name} ${photo.role} source photograph`} /></a><figcaption><strong>{readable(photo.role)}</strong><p>{photo.evidence_note}</p><small>{photo.attribution} · {photo.license}</small></figcaption></figure>)}</div></>}{snack.recipe_comparison_available && snack.recipe_history ? <><RecipeComparison recipe={snack.recipe_history} /><ul className="limitations-list">{snack.recipe_history.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul></> : <><h3>Recipe history</h3><p className="dialog-copy">Recipe history unavailable: a verified old/new ingredient-label pair has not been collected.</p></>}<h3>Keep in view</h3><ul className="limitations-list">{snack.limitations.map((item, index) => <li key={index}>{item}</li>)}</ul><div className="calculation-note"><span className="eyebrow">The calculation</span><code>price per 100g = 100 × pack price ÷ pack mass in grams</code><p>A 10% smaller pack at the same price means about 11.1% more per gram.</p></div></div></dialog>;
}

function shortName(value: string) { return value.replace(/ Milk Chocolate Extra Large Easter Egg| Milk Chocolate Easter Egg| chocolate tub| sharing bag| single bar/gi, '').trim(); }
function initials(value: string) { const cleaned = value.replace(/[^a-zA-Z ]/g, '').split(' ').filter(Boolean); return (cleaned.length > 1 ? cleaned[0][0] + cleaned[1][0] : cleaned[0]?.slice(0, 2) ?? 'UK').toUpperCase(); }
function brandClass(value: string) { if (/doritos/i.test(value)) return 'brand-doritos'; if (/snickers/i.test(value)) return 'brand-snickers'; if (/maltesers/i.test(value)) return 'brand-maltesers'; if (/oreo/i.test(value)) return 'brand-oreo'; if (/quality/i.test(value)) return 'brand-quality'; if (/m&m/i.test(value)) return 'brand-mms'; return 'brand-other'; }
function comparisonKey(value: ComparisonGroup) { return value.id ?? `${value.group ?? value.label}:${value.retailer}:${value.date}`; }

export default App;
