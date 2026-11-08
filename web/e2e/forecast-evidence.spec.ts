import { expect, test } from '@playwright/test';
import type { Page, TestInfo } from '@playwright/test';
import { mkdir, readFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

// Read the frozen published predictions, independently of presentation helpers.
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const demo = JSON.parse(await readFile(join(root, 'data/app-public/data/demo.json'), 'utf8'));
const original = demo.category_forecast;
const chocolate = original.categories.find((category: { category_id: string }) => category.category_id === 'chocolate');
const crisps = original.categories.find((category: { category_id: string }) => category.category_id === 'crisps');
const pageErrors = new WeakMap<Page, string[]>();
const displayedScore = (value: number) => `${value.toFixed(2)} pp`;
const percentDifference = (selected: number, reference: number) => Math.abs(100 * (reference - selected) / reference).toFixed(1) + '%';

async function openOriginal(page: Page, categoryName: string) {
  await page.goto('/#forecast');
  await page.getByRole('button', { name: 'Original evaluation', exact: true }).click();
  await page.getByRole('button', { name: categoryName, exact: true }).click();
  await expect(page.getByTestId('forecast-evidence')).toBeVisible();
}

async function capturePanel(page: Page, testInfo: TestInfo, name: string) {
  const panel = page.getByTestId('forecast-evidence');
  await panel.scrollIntoViewIfNeeded();
  const folder = join(root, 'data/reports/browser/screenshots');
  await mkdir(folder, { recursive: true });
  const path = join(folder, `${testInfo.project.name}-${name}.png`);
  await panel.screenshot({ path, animations: 'disabled', timeout: 10_000 });
  await testInfo.attach(name, { path, contentType: 'image/png' });
}

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  pageErrors.set(page, errors);
  page.on('pageerror', error => errors.push(error.message));
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
});

test.afterEach(async ({ page }) => {
  expect(pageErrors.get(page) ?? [], 'The evidence panel should render without browser errors.').toEqual([]);
});

test('chocolate evidence keeps the commodity increment distinct from beating simple baselines', async ({ page }, testInfo) => {
  const predictions = chocolate.test_predictions as Array<{ actual_pct: number; predicted_pct: number }>;
  const measuredMae = predictions.reduce((sum, item) => sum + Math.abs(item.actual_pct - item.predicted_pct), 0) / predictions.length;
  const zeroMae = predictions.reduce((sum, item) => sum + Math.abs(item.actual_pct), 0) / predictions.length;
  // These are the original saved test forecasts, not values invented for the UI.
  expect(predictions).toHaveLength(33);
  expect(measuredMae).toBeCloseTo(1.5747375908632857, 12);
  expect(zeroMae).toBeCloseTo(1.9770120494163437, 12);
  const seasonal = chocolate.leaderboard.find((item: { model_id: string }) => item.model_id === 'seasonal');
  const history = chocolate.leaderboard.find((item: { model_id: string; feature_group: string }) => item.model_id === chocolate.selected_model_id && item.feature_group === 'history_only');
  expect(history.test_mae_pp).toBeCloseTo(1.5947658752973108, 12);
  expect(seasonal.test_mae_pp).toBeCloseTo(1.6158238292089573, 12);

  await openOriginal(page, chocolate.category_name);
  const panel = page.getByTestId('forecast-evidence');
  await expect(panel).toContainText(displayedScore(measuredMae));
  const zero = page.getByTestId('evidence-no-change');
  await expect(zero).toContainText(displayedScore(zeroMae));
  await expect(zero).toContainText(percentDifference(measuredMae, zeroMae));
  await expect(zero).toContainText(/lower/i);
  const seasonalCard = page.getByTestId('evidence-seasonal');
  await expect(seasonalCard).toContainText(displayedScore(seasonal.test_mae_pp));
  await expect(seasonalCard).toContainText(percentDifference(measuredMae, seasonal.test_mae_pp));
  await expect(seasonalCard).toContainText(/lower/i);
  const commodity = page.getByTestId('evidence-history-only');
  await expect(commodity).toContainText(displayedScore(history.test_mae_pp));
  await expect(commodity).toContainText(percentDifference(measuredMae, history.test_mae_pp));
  await expect(commodity).toContainText(/lower/i);
  // No-change improvement is about 20%; adding commodities is only about 1%.
  await expect(commodity).not.toContainText('20.3%');
  await expect(panel).toContainText(/33/);
  await capturePanel(page, testInfo, 'forecast-evidence-chocolate');
});

test('crisps evidence retains the failed baseline comparison and has no commodity ablation', async ({ page }, testInfo) => {
  await openOriginal(page, crisps.category_name);
  const panel = page.getByTestId('forecast-evidence');
  await expect(panel).toContainText(displayedScore(crisps.test_metrics.mae_pp));
  const zero = page.getByTestId('evidence-no-change');
  await expect(zero).toContainText(displayedScore(crisps.baseline_metrics.mae_pp));
  await expect(zero).toContainText(percentDifference(crisps.test_metrics.mae_pp, crisps.baseline_metrics.mae_pp));
  await expect(zero).toContainText(/higher/i);
  await expect(page.getByTestId('evidence-history-only')).toHaveCount(0);
  await expect(page.locator('.outlook-baseline-note')).toContainText('did not beat');
  await capturePanel(page, testInfo, 'forecast-evidence-crisps');
});

test('exploratory tuning never relabels unmatched candidates as a commodity ablation', async ({ page }) => {
  await openOriginal(page, chocolate.category_name);
  await page.getByRole('button', { name: 'Tuned backtest', exact: true }).click();
  for (const method of ['models', 'policies']) {
    await page.getByRole('combobox', { name: 'Tuning experiment' }).selectOption(method);
    await page.getByRole('button', { name: chocolate.category_name, exact: true }).click();
    const report = method === 'models' ? demo.category_tuning : demo.category_policy_tuning;
    const selected = report.categories.find((item: { category_id: string }) => item.category_id === 'chocolate');
    const panel = page.getByTestId('forecast-evidence');
    await expect(panel).toContainText(/Exploratory comparison/i);
    await expect(panel).toContainText(displayedScore(selected.test_metrics.mae_pp));
    await expect(page.getByTestId('evidence-no-change')).toContainText(percentDifference(selected.test_metrics.mae_pp, selected.baseline_metrics.mae_pp));
    await expect(page.getByTestId('evidence-history-only')).toHaveCount(0);
  }
});

test('forecast evidence remains readable within the viewport in both category states', async ({ page }) => {
  for (const category of [chocolate, crisps]) {
    await openOriginal(page, category.category_name);
    const panel = page.getByTestId('forecast-evidence');
    const box = await panel.boundingBox();
    expect(box, 'The evidence panel must occupy real layout space.').not.toBeNull();
    expect(box!.width).toBeGreaterThan(250);
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width + 1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width);
  }
});
