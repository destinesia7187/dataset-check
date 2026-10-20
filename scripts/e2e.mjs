// Real-browser acceptance scenario against an already running, built application.
// Resolve Playwright from the frontend's pinned dependency tree.
import assert from 'node:assert/strict';
import { mkdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const require = createRequire(path.join(root, 'frontend', 'package.json'));
const { chromium, expect: playwrightExpect } = require('@playwright/test');
const expect = playwrightExpect.configure({ timeout: 30000 });
const baseUrl = (process.env.E2E_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '');
const output = process.env.E2E_SCREENSHOT_DIR ?? path.join(root, 'benchmark-results', 'e2e');
await mkdir(output, { recursive: true });

const browser = await chromium.launch({
  headless: process.env.E2E_HEADED !== '1',
  ...(process.env.PLAYWRIGHT_EXECUTABLE_PATH ? { executablePath: process.env.PLAYWRIGHT_EXECUTABLE_PATH } : {}),
});
const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
const page = await context.newPage();
page.setDefaultTimeout(30000);
const pageErrors = [];
page.on('pageerror', error => pageErrors.push(error.message));
let datasetId;
let runId;
try {
  await page.goto(baseUrl, { waitUntil: 'networkidle' });
  await expect(page.getByRole('heading', { name: 'Check your data before analysis' })).toBeVisible();
  await page.screenshot({ path: path.join(output, 'workspace.png'), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('button', { name: 'Choose file', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Choose file', exact: true })).toBeInViewport({ ratio: 1 });
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true,
    'The mobile workspace must fit the viewport without horizontal page scrolling');
  await page.screenshot({ path: path.join(output, 'workspace-mobile.png'), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByLabel('CSV file').setInputFiles(path.join(root, 'examples', 'synthetic', 'acceptance.csv'));
  await page.getByLabel(/^Delimiter/).selectOption('comma');
  const uploadResponsePromise = page.waitForResponse(response =>
    response.request().method() === 'POST' && new URL(response.url()).pathname === '/api/v1/datasets');
  await page.getByRole('button', { name: 'Upload and preview →', exact: true }).click();
  const uploadResponse = await uploadResponsePromise;
  assert.equal(uploadResponse.status(), 201, await uploadResponse.text());
  datasetId = (await uploadResponse.json()).dataset_id;
  await expect(page.getByRole('heading', { name: 'Data preview', exact: true })).toBeVisible();
  await page.screenshot({ path: path.join(output, 'preview.png'), fullPage: true });
  await page.getByRole('button', { name: 'Configure checks', exact: true }).click();

  await page.getByLabel('id: required', { exact: true }).check();
  await page.getByLabel('id: unique', { exact: true }).check();
  await page.getByLabel('id: type', { exact: true }).selectOption('text');
  await page.getByLabel('name: required', { exact: true }).check();
  await page.getByLabel('name: type', { exact: true }).selectOption('text');
  await page.getByLabel('population: required', { exact: true }).check();
  await page.getByLabel('population: type', { exact: true }).selectOption('integer');
  await page.getByLabel('population: minimum', { exact: true }).fill('0');
  await page.getByLabel('population: maximum', { exact: true }).fill('100');
  await page.getByLabel('opened_at: required', { exact: true }).uncheck();
  await page.getByLabel('opened_at: type', { exact: true }).selectOption('date');
  await page.getByLabel(/Find exact duplicate rows/).check();

  const runResponsePromise = page.waitForResponse(response =>
    response.request().method() === 'POST' && new URL(response.url()).pathname.endsWith('/runs'));
  await page.getByRole('button', { name: 'Run checks →', exact: true }).click();
  const runResponse = await runResponsePromise;
  assert.equal(runResponse.status(), 202, await runResponse.text());
  runId = (await runResponse.json()).run_id;
  await expect(page.getByRole('heading', { name: 'Results are ready', exact: true })).toBeVisible();
  const metrics = page.locator('.result-metrics .metric');
  await expect(metrics.filter({ hasText: 'Problematic records' }).locator('strong')).toHaveText('8');
  await expect(metrics.filter({ hasText: 'Total issues' }).locator('strong')).toHaveText('13');
  await page.screenshot({ path: path.join(output, 'result.png'), fullPage: true });

  // Exercise server-side filtering and record/group details through the UI.
  await page.locator('.filters').getByLabel(/^Rule/).selectOption('INVALID_TYPE');
  await expect(page.locator('.issues-table tbody tr')).toHaveCount(3);
  await page.getByRole('button', { name: 'Reset', exact: true }).click();
  await expect(page.locator('.issues-table tbody tr')).toHaveCount(13);
  await page.getByRole('button', { name: '#1 ↗', exact: true }).first().click();
  await expect(page.getByRole('dialog')).toContainText('Record # 1');
  await page.getByRole('button', { name: 'Close preview', exact: true }).click();
  await page.getByRole('button', { name: 'Participants ↗', exact: true }).first().click();
  await expect(page.getByRole('dialog')).toContainText('Duplicate group participants');
  await page.getByRole('button', { name: 'Close preview', exact: true }).click();

  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: '↓ JSON report', exact: true }).click();
  const download = await downloadPromise;
  const reportPath = path.join(output, 'report.json');
  await download.saveAs(reportPath);
  const report = JSON.parse(await readFile(reportPath, 'utf8'));
  const expectedSummary = JSON.parse(await readFile(path.join(root, 'examples/synthetic/expected_summary.json'), 'utf8'));
  assert.deepEqual(report.summary, expectedSummary);
  assert.equal(report.problematic_records.length, 8);
  assert.equal(report.problematic_records.reduce((sum, record) => sum + record.violation_count, 0), 13);
  assert.deepEqual(report.problematic_records.map(record => record.row_index), [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.equal(report.problematic_records.find(record => record.row_index === 8).values[2], '  ');

  // Reload reads the persisted run and its original rules, without loading the full report.
  const reportRequests = [];
  const trackExport = request => {
    if (request.url().includes('/exports/report-json')) reportRequests.push(request.url());
  };
  page.on('request', trackExport);
  await page.reload({ waitUntil: 'networkidle' });
  await expect(page.getByRole('heading', { name: 'Results are ready', exact: true })).toBeVisible();
  await page.getByRole('button', { name: /Show saved rules/ }).click();
  const populationSnapshot = page.locator('.snapshot tbody tr').filter({ hasText: 'population' });
  await expect(populationSnapshot).toContainText('Integer');
  await expect(populationSnapshot).toContainText('0 … 100');
  assert.equal(reportRequests.length, 0, 'Opening a result must not download the full JSON report');
  page.off('request', trackExport);
  assert.deepEqual(pageErrors, [], 'Browser must have no uncaught JavaScript errors');
  const result = { passed: true, dataset_id: datasetId, run_id: runId, issues: 13, problematic_records: 8 };
  await writeFile(path.join(output, 'result.json'), JSON.stringify(result, null, 2) + '\n');
  console.log(JSON.stringify(result, null, 2));
} catch (error) {
  await page.screenshot({ path: path.join(output, 'failure.png'), fullPage: true }).catch(() => {});
  await writeFile(path.join(output, 'page-errors.json'), JSON.stringify(pageErrors, null, 2));
  throw error;
} finally {
  if (datasetId && process.env.E2E_KEEP !== '1') {
    const response = await context.request.delete(`${baseUrl}/api/v1/datasets/${datasetId}`, { headers: { 'X-Dataset-Check': '1' } });
    if (!response.ok()) console.error(`E2E cleanup returned ${response.status()}: ${await response.text()}`);
  }
  await context.close();
  await browser.close();
}
