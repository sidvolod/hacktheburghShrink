import { expect, test } from '@playwright/test';
import type { Page, TestInfo } from '@playwright/test';
import { mkdir, readFile } from 'node:fs/promises';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
// Independently checked with Decimal arithmetic from fixture pounds and the
// two original ONS endpoint levels; no application calculation is imported.
const oracle = {
  'snack-club': { personal: .011223801883832612, spending: 55.80, other: 0 },
  'mixed-household': { personal: .034887258592887332, spending: 13137.60, other: .9956156375593716 },
  'short-statement': { personal: .028378888885901908, spending: 16.30, other: .6134969325153374 },
};
const percent = (value: number) => `${(value * 100).toFixed(1)}%`;
async function open(page: Page) {
  await page.goto('/#personal');
  await expect(page.getByRole('heading', { level: 1 })).toContainText('Your basket.');
  await expect(page.getByLabel('Synthetic example')).toHaveValue('snack-club');
  await expect(page.getByRole('button', { name: 'Personal inflation', exact: true })).toHaveAttribute('aria-current', 'page');
}
async function sample(page: Page, id: keyof typeof oracle) {
  await page.getByLabel('Synthetic example').selectOption(id);
  await page.getByRole('button', { name: 'Calculate sample', exact: true }).click();
  await expect(page.getByTestId('personal-rate')).toHaveText(percent(oracle[id].personal));
  await expect(page.getByTestId('personal-other-share')).toHaveText(percent(oracle[id].other));
}
async function screenshot(page: Page, info: TestInfo, name: string) {
  if (process.env.MVP_SKIP_SCREENSHOTS === '1') return;
  const directory = join(root, 'data/reports/browser/screenshots'); await mkdir(directory, { recursive: true });
  const path = join(directory, `${info.project.name}-${name}.png`);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  await page.screenshot({ path, fullPage: true, animations: 'disabled' });
  await info.attach(name, { path, contentType: 'image/png' });
}

test('synthetic statements use independently checked annual weights and keep observations separate', async ({ page }, info) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await open(page); await sample(page, 'snack-club');
  await expect(page.locator('.personal-result-label')).toContainText('Synthetic statement');
  await expect(page.getByTestId('personal-headline-rate')).toHaveText('3.5%');
  await expect(page.locator('.personal-metrics')).toContainText('3.6%');
  await expect(page.locator('.personal-metrics a')).toHaveAttribute('href', 'https://www.ons.gov.uk/economy/inflationandpriceindices/bulletins/consumerpriceinflation/september2026');
  await expect(page.locator('.personal-metrics')).toContainText('2026-10-21');
  await expect(page.locator('.personal-summary')).toContainText(/Sept? 2025 to Sept? 2026/);
  await expect(page.locator('.personal-metrics')).toContainText('£55.80');
  await expect(page.locator('.personal-observed')).toContainText('DEMO CHOCOLATE CLUB');
  await expect(page.locator('.personal-observed')).toContainText('+20.0%');
  await expect(page.locator('.personal-observed')).toContainText('13 payments');
  await expect(page.locator('.personal-exclusions')).toContainText('£31,200.00');
  await expect(page.locator('.personal-exclusions')).toContainText('£260.00');
  await screenshot(page, info, 'personal-inflation');
  const downloadEvent = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Download aggregate result' }).click();
  const download = await downloadEvent, path = await download.path();
  expect(path).not.toBeNull();
  const result = JSON.parse(await readFile(path!, 'utf8'));
  expect(result.personal_rate).toBeCloseTo(oracle['snack-club'].personal, 12);
  expect(result.total_spending_gbp).toBe(55.80); expect(result.other_share).toBe(0);
  expect(result.categories.reduce((sum: number, category: { weight: number }) => sum + category.weight, 0)).toBeCloseTo(1, 12);
  expect(result.headline_rate).toBe(.035); expect(result.cpih_rate).toBe(.036);
  expect(result.headline_reference.start_month).toBe('2025-09'); expect(result.headline_reference.end_month).toBe('2026-09');
  expect(result.headline_reference.release_date).toBe('2026-10-21');
  expect(result.mode).toBe('synthetic_demo'); expect(result.input_is_synthetic).toBe(true);
  expect(result.observed_price_changes).toHaveLength(2);
  expect(result).not.toHaveProperty('transactions'); expect(result).not.toHaveProperty('descriptions');
  await sample(page, 'mixed-household');
  await expect(page.locator('.personal-metrics')).toContainText('£13,137.60');
  await expect(page.getByRole('list', { name: 'Calculation warnings' })).toContainText('25%');
  await expect(page.locator('.personal-observed')).toContainText('No qualifying recurring payment');
  await sample(page, 'short-statement');
  await expect(page.locator('.personal-metrics')).toContainText('£16.30');
  await expect(page.getByRole('list', { name: 'Calculation warnings' })).toContainText('less than three months');
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(page.viewportSize()!.width);
  expect(errors).toEqual([]);
});

test('CSV processing stays in browser memory, rejects malformed input and clears results', async ({ page }) => {
  const posts: string[] = [], external: string[] = [], logs: string[] = []; let origin = '';

  page.on('request', request => {
    if (!origin && request.isNavigationRequest()) origin = new URL(request.url()).origin;
    if (request.method() !== 'GET' && request.method() !== 'HEAD') posts.push(request.method());
    if (new URL(request.url()).origin !== origin) external.push(new URL(request.url()).origin);
  });
  page.on('console', message => logs.push(message.text()));
  await open(page);
  const originalStorage = await page.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage } }));
  const marker = 'PRIVATE_LOCAL_TEST_MERCHANT_Q981';
  await page.getByLabel('Choose bank statement CSV').setInputFiles({ name: 'synthetic-local.csv', mimeType: 'text/csv', buffer: Buffer.from(`Date,Description,Amount\n01/09/2026,${marker},-12.00\n`) });
  await expect(page.getByTestId('personal-rate')).toHaveText('3.5%');
  await expect(page.getByTestId('personal-other-share')).toHaveText('100.0%');
  await expect(page.locator('.personal-result-label')).toContainText('Local statement');
  expect(await page.evaluate(() => ({ local: { ...localStorage }, session: { ...sessionStorage } }))).toEqual(originalStorage);
  expect(logs.some(item => item.includes(marker))).toBe(false);
  await page.getByRole('button', { name: 'Clear statement', exact: true }).click();
  await expect(page.locator('.personal-results')).toHaveCount(0);
  await expect(page.getByLabel('Choose bank statement CSV')).toHaveValue('');
  await page.getByLabel('Choose bank statement CSV').setInputFiles({ name: 'malformed.csv', mimeType: 'text/csv', buffer: Buffer.from('Date,Description,Amount\n01/09/2026,"unclosed,-12') });
  await expect(page.getByRole('alert')).toContainText('Malformed CSV');
  await expect(page.locator('.personal-results')).toHaveCount(0);
  await page.getByRole('button', { name: 'Clear statement', exact: true }).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  await sample(page, 'snack-club');
  expect(posts).toEqual([]); expect(external).toEqual([]);
});
