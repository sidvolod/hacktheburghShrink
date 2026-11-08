import { useId, useMemo, useState } from 'react';
import type { ComparisonGroup } from './types';
import { MAX_TARGET_GRAMS, MIN_TARGET_GRAMS, optimizeWholePacks } from './wholePackMath';
import './whole-pack.css';

const pounds = (pence: number) => new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(pence / 100);
const grams = (value: number) => new Intl.NumberFormat('en-GB', { maximumFractionDigits: 3 }).format(value);
const snapshotDate = (value: string) => new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}T12:00:00Z`));

export function WholePackPlanner({ group }: { group: ComparisonGroup }) {
  const [target, setTarget] = useState(300);
  const id = useId();
  const plan = useMemo(() => optimizeWholePacks(group, target), [group, target]);
  return <section className="whole-pack-planner" aria-labelledby={`${id}-heading`}>
    <div className="whole-pack-intro">
      <span className="eyebrow">From a fair comparison to a real basket</span>
      <h2 id={`${id}-heading`}>You can’t buy<br /><em>half a pack.</em></h2>
      <p>How much do you need? Find the lowest checkout cost for at least that weight, using whole packs from this snapshot.</p>
      <label className="whole-pack-target" htmlFor={`${id}-target`}>
        <span>Target weight <strong>{grams(target)}g</strong></span>
        <input id={`${id}-target`} aria-label="Target weight in grams" type="range" min={MIN_TARGET_GRAMS} max={MAX_TARGET_GRAMS} step="50" value={target} aria-valuetext={`${target} grams`} onChange={event => setTarget(Number(event.target.value))} />
        <span className="whole-pack-endpoints"><span>50g</span><span>1,000g</span></span>
      </label>
      <p className="whole-pack-priority">Lowest spend first. If costs tie: less excess, then fewer packs.</p>
    </div>
    <div className="whole-pack-result" aria-live="polite" aria-atomic="true">
      {plan.status === 'unavailable' ? <div className="whole-pack-unavailable"><h3>Basket calculation unavailable</h3><p>{plan.reason}</p></div> : <>
        <div className="whole-pack-result-heading"><div><span className="eyebrow">Lowest checkout cost</span><h3>At least {grams(target)}g</h3></div><strong className="whole-pack-total" data-testid="basket-total">{pounds(plan.totalPricePence)}</strong></div>
        <p className="whole-pack-snapshot">{group.retailer} · {snapshotDate(group.date)}<span>Historical snapshot</span></p>
        <ul className="whole-pack-lines" aria-label="Recommended whole-pack basket">{plan.lines.map(line => <li key={line.item.id}>
          <span className="whole-pack-count">{line.count} ×</span>
          <div><strong>{line.item.name}</strong><span>{grams(line.packMassGrams)}g per pack · {pounds(line.packPricePence)} each</span></div>
          <strong className="whole-pack-line-total">{pounds(line.totalPricePence)}</strong>
        </li>)}</ul>
        <dl className="whole-pack-stats"><div><dt>Whole packs</dt><dd data-testid="basket-pack-count">{plan.packCount}</dd></div><div><dt>Total weight</dt><dd data-testid="basket-weight">{grams(plan.totalGrams)}<small>g</small></dd></div><div><dt>Extra to keep</dt><dd data-testid="basket-excess">{grams(plan.excessGrams)}<small>g</small></dd></div><div><dt>Basket per 100g</dt><dd>{pounds(plan.pricePer100gPence)}</dd></div></dl>
        <p className="whole-pack-proof">Exact whole-pack calculation across {plan.consideredProducts} listed options. Packs can be mixed within this retailer, date and category.</p>
      </>}
      <p className="whole-pack-conditions">Uses recorded per-pack prices, which may require loyalty membership; price conditions and stock are unknown. Assumes repeat purchases at that price, with no extra multibuy discount. Ingredients, taste and dietary needs still matter.</p>
    </div>
  </section>;
}
