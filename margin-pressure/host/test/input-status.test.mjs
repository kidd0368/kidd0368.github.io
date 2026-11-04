import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { readInputStatus, taipeiCalendarDate } from '../input-status.mjs';
import { workbook } from './xlsx-fixture.mjs';
import { inspectXlsxDates } from '../xlsx-dates.mjs';

async function inputFixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'margin-inputs-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  async function file(name, contentDate, options = {}) {
    const parts = name.split('/'); parts.pop();
    await mkdir(join(root, ...parts), { recursive: true });
    const kind = name.includes('chatgpt') ? 'history' : name.includes('融資融券') ? 'margin' : 'prices';
    await writeFile(join(root, name), workbook(kind, contentDate || name.match(/\d{8}/)?.[0], options));
  }
  return { root, file };
}

test('newer primary workbook wins over stale legacy workbook, including repeated spaces', async t => {
  const { root, file } = await inputFixture(t);
  await file('chatgpt 計算融資維持率  20261030.xlsx');
  await file('gpt 維持率追蹤/chatgpt 計算融資維持率  20260821.xlsx');
  await file('融資融券 20261103.xlsx');
  await file('個股日K線 20261103.xlsx');
  await file('gpt 維持率追蹤/備份/融資維持率  20260728.xlsx');
  const status = await readInputStatus(root, '20260814');
  assert.equal(status.files.length, 3);
  assert.equal(status.files[0].latest.date, '20261030');
  assert.equal(status.files[0].latest.path, join(root, 'chatgpt 計算融資維持率  20261030.xlsx'));
  assert.equal(status.files[2].latest.date, '20261103');
  assert.match(status.summary, /檔名日期不同/);
  assert.equal(status.anchor.found, true);
  assert.equal(status.anchor.dataDate, '20260727');
  assert.equal(status.dateBasis, 'worksheet_headers');
});

test('same day selects primary folder; a newer legacy workbook still wins', async t => {
  const { root, file } = await inputFixture(t);
  await file('chatgpt 計算融資維持率 20261102.xlsx');
  await file('gpt 維持率追蹤/chatgpt 計算融資維持率 20261102.xlsx');
  let status = await readInputStatus(root, '20260814');
  assert.equal(status.files[0].latest.rank, 0);
  assert.equal(status.files[0].duplicate, false);
  await file('gpt 維持率追蹤/chatgpt 計算融資維持率 20261103.xlsx');
  status = await readInputStatus(root, '20260814');
  assert.equal(status.files[0].latest.rank, 1);
  assert.equal(status.files[0].latest.date, '20261103');
});

test('invalid dates, Excel temporary locks and unrelated workbooks do not become inputs', async t => {
  const { root, file } = await inputFixture(t);
  for (const name of ['融資融券 20260230.xlsx', '~$融資融券 20261103.xlsx', '三大法人買賣超 20261103.xlsx']) await file(name);
  const status = await readInputStatus(root, '20260814');
  assert.ok(status.files.every(row => row.latest === null));
  assert.match(status.summary, /尚未找到 3 份/);
  assert.equal(status.anchor.found, false);
});

test('newer filename is labelled as pending rebuild and not verified workbook content', async t => {
  const { root, file } = await inputFixture(t);
  for (const prefix of ['chatgpt 計算融資維持率', '融資融券', '個股日k線']) await file(`${prefix} 20261103.xlsx`);
  const status = await readInputStatus(root, '20260814');
  assert.match(status.summary, /網站仍須完成重算/);
  assert.equal(status.analysisDate, '20260814');
});

test('same-folder same-day duplicates need confirmation', async t => {
  const { root, file } = await inputFixture(t);
  await file('chatgpt 計算融資維持率 20261103.xlsx');
  await file('chatgpt 計算融資維持率  20261103.xlsx');
  for (const prefix of ['融資融券', '個股日k線']) await file(`${prefix} 20261103.xlsx`);
  const status = await readInputStatus(root, '20260814');
  assert.equal(status.files[0].duplicate, true);
  assert.match(status.summary, /同日重複/);
});

test('missing source directory is distinguished from a verified missing workbook', async t => {
  const { root } = await inputFixture(t);
  const status = await readInputStatus(join(root, 'not-here'), '20260814');
  assert.equal(status.available, false);
  assert.match(status.summary, /找不到來源資料夾/);
});

test('per-file warning names the lagging workbook and the exact target filename', async t => {
  const { root, file } = await inputFixture(t);
  await file('chatgpt 計算融資維持率 20261030.xlsx');
  for (const prefix of ['融資融券', '個股日k線']) await file(`${prefix} 20261103.xlsx`);
  const status = await readInputStatus(root, '20260814', { targetDate: '20261103' });
  assert.deepEqual(status.files.map(file => file.freshness.code), ['outdated', 'at_target', 'at_target']);
  assert.equal(status.counts.outdated, 1);
  assert.equal(status.files[0].expectedTargetName, 'chatgpt 計算融資維持率 20261103.xlsx');
  assert.match(status.files[0].action, /重新匯出/);
  assert.match(status.alert, /chatgpt 計算融資維持率（檔內 2026\/10\/30；檔名 2026\/10\/30）/);
  assert.match(status.alert, /目標 2026\/11\/03/);
  assert.equal(status.tone, 'danger');
});

test('three equally stale filenames are all overdue even when their dates agree', async t => {
  const { root, file } = await inputFixture(t);
  for (const prefix of ['chatgpt 計算融資維持率', '融資融券', '個股日k線']) await file(`${prefix} 20261030.xlsx`);
  const status = await readInputStatus(root, '20261030', { targetDate: '20261103' });
  assert.equal(status.counts.outdated, 3);
  assert.ok(status.files.every(file => file.freshness.label === '尚未更新'));
});

test('current filenames do not hide an outdated website or imply verified workbook content', async t => {
  const { root, file } = await inputFixture(t);
  for (const prefix of ['chatgpt 計算融資維持率', '融資融券', '個股日k線']) await file(`${prefix} 20261103.xlsx`);
  const status = await readInputStatus(root, '20260814', { targetDate: '20261103' });
  assert.equal(status.counts.at_target, 3);
  assert.equal(status.website.code, 'outdated');
  assert.match(status.website.label, /2026\/08\/14/);
  assert.match(status.alert, /網站數據尚未套用/);
  assert.ok(status.files.every(file => file.freshness.contentVerified === false));
});

test('matching website and filenames still retain the content-check boundary', async t => {
  const { root, file } = await inputFixture(t);
  for (const prefix of ['chatgpt 計算融資維持率', '融資融券', '個股日k線']) await file(`${prefix} 20261103.xlsx`);
  await file('gpt 維持率追蹤/備份/融資維持率 20260728.xlsx');
  const status = await readInputStatus(root, '20261103', { targetDate: '20261103' });
  assert.equal(status.website.code, 'at_target');
  assert.equal(status.tone, 'info');
  assert.match(status.alert, /個股數值與欄位完整性仍須/);
});

test('future-dated and missing filenames are not shown as current', async t => {
  const { root, file } = await inputFixture(t);
  await file('chatgpt 計算融資維持率 20261104.xlsx');
  const status = await readInputStatus(root, '20260814', { targetDate: '20261103' });
  assert.equal(status.files[0].freshness.code, 'future');
  assert.equal(status.files[1].freshness.code, 'missing');
  assert.equal(status.counts.at_target, 0);
});

test('invalid target dates are rejected and the default day follows Taipei midnight', async t => {
  const { root } = await inputFixture(t);
  await assert.rejects(readInputStatus(root, '20260814', { targetDate: '20260230' }), error => error.status === 400);
  assert.equal(taipeiCalendarDate(new Date('2026-11-03T15:59:59Z')), '20261103');
  assert.equal(taipeiCalendarDate(new Date('2026-11-03T16:00:00Z')), '20261104');
  const status = await readInputStatus(root, '20260814', { now: new Date('2026-11-03T15:00:00Z') });
  assert.equal(status.targetDate, '20261103');
  assert.equal(status.targetSource, 'taipei_today');
});

test('renaming a stale workbook does not make its content current', async t => {
  const { root, file } = await inputFixture(t);
  await file('chatgpt 計算融資維持率 20261103.xlsx', '20261030');
  for (const prefix of ['融資融券', '個股日k線']) await file(`${prefix} 20261103.xlsx`);
  const status = await readInputStatus(root, '20261030', { targetDate: '20261103' });
  assert.equal(status.files[0].latest.date, '20261103');
  assert.equal(status.files[0].inspection.lastDate, '20261030');
  assert.equal(status.files[0].freshness.code, 'outdated');
  assert.match(status.files[0].action, /只改檔名不會/);
  assert.match(status.alert, /檔內 2026\/10\/30；檔名 2026\/11\/03/);
});

test('unreadable or inconsistent date headers are never shown as updated', async t => {
  const { root, file } = await inputFixture(t);
  const name = 'chatgpt 計算融資維持率 20261103.xlsx';
  await file(name, '20261103', { mismatch: '資買' });
  let result = await inspectXlsxDates(join(root, name), 'history');
  assert.equal(result.code, 'unknown'); assert.match(result.note, /不一致/);
  await file(name, '20261103', { omit: '資買' });
  result = await inspectXlsxDates(join(root, name), 'history');
  assert.equal(result.code, 'unknown');
  await writeFile(join(root, name), 'unfinished sync');
  const status = await readInputStatus(root, '20261103', { targetDate: '20261103' });
  assert.equal(status.files[0].freshness.code, 'unknown');
  assert.equal(status.counts.at_target, 0);
});

test('header cache notices replacement of an existing workbook', async t => {
  const { root, file } = await inputFixture(t);
  const name = '個股日k線 20261103.xlsx';
  await file(name, '20261030');
  assert.equal((await inspectXlsxDates(join(root, name), 'prices')).lastDate, '20261030');
  await file(name, '20261103');
  assert.equal((await inspectXlsxDates(join(root, name), 'prices')).lastDate, '20261103');
});
