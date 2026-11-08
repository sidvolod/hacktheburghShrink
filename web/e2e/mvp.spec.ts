import { expect, test } from '@playwright/test';
import type { Page, TestInfo } from '@playwright/test';
import { mkdir, readFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import type { DemoData, ProductHistory, SnackCase } from '../src/types';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const data: DemoData = JSON.parse(await readFile(join(root, 'data/app-public/data/demo.json'), 'utf8'));
const basketOracle = JSON.parse(await readFile(join(root, 'web/e2e/fixtures/whole-pack-oracle.json'), 'utf8')).results as Array<{group_id: string; target_grams: number; total_price_pence: number; total_grams: number; extra_grams: number; pack_count: number}>;
const errors = new WeakMap<Page, string[]>();
const money = (value: number | null) => value == null ? 'Not reported' : new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'GBP', minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
const formatMass = (value: number) => new Intl.NumberFormat('en-GB', { maximumFractionDigits: 3 }).format(value);
const date = (value: string) => new Date(`${value.slice(0, 10)}T12:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
const orderedPoints = (history: ProductHistory) => [...history.points].sort((a, b) => a.date.localeCompare(b.date));

async function expectBasket(page: Page, groupId: string, target: number) {
  const expected = basketOracle.find(item => item.group_id === groupId && item.target_grams === target)!;
  expect(expected, 'Independent exhaustive basket expectation must exist.').toBeTruthy();
  await expect(page.getByTestId('basket-total')).toHaveText(money(expected.total_price_pence / 100));
  await expect(page.getByTestId('basket-weight')).toHaveText(`${formatMass(expected.total_grams)}g`);
  await expect(page.getByTestId('basket-excess')).toHaveText(`${formatMass(expected.extra_grams)}g`);
  await expect(page.getByTestId('basket-pack-count')).toHaveText(String(expected.pack_count));
}

async function home(page: Page) {
  await page.goto('/');
  await expect(page.getByRole('heading', { level: 1, name: 'Your memory was right.' })).toBeVisible();
  await expect(page.locator('.case-list .case-button')).toHaveCount(data.cases.length);
}

async function chooseCase(page: Page, snack: SnackCase) {
  const choice = page.locator('.case-list .case-button').nth(data.cases.findIndex(item => item.id === snack.id));
  await expect(choice).toContainText(snack.name);
  await choice.click();
  await expect(page.locator('.case-detail').getByRole('heading', { level: 2, name: snack.name, exact: true })).toBeVisible();
}

async function capture(page: Page, testInfo: TestInfo, name: string) {
  if (process.env.MVP_SKIP_SCREENSHOTS === '1') {
    testInfo.annotations.push({ type: 'diagnostic_only', description: 'Screenshot capture explicitly skipped; this run cannot satisfy visual verification.' });
    return;
  }
  const folder = join(root, 'data/reports/browser/screenshots');
  await mkdir(folder, { recursive: true });
  const path = join(folder, `${testInfo.project.name}-${name}.png`);
  const modalOpen = await page.locator('.evidence-dialog[open]').isVisible();
  if (!modalOpen) await page.evaluate(() => window.scrollTo({ top: 0, left: 0, behavior: 'instant' }));
  await page.screenshot({ path, fullPage: !modalOpen, animations: 'disabled', timeout: 10_000 });
  await testInfo.attach(name, { path, contentType: 'image/png' });
}

test.beforeEach(async ({ page }) => {
  const current: string[] = [];
  errors.set(page, current);
  page.on('pageerror', error => current.push(`pageerror: ${error.message}`));
  page.on('console', message => { if (message.type() === 'error') current.push(`console: ${message.text()}`); });
  page.on('response', response => {
    if (response.status() >= 400 && new URL(response.url()).origin === new URL(page.url()).origin) current.push(`HTTP ${response.status()}: ${response.url()}`);
  });
  page.on('requestfailed', request => {
    if (request.failure()?.errorText !== 'net::ERR_ABORTED' && new URL(request.url()).origin === new URL(page.url()).origin) current.push(`requestfailed: ${request.url()} ${request.failure()?.errorText}`);
  });
});

test.afterEach(async ({ page }, testInfo) => {
  const current = errors.get(page) ?? [];
  await testInfo.attach('console-and-resource-errors', { body: JSON.stringify(current, null, 2), contentType: 'application/json' });
  expect(current, 'The app must not log browser errors or request missing local assets.').toEqual([]);
});

for (const snack of data.cases) {
  test(`documented case: ${snack.name} (${snack.id})`, async ({ page }, testInfo) => {
    await home(page);
    await chooseCase(page, snack);
    const detail = page.locator('.case-detail');
    for (const role of ['old', 'new'] as const) {
      const version = snack[role];
      const card = detail.locator(`.version-card.${role}`);
      await expect(card.locator('.version-numbers > div').first().locator('strong')).toHaveText(`${formatMass(version.mass_g)}g`);
      await expect(card.locator('.version-numbers > div').last().locator('strong')).toHaveText(money(version.price_gbp));
      const unit = version.price_gbp == null ? null : 100 * version.price_gbp / version.mass_g;
      await expect(card.locator('.unit-price-line strong')).toHaveText(money(unit));
      await expect(card.locator('.price-basis')).toHaveText(version.price_basis.replaceAll('_', ' ').replaceAll('-', ' '));
    }
    const change = snack.unit_price_change_fraction;
    await expect(detail.locator('.unit-change strong')).toHaveText(change == null ? 'Unknown' : `${change > 0 ? '+' : ''}${(change * 100).toFixed(1)}%`);
    if (/recommended|rrp/i.test(snack.new.price_basis)) {
      await expect(detail.locator('.reveal-strip > p')).toContainText('recommended retail price stayed the same');
      await expect(detail.locator('.reveal-strip > p')).not.toContainText('shelf price stayed');
    }
    if (snack.old.price_gbp != null && snack.new.price_gbp != null && snack.new.price_gbp < snack.old.price_gbp) await expect(detail.locator('.reveal-strip > p')).toContainText('pack price fell');
    if (change == null) await expect(detail.locator('.reveal-strip > p')).toContainText('A comparable price pair is unavailable');
    if (/doritos/i.test(snack.name)) await capture(page, testInfo, 'historical-detective');
  });
}

test('case search and the slash shortcut filter actual evidence', async ({ page }) => {
  await home(page);
  const search = page.getByRole('textbox', { name: 'Search case files' });
  await page.keyboard.press('/');
  await expect(search).toBeFocused();
  await search.fill('snickers');
  await expect(page.locator('.case-list .case-button')).toHaveCount(1);
  await page.locator('.case-list .case-button').click();
  await expect(page.locator('.case-detail h2')).toHaveText('Snickers');
  await search.fill('unmatched case name');
  await expect(page.locator('.empty-search')).toContainText('No case matches');
  await expect(page.locator('.case-list .case-button')).toHaveCount(0);
  await search.clear();
  await expect(page.locator('.case-list .case-button')).toHaveCount(data.cases.length);
});

test('ingredient snapshots show documented differences with their own dates and sources', async ({ page }, testInfo) => {
  await home(page);
  const digestives = data.cases.find(item => item.id === 'mcvities-digestives-uk-500-to-400')!;
  await chooseCase(page, digestives);
  const recipe = page.locator('.case-detail .recipe-comparison');
  await expect(recipe).toBeVisible();
  await expect(recipe.locator('.recipe-scope')).toContainText('separate from the 2018/2019 size change');
  await expect(recipe.locator('.recipe-snapshots > div').first()).toContainText('2008');
  await expect(recipe.locator('.recipe-snapshots > div').last()).toContainText('2022');
  await expect(recipe.locator('.recipe-differences')).toContainText('Dried skimmed milk listed');
  await expect(recipe.locator('.recipe-differences')).toContainText('may-contain notice retained');
  await recipe.locator('.recipe-interpretation summary').click();
  await expect(recipe.locator('.recipe-interpretation')).toContainText('does not prove that palm oil was newly introduced');
  await recipe.locator('.recipe-interpretation summary').click();
  await expect(recipe.locator('.recipe-source-links a')).toHaveCount(2);
  const folder = join(root, 'data/reports/browser/screenshots');
  await mkdir(folder, { recursive: true });
  const digestivesPath = join(folder, `${testInfo.project.name}-digestives-recipe.png`);
  await recipe.screenshot({ path: digestivesPath, animations: 'disabled' });
  await testInfo.attach('digestives-recipe', { path: digestivesPath, contentType: 'image/png' });
  const penguin = page.locator('.recipe-finding').filter({ has: page.getByRole('heading', { name: 'Penguin Original', exact: true }) });
  await expect(penguin).toBeVisible();
  await expect(penguin.locator('.recipe-snapshots > div').first()).toContainText('2008');
  await expect(penguin.locator('.recipe-snapshots > div').last()).toContainText('2026');
  await expect(penguin.locator('.recipe-differences')).toContainText(/flavour/i);
  await expect(penguin.locator('.recipe-source-links a')).toHaveCount(2);
  await expect(penguin).not.toContainText('Price per 100g');
  const penguinPath = join(folder, `${testInfo.project.name}-penguin-recipe.png`);
  await penguin.screenshot({ path: penguinPath, animations: 'disabled' });
  await testInfo.attach('penguin-recipe', { path: penguinPath, contentType: 'image/png' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width);
  await page.locator('.case-detail .source-count').click();
  const dialog = page.getByRole('dialog', { name: digestives.name });
  await expect(dialog.locator('.recipe-comparison')).toBeVisible();
  await expect(dialog).not.toContainText('Recipe history unavailable');
  await expect(dialog.locator('.date-grid')).toContainText('Unknown');
});

test('Quality Street evidence exposes barcodes, photographs, provenance and unknown dates', async ({ page }, testInfo) => {
  await home(page);
  const quality = data.cases.find(item => /quality street/i.test(item.name))!;
  await chooseCase(page, quality);
  const trigger = page.locator('.case-detail .source-count');
  await trigger.click();
  const dialog = page.getByRole('dialog', { name: quality.name });
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('.barcode-row')).toContainText(quality.old.barcode!);
  await expect(dialog.locator('.barcode-row')).toContainText(quality.new.barcode!);
  await expect(dialog.locator('.date-grid > div').filter({ hasText: 'Exact shelf-transition day' })).toContainText('Unknown');
  await expect(dialog.locator('.date-grid > div').filter({ hasText: 'Exact transaction dates' })).toContainText('Unknown');
  await expect(dialog).toContainText(quality.event_date_precision);
  await expect(dialog).toContainText('Recipe history unavailable: a verified old/new ingredient-label pair has not been collected.');
  await expect(dialog.locator('.source-list > a')).toHaveCount(quality.sources.length);
  for (const source of quality.sources) await expect(dialog.locator('.source-list > a').filter({ hasText: source.title })).toHaveAttribute('href', source.url);
  await expect(dialog.locator('.source-photos img')).toHaveCount(3);
  await expect.poll(() => dialog.locator('.source-photos img').evaluateAll(images => images.every(image => (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0))).toBe(true);
  await expect(dialog.locator('.source-photos')).toContainText('CC-BY-SA');
  await expect(dialog).toContainText('weight is not visible');
  await expect(dialog.locator('.corroboration-links a')).toHaveCount(3);
  await capture(page, testInfo, 'source-evidence');
  await dialog.locator('.source-photos').scrollIntoViewIfNeeded();
  await capture(page, testInfo, 'source-photographs');
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(trigger).toBeFocused();
  const footerTrigger = page.locator('.case-detail .text-button');
  await footerTrigger.click();
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', { name: 'Close source evidence' }).click();
  await expect(dialog).not.toBeVisible();
  await expect(footerTrigger).toBeFocused();
  await footerTrigger.click();
  await expect(dialog).toBeVisible();
  await page.mouse.click(2, 2);
  await expect(dialog).not.toBeVisible();
  await expect(footerTrigger).toBeFocused();
});

test('switching from the final point of a longer history to a shorter history stays usable', async ({ page }, testInfo) => {
  await home(page);
  const histories = [...data.histories].sort((a, b) => b.points.length - a.points.length);
  const longer = histories[0];
  const shorter = histories[histories.length - 1];
  expect(longer.points.length).toBeGreaterThan(shorter.points.length);
  const listing = page.locator('.listing-select select');
  const slider = page.getByRole('slider', { name: 'Select a recorded price observation' });
  await listing.selectOption(longer.id);
  await slider.focus();
  await slider.press('End');
  await expect(slider).toHaveValue(String(longer.points.length - 1));
  await listing.selectOption(shorter.id);
  await expect(slider).toHaveValue(String(shorter.points.length - 1));
  const shorterPoints = orderedPoints(shorter);
  await expect(page.locator('.observation-heading > strong')).toContainText(date(shorterPoints[shorterPoints.length - 1].date));
  await expect(page.locator('.chart-summary h3')).toHaveText(shorter.name);
  await slider.focus();
  await slider.press('Home');
  await expect(slider).toHaveValue('0');
  await expect(page.locator('.observation-heading > strong')).toContainText(date(shorterPoints[0].date));
  await slider.press('ArrowRight');
  await expect(slider).toHaveValue('1');
  await expect(page.locator('.observation-heading > strong')).toContainText(date(shorterPoints[1].date));
  await expect(page.locator('.observation-heading > strong')).toContainText(money(shorterPoints[1].unit_price_gbp));
  const point = page.locator('.price-chart [role="button"][tabindex="0"]');
  await expect(point).toHaveCount(1);
  await expect(point).toHaveAttribute('data-point', '1');
  await point.focus();
  await point.press('ArrowRight');
  await expect(slider).toHaveValue('2');
  await expect(page.locator('.price-chart [role="button"][tabindex="0"]')).toHaveAttribute('data-point', '2');
  await expect(page.locator('.data-note')).toContainText('Listing identity is provisional');
  await expect(page.locator('.observation-inspector')).toContainText('Gaps between dates have no implied prices.');
  if (testInfo.project.name === 'phone') expect((await slider.boundingBox())!.height).toBeGreaterThanOrEqual(44);
  await capture(page, testInfo, 'recorded-price-history');
});

test('comparison switches snapshots and finds the lowest-cost whole-pack basket', async ({ page }, testInfo) => {
  await home(page);
  await page.getByRole('button', { name: 'Price comparison', exact: true }).click();
  await expect(page).toHaveURL(/#compare$/);
  for (const group of data.comparisons) {
    await page.getByRole('button', { name: group.group, exact: true }).click();
    await page.locator('.snapshot-select select').selectOption(group.id!);
    await expect(page.locator('.comparison-board-header h2')).toContainText(group.retailer);
    await expect(page.locator('.comparison-board-header h2')).toContainText(group.group);
    await expect(page.locator('.comparison-board-header p')).toContainText('Historical prices, not today’s offers');
    const rows = page.locator('.comparison-table tbody tr');
    const items = [...group.items].sort((a, b) => a.price_per_100g_gbp - b.price_per_100g_gbp);
    await expect(rows).toHaveCount(items.length);
    for (let index = 0; index < items.length; index++) {
      await expect(rows.nth(index).locator('th')).toContainText(items[index].name);
      await expect(rows.nth(index).locator('td').nth(0)).toHaveText(`${formatMass(items[index].mass_g)}g`);
      await expect(rows.nth(index).locator('td').nth(1)).toHaveText(money(items[index].price_gbp));
      await expect(rows.nth(index).locator('td').nth(2)).toHaveText(money(items[index].price_per_100g_gbp));
    }
    await expect(rows.first()).toContainText('Lowest unit price in this set');
    await expectBasket(page, group.id!, 300);
    await expect(page.locator('.whole-pack-snapshot')).toContainText(group.retailer);
    if (testInfo.project.name === 'phone') {
      const firstName = rows.first().locator('.comparison-product-name');
      await firstName.evaluate(element => element.scrollIntoView({ block: 'center', inline: 'nearest', behavior: 'instant' }));
      await expect(firstName).toBeInViewport({ ratio: 1 });
      await expect(rows.first().locator('.table-unit-price')).toBeInViewport({ ratio: 1 });
      await expect(rows.first().locator('.mobile-pack-facts')).toBeVisible();
      await expect(rows.first().locator('.mobile-pack-facts')).toContainText(`${formatMass(items[0].mass_g)}g · ${money(items[0].price_gbp)} per pack`);
    }
  }
  const finalGroup = data.comparisons[data.comparisons.length - 1];
  const weight = page.getByRole('slider', { name: 'Target weight in grams' });
  await weight.focus();
  await weight.press('End');
  await expect(weight).toHaveValue('1000');
  await expectBasket(page, finalGroup.id!, 1000);
  for (let step = 0; step < 10; step++) await weight.press('ArrowLeft');
  await expect(weight).toHaveValue('500');
  await expectBasket(page, finalGroup.id!, 500);
  await expect(page.locator('.whole-pack-conditions')).toContainText('price conditions and stock are unknown');
  const plannerPath = join(root, 'data/reports/browser/screenshots', `${testInfo.project.name}-whole-pack-planner.png`);
  await page.locator('.whole-pack-planner').screenshot({ path: plannerPath, animations: 'disabled' });
  await testInfo.attach('whole-pack-planner', { path: plannerPath, contentType: 'image/png' });
  await expect(page.locator('.comparison-note')).toContainText('Prices may include loyalty discounts');
  await capture(page, testInfo, 'price-comparison');
});

test('forecast renders trained category results or the explicit product-data fallback', async ({ page }, testInfo) => {
  await home(page);
  await page.getByRole('button', { name: /Forecast lab/ }).click();
  await expect(page).toHaveURL(/#forecast$/);
  if (data.category_forecast?.categories.length) {
    const activeReport = data.category_tuning ?? data.category_forecast;
    if (data.category_tuning?.categories.length) await page.getByRole('button', { name: 'Tuned backtest', exact: true }).click();
    for (const category of activeReport.categories) {
      await page.getByRole('button', { name: category.category_name, exact: true }).click();
      await expect(page.locator('.forecast-status .eyebrow')).toHaveText('Category forecast available');
      await expect(page.locator('.forecast-status h2')).toHaveText(`${category.category_name} price outlook`);
      const value = category.forecast.change_pct;
      await expect(page.locator('.outlook-number > strong')).toHaveText(`${value > 0 ? '+' : ''}${value.toFixed(2)}%`);
      await expect(page.locator('.outlook-metrics')).toContainText(`${category.test_metrics.mae_pp.toFixed(2)} pp`);
      await expect(page.locator('.outlook-model')).toContainText(`${category.test_metrics.n} later test months`);
      await expect(page.locator('.model-table tbody tr')).toHaveCount(category.leaderboard.length);
      await expect(page.locator('.model-table .selected-model')).toHaveCount(1);
      await page.getByRole('button', { name: 'Reveal actual' }).click();
      const first = category.test_predictions[0];
      await expect(page.locator('.actual-revealed strong')).toHaveText(`${first.actual_pct > 0 ? '+' : ''}${first.actual_pct.toFixed(2)}%`);
      const slider = page.getByRole('slider', { name: 'Historical forecast month' });
      await slider.focus();
      await slider.press('End');
      await expect(page.locator('.actual-hidden strong')).toHaveText('?');
      await page.getByRole('button', { name: 'Reveal actual' }).click();
      const last = category.test_predictions.at(-1)!;
      await expect(page.locator('.actual-revealed strong')).toHaveText(`${last.actual_pct > 0 ? '+' : ''}${last.actual_pct.toFixed(2)}%`);
      if (typeof category.baseline_metrics.mae_pp === 'number' && category.test_metrics.mae_pp >= category.baseline_metrics.mae_pp) {
        await expect(page.locator('.outlook-baseline-note')).toContainText('did not beat');
      }
    }
    const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'Download the model comparison' }).click()]);
    const downloaded = JSON.parse(await readFile((await download.path())!, 'utf8'));
    expect(downloaded.categories).toHaveLength(activeReport.categories.length);
    if (data.category_policy_tuning?.categories.length) {
      await page.getByRole('combobox', { name: 'Tuning experiment' }).selectOption('policies');
      for (const category of data.category_policy_tuning.categories) {
        await page.getByRole('button', { name: category.category_name, exact: true }).click();
        await expect(page.locator('.outlook-model h3')).toHaveText('Rolling ensemble selection');
        await expect(page.locator('.outlook-metrics')).toContainText(`${category.test_metrics.mae_pp.toFixed(2)} pp`);
        const value = category.forecast.change_pct;
        await expect(page.locator('.outlook-number > strong')).toHaveText(`${value > 0 ? '+' : ''}${value.toFixed(2)}%`);
      }
    }
    await expect(page.locator('.outlook-method')).toContainText('does not establish the future price or pack size');
    if (data.category_tuning?.categories.length) {
      await expect(page.locator('.outlook-tuning-note')).toContainText('already examined');
      await page.getByRole('button', { name: 'Original evaluation', exact: true }).click();
      await expect(page.locator('.outlook-tuning-note')).toHaveCount(0);
      const original = data.category_forecast.categories.at(-1)!;
      const originalValue = original.forecast.change_pct;
      await expect(page.locator('.outlook-number > strong')).toHaveText(`${originalValue > 0 ? '+' : ''}${originalValue.toFixed(2)}%`);
      await page.getByRole('button', { name: 'Tuned backtest', exact: true }).click();
      await expect(page.locator('.outlook-tuning-note')).toContainText('Exploratory retuning');
      await expect(page.locator('.outlook-model h3')).toContainText('Rolling');
    }
    await capture(page, testInfo, 'category-forecast');
    return;
  }
  await expect(page.locator('.forecast-status .eyebrow')).toHaveText('Forecast unavailable');
  await expect(page.locator('.forecast-status')).toContainText('39,920');
  await expect(page.locator('.forecast-status')).toContainText('1 distinct target month');
  await expect(page.locator('.hero-description')).toContainText('Monthly grocery-price changes.');
  await expect(page.locator('.hero-description')).toContainText('weekly commodity movements.');
  const rows = page.locator('.model-table tbody tr');
  await expect(rows).toHaveCount(3);
  for (const model of data.evaluation.models) {
    const row = rows.filter({ hasText: model.name! });
    await expect(row.locator('.unrun-status')).toHaveText('not run');
    await expect(row.locator('td').last()).toHaveText('—');
  }
  await expect(page.locator('.reference-card h3')).toContainText('8.08 percentage points');
  await expect(page.locator('.reference-card')).toContainText('Root mean squared error: 20.15 percentage points');
  await expect(page.locator('.reference-card')).toContainText('does not measure future skill or model accuracy');
  await expect(page.locator('.reference-card')).toContainText('39,920 observed pairs');
  await expect(page.locator('.requirements-list li')).toHaveCount(3);
  await expect(page.locator('.requirements-list')).toContainText('publication');
  await expect(page.locator('.requirements-list')).toContainText('Candidate matches are not training labels');
  await expect(page.locator('.feature-card-note')).toContainText('improvements are not established');
  const [download] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', { name: 'Download evaluation report' }).click()]);
  const downloaded = JSON.parse(await readFile((await download.path())!, 'utf8'));
  expect(downloaded.status).toBe('unavailable');
  expect(downloaded.forecast).toBeNull();
  expect(downloaded.observed_nochange_reference.observations).toBe(39920);
  expect(downloaded.observed_nochange_reference.mae_percentage_points).toBeCloseTo(8.078393715162392, 9);
  await capture(page, testInfo, 'forecast-evidence-gate');
});

test('skip-to-content preserves comparison and forecast routes', async ({ page }) => {
  await home(page);
  for (const name of ['Price comparison', 'Forecast lab']) {
    await page.getByRole('button', { name: new RegExp(`^${name}`) }).click();
    const expectedHash = name === 'Price comparison' ? '#compare' : '#forecast';
    const skip = page.getByRole('link', { name: 'Skip to content' });
    await skip.focus();
    await skip.press('Enter');
    await expect(page.locator('main')).toBeFocused();
    await expect(page).toHaveURL(new RegExp(`${expectedHash}$`));
  }
});

test('phone layouts keep body copy and controls readable without page-level horizontal overflow', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== 'phone', 'Phone-specific layout and touch-target checks.');
  await home(page);
  for (const section of ['The detective', 'Price comparison', 'Forecast lab']) {
    await page.getByRole('button', { name: new RegExp(`^${section}`) }).click();
    const viewportWidth = page.viewportSize()!.width;
    const documentWidth = await page.evaluate(() => document.documentElement.scrollWidth);
    expect(documentWidth, `${section}: tables and case lists should scroll internally, not widen the configured ${viewportWidth}px phone viewport.`).toBeLessThanOrEqual(viewportWidth);
    const paragraphs = await page.locator('main p:visible:not(.eyebrow)').evaluateAll(elements => elements.map(element => ({ text: element.textContent?.slice(0, 65), size: parseFloat(getComputedStyle(element).fontSize) })));
    expect(paragraphs.filter(item => item.size < 12), `${section}: body copy minimum is 12px.`).toEqual([]);
    const controls = await page.locator('main select:visible, main input:visible').evaluateAll(elements => elements.map(element => ({ height: element.getBoundingClientRect().height, font: parseFloat(getComputedStyle(element).fontSize) })));
    expect(controls.every(item => item.height >= 40 && item.font >= 11), `${section}: native controls must stay usable on phones.`).toBe(true);
  }
});


test('memory challenge prints a sourced, exact inflation receipt and resets on a new case', async ({ page }, testInfo) => {
  await home(page);
  const challenge = page.locator('.reveal-challenge');
  const picker = challenge.getByRole('combobox', { name: 'Pick a familiar case' });
  await expect(picker).toHaveValue('revels-uk-pouch-2025');
  await expect(challenge.locator('.inflation-receipt')).toHaveCount(0);
  await expect(picker.locator('option[value="maltesers-uk-pouch-2016"]')).toHaveCount(0);
  const gramsGuess = challenge.getByRole('slider', { name: /Your guess: grams removed/ });
  await gramsGuess.focus();
  await gramsGuess.press('ArrowRight');
  await expect(gramsGuess).toHaveValue('10.5');
  await challenge.getByRole('button', { name: 'Lock guess & print receipt' }).click();
  const receipt = challenge.locator('.inflation-receipt');
  await expect(receipt).toBeVisible();
  await expect(receipt).toBeFocused();
  await expect(receipt).toContainText('£3.66');
  await expect(receipt).toContainText('+33.0%');
  await expect(receipt).toContainText('+£0.36');
  await expect(receipt).toContainText('+20.0%');
  await expect(receipt).toContainText('+13.0 pp');
  await expect(receipt).toContainText('Hypothetical constant-weight cost');
  await expect(gramsGuess).toBeDisabled();
  const solidShare = await receipt.locator('.reveal-ghost-bar > div').first().evaluate(element => parseFloat((element as HTMLElement).style.width));
  expect(solidShare).toBeCloseTo(100 * 185 / 205, 3);
  const folder = join(root, 'data/reports/browser/screenshots');
  await mkdir(folder, { recursive: true });
  const path = join(folder, `${testInfo.project.name}-hidden-inflation-receipt.png`);
  await challenge.screenshot({ path, animations: 'disabled' });
  await testInfo.attach('hidden-inflation-receipt', { path, contentType: 'image/png' });
  await receipt.getByRole('button', { name: 'Read sources & limitations' }).click();
  const dialog = page.getByRole('dialog', { name: 'Revels', exact: true });
  await expect(dialog).toBeVisible();
  await expect(dialog.locator('.source-list > a')).toHaveCount(data.cases.find(item => item.id === 'revels-uk-pouch-2025')!.sources.length);
  await dialog.getByRole('button', { name: 'Close source evidence' }).click();
  await expect(receipt.getByRole('button', { name: 'Read sources & limitations' })).toBeFocused();
  await challenge.getByRole('button', { name: 'Try another guess' }).click();
  await expect(receipt).toHaveCount(0);
  await expect(gramsGuess).toBeEnabled();
  await picker.selectOption('snickers-uk-single-2013');
  await challenge.getByRole('button', { name: 'Lock guess & print receipt' }).click();
  await expect(receipt).toContainText('recommended retail prices; not observed checkout prices');
  await picker.selectOption('maltesers-uk-pouch-2017');
  await expect(receipt).toHaveCount(0);
  await challenge.getByRole('button', { name: 'Lock guess & print receipt' }).click();
  await expect(receipt).toContainText('retailer and offer conditions are unspecified');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width);
});

test('conservative decision output keeps raw forecasts and identifies the post-evaluation rule', async ({ page }, testInfo) => {
  await home(page);
  await page.getByRole('button', { name: /Forecast lab/ }).click();
  const original = data.category_forecast!;
  for (const category of original.categories) {
    await page.getByRole('button', { name: category.category_name, exact: true }).click();
    const gate = page.locator('.forecast-decision');
    const passes = category.test_metrics.mae_pp < Number(category.baseline_metrics.mae_pp);
    await expect(gate.locator('.forecast-decision-badge')).toHaveText(passes ? 'Model retained' : 'No-change fallback');
    const raw = category.forecast.change_pct;
    const output = passes ? raw : 0;
    await expect(gate.locator('.forecast-decision-output > strong')).toHaveText(`${output > 0 ? '+' : ''}${output.toFixed(2)}%`);
    await expect(page.locator('.outlook-number > strong')).toHaveText(`${raw > 0 ? '+' : ''}${raw.toFixed(2)}%`);
    await expect(gate.locator('.forecast-decision-note')).toContainText('added after reviewing these test results');
    await expect(gate.locator('.forecast-decision-note')).toContainText('future performance is untested');
  }
  const gatePath = join(root, 'data/reports/browser/screenshots', `${testInfo.project.name}-conservative-output.png`);
  await page.locator('.forecast-decision').screenshot({ path: gatePath, animations: 'disabled' });
  await testInfo.attach('conservative-output', { path: gatePath, contentType: 'image/png' });
});
