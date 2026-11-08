import { useId, useMemo, useRef, useState, useEffect } from 'react';
import type { SnackCase } from './types';
import { inflationReceipt } from './revealMath';
import './reveal-challenge.css';

interface RevealChallengeProps {
  cases: SnackCase[];
  onEvidence?: (snack: SnackCase, opener: HTMLButtonElement) => void;
}

const money = (value: number) => new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP' }).format(value);
const grams = (value: number) => new Intl.NumberFormat('en-GB', { maximumFractionDigits: 1 }).format(value);
const percent = (value: number) => `${value > 0 ? '+' : ''}${(value * 100).toFixed(1)}%`;
const points = (value: number) => `${value > 0 ? '+' : ''}${(value * 100).toFixed(1)} pp`;

export function GhostWeightOverlay({ oldMass, newMass }: { oldMass: number; newMass: number }) {
  if (!Number.isFinite(oldMass) || !Number.isFinite(newMass) || newMass <= 0 || oldMass <= newMass) return null;
  const removed = oldMass - newMass;
  const share = newMass / oldMass;
  return <div className="reveal-ghost" aria-label={`Weight illustration: ${grams(oldMass)} grams before, ${grams(newMass)} grams now, ${grams(removed)} grams removed`}>
    <div className="reveal-ghost-labels"><span>{grams(newMass)}g now</span><span>{grams(removed)}g gone</span></div>
    <div className="reveal-ghost-bar" aria-hidden="true"><div style={{ width: `${share * 100}%` }} /><div style={{ width: `${(1 - share) * 100}%` }} /></div>
    <small>Area represents weight, not wrapper dimensions.</small>
  </div>;
}

export function RevealChallenge({ cases, onEvidence }: RevealChallengeProps) {
  const candidates = useMemo(() => cases.filter(snack => inflationReceipt(snack) !== null), [cases]);
  const [selected, setSelected] = useState(() => candidates.find(snack => snack.id === 'revels-uk-pouch-2025')?.id ?? candidates[0]?.id ?? '');
  const [guessedGrams, setGuessedGrams] = useState(10);
  const [guessedRise, setGuessedRise] = useState(10);
  const [revealed, setRevealed] = useState(false);
  const receiptRef = useRef<HTMLElement>(null);
  const id = useId();
  const snack = candidates.find(candidate => candidate.id === selected) ?? candidates[0];
  const receipt = snack ? inflationReceipt(snack) : null;
  useEffect(() => {
    if (revealed) receiptRef.current?.focus({ preventScroll: true });
  }, [revealed]);
  if (!snack || !receipt) return null;
  const changeCase = (value: string) => { setSelected(value); setGuessedGrams(10); setGuessedRise(10); setRevealed(false); };
  const maxGrams = Math.floor(receipt.oldMass * 2 - 1) / 2;
  const maxRise = Math.max(100, Math.ceil(receipt.effectiveChangeFraction * 125 / 10) * 10);

  return <section className={`reveal-challenge ${revealed ? 'is-revealed' : ''}`} aria-labelledby={`${id}-heading`}>
    <div className="reveal-challenge-intro">
      <span className="eyebrow">Before you open the case files</span>
      <h2 id={`${id}-heading`}>Trust your snack memory?</h2>
      <p>Guess what disappeared. Then see the price increase hiding behind a smaller pack.</p>
    </div>
    <div className="reveal-challenge-grid">
      <div className="reveal-guess-card">
        <label className="reveal-case-select" htmlFor={`${id}-case`}>Pick a familiar case
          <select id={`${id}-case`} value={snack.id} onChange={event => changeCase(event.target.value)}>
            {candidates.map(candidate => <option value={candidate.id} key={candidate.id}>{candidate.name}{candidate.reported_year ? ` · ${candidate.reported_year} report` : ''}</option>)}
          </select>
        </label>
        <div className="reveal-product-title"><span aria-hidden="true">?</span><div><h3>{snack.name}</h3><p>{snack.format ?? snack.category}</p></div></div>
        <label className="reveal-slider" htmlFor={`${id}-grams`}><span>Your guess: grams removed <output htmlFor={`${id}-grams`}>{grams(guessedGrams)}g</output></span>
          <input id={`${id}-grams`} type="range" min={0} max={maxGrams} step={0.5} value={Math.min(maxGrams, guessedGrams)} disabled={revealed} onChange={event => setGuessedGrams(Number(event.target.value))} />
        </label>
        <label className="reveal-slider" htmlFor={`${id}-rise`}><span>Your guess: effective price increase <output htmlFor={`${id}-rise`}>{guessedRise}%</output></span>
          <input id={`${id}-rise`} type="range" min={0} max={maxRise} step={1} value={guessedRise} disabled={revealed} onChange={event => setGuessedRise(Number(event.target.value))} />
        </label>
        <p className="reveal-guess-help">Effective increase means the change in price for the same amount of food.</p>
        {!revealed ? <button className="button dark reveal-print-button" onClick={() => setRevealed(true)}>Lock guess &amp; print receipt <span aria-hidden="true">↗</span></button>
          : <><div className="reveal-guess-result" aria-live="polite"><strong>The reveal: {grams(receipt.removedGrams)}g gone · {percent(receipt.effectiveChangeFraction)} per gram.</strong><span>Your guesses: {grams(guessedGrams)}g and {guessedRise}%. {Math.abs(guessedRise - receipt.effectiveChangeFraction * 100).toFixed(1)} percentage points from the measured increase.</span></div><button className="button outline reveal-reset-button" onClick={() => setRevealed(false)}>Try another guess</button></>}
      </div>

      {!revealed ? <div className="reveal-receipt-cover" aria-hidden="true"><div className="reveal-printer-slot" /><div className="reveal-blank-receipt"><span>THE PRICE YOU SEE</span><strong>£ ? . ? ?</strong><div /><div /><div /><p>The part you missed<br />prints next.</p><span className="reveal-cover-mark">✳</span></div></div>
        : <article className="inflation-receipt" ref={receiptRef} tabIndex={-1} aria-labelledby={`${id}-receipt`}>
          <div className="receipt-topline">SHRINCFLATION TRACK <span>REPORTED CHANGE</span></div>
          <h3 id={`${id}-receipt`}>Your hidden<br />inflation receipt</h3>
          <p className="receipt-case">{snack.name} · {snack.retailer ?? 'Retailer unspecified'}{snack.reported_year ? ` · ${snack.reported_year} report` : ''}</p>
          {/rrp|recommended/i.test(snack.new.price_basis) && <p className="receipt-footnote receipt-price-basis">Reported recommended retail prices; not observed checkout prices.</p>}
          {!snack.retailer && !/rrp|recommended/i.test(snack.new.price_basis) && <p className="receipt-footnote receipt-price-basis">Reported prices; retailer and offer conditions are unspecified.</p>}
          <dl className="receipt-lines">
            <div><dt>Earlier pack <span>{grams(receipt.oldMass)}g</span></dt><dd>{money(receipt.oldPrice)}</dd></div>
            <div><dt>Later pack <span>{grams(receipt.newMass)}g</span></dt><dd>{money(receipt.newPrice)}</dd></div>
            <div className="receipt-sticker"><dt>Sticker-price change</dt><dd>{percent(receipt.stickerChangeFraction)}</dd></div>
            <div><dt>Restore the missing {grams(receipt.removedGrams)}g <small>At the later price per gram</small></dt><dd>+{money(receipt.missingQuantityCost)}</dd></div>
            <div className="receipt-total"><dt>Same {grams(receipt.oldMass)}g, at the new rate <small>Hypothetical constant-weight cost</small></dt><dd>{money(receipt.constantWeightCost)}</dd></div>
          </dl>
          <div className="receipt-effective"><span>Real change per gram</span><strong>{percent(receipt.effectiveChangeFraction)}</strong></div>
          <div className="receipt-decomposition"><span>How the increase adds up</span><p>Sticker price <b>{points(receipt.stickerChangeFraction)}</b><br />Then restore missing grams <b>{points(receipt.shrinkContributionFraction)}</b></p><small>Contributions use the old pack price as their base. Values round separately.</small></div>
          <GhostWeightOverlay oldMass={receipt.oldMass} newMass={receipt.newMass} />
          <p className="receipt-footnote">A historical calculation from reported prices. The extra grams are costed proportionally; this is not a pack you can buy.</p>
          <div className="receipt-evidence">{onEvidence ? <button onClick={event => onEvidence(snack, event.currentTarget)}>Read sources &amp; limitations <span aria-hidden="true">↗</span></button> : snack.sources.map(source => <a href={source.url} target="_blank" rel="noreferrer" key={source.url}>{source.title} ↗</a>)}</div>
        </article>}
    </div>
  </section>;
}
