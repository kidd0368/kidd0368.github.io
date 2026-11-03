import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { readInputStatus } from '../input-status.mjs';

async function inputFixture(t) {
  const root = await mkdtemp(join(tmpdir(), 'margin-inputs-'));
  t.after(() => rm(root, { recursive: true, force: true }));
  async function file(name) {
    const parts = name.split('/'); parts.pop();
    await mkdir(join(root, ...parts), { recursive: true });
    await writeFile(join(root, name), 'fixture-name-check-only');
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
  assert.equal(status.dateBasis, 'filename_only');
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
