import { test } from 'node:test';
import assert from 'node:assert/strict';
import { mkdtemp, mkdir, writeFile, rm, readFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { randomBytes, pbkdf2Sync, createCipheriv, createHash } from 'node:crypto';
import { createApp, decryptPayload } from '../server.mjs';
import { hostFrontend } from '../frontend.mjs';
import { createDataSource } from '../data-source.mjs';

const password = 'synthetic-test-password';

test('Windows launcher has CRLF and ASCII commands for every system code page', async () => {
  const bytes = await readFile(new URL('../start.cmd', import.meta.url));
  assert.ok(bytes.every(value => value < 128), 'CMD launcher must contain only ASCII bytes');
  const text = bytes.toString('ascii');
  assert.ok(text.includes('\r\n'), 'CMD launcher must use Windows newlines');
  assert.ok(!text.replaceAll('\r\n', '').includes('\n'), 'CMD launcher must not contain lone LF');
  assert.match(text, /cd \/d "%~dp0"/);
  assert.match(text, /node\.exe "%~dp0server\.mjs"/);
  assert.doesNotMatch(text, /chcp/);
  for (const target of text.matchAll(/^if .* goto ([a-z_]+)\r?$/gm)) {
    assert.ok(text.includes(`\r\n:${target[1]}\r\n`), `Missing jump label: ${target[1]}`);
  }
});

const sample = {
  asOf: '20260814',
  stockColumns: ['code', 'name', 'current_price'],
  stocks: [['2492', '測試股票', 100]],
  segments: {}, assumptions: {}
};
function encrypt(data) {
  const salt = randomBytes(16), iv = randomBytes(12), iterations = 10000;
  const key = pbkdf2Sync(password, salt, iterations, 32, 'sha256');
  const cipher = createCipheriv('aes-256-gcm', key, iv);
  const ciphertext = Buffer.concat([cipher.update(JSON.stringify(data)), cipher.final(), cipher.getAuthTag()]);
  return { iterations, salt: salt.toString('base64'), iv: iv.toString('base64'), ciphertext: ciphertext.toString('base64') };
}
async function fixture(t, options = {}) {
  const dir = await mkdtemp(join(tmpdir(), 'margin-pressure-'));
  const dataFile = join(dir, 'payload.enc');
  await writeFile(dataFile, JSON.stringify(encrypt(sample)));
  const app = await createApp({ dataFile, ...options });
  await new Promise(resolve => app.listen(0, '127.0.0.1', resolve));
  t.after(async () => { await new Promise(resolve => app.close(resolve)); await rm(dir, { recursive: true, force: true }); });
  const base = `http://127.0.0.1:${app.address().port}`;
  const request = (path, options) => fetch(base + path, options);
  const login = (value = password, headers = {}) => request('/api/login', {
    method: 'POST', headers: { 'Content-Type': 'application/json', ...headers }, body: JSON.stringify({ password: value })
  });
  return { request, login, base };
}

test('original AES-GCM format decrypts; wrong passwords and tampering fail', async () => {
  const encrypted = encrypt(sample);
  assert.deepEqual(JSON.parse((await decryptPayload(encrypted, password)).toString()), sample);
  await assert.rejects(decryptPayload(encrypted, 'incorrect'));
  const packed = Buffer.from(encrypted.ciphertext, 'base64'); packed[0] ^= 1;
  await assert.rejects(decryptPayload({ ...encrypted, ciphertext: packed.toString('base64') }, password));
  await assert.rejects(decryptPayload({ ...encrypted, iterations: 999999999 }, password));
});

test('authenticated data survives refresh; logout revokes the server session', async t => {
  const { request, login } = await fixture(t);
  assert.equal((await request('/api/data')).status, 401);
  assert.equal((await request('/api/input-status')).status, 401);
  assert.equal((await login('incorrect')).status, 401);
  assert.equal((await request('/api/data', { headers: { Cookie: 'mp_session=forged' } })).status, 401);
  const authenticated = await login();
  assert.equal(authenticated.status, 204);
  const setCookie = authenticated.headers.get('set-cookie');
  assert.match(setCookie, /HttpOnly/); assert.match(setCookie, /SameSite=Strict/);
  const Cookie = setCookie.split(';')[0];
  const inputStatus = await request('/api/input-status', { headers: { Cookie } });
  assert.equal(inputStatus.status, 200);
  assert.equal((await inputStatus.json()).analysisDate, sample.asOf);
  const targeted = await request('/api/input-status?target=20261030', { headers: { Cookie } });
  assert.equal(targeted.status, 200);
  assert.equal((await targeted.json()).targetDate, '20261030');
  assert.equal((await request('/api/input-status?target=invalid', { headers: { Cookie } })).status, 400);
  for (let i = 0; i < 2; i++) {
    const response = await request('/api/data', { headers: { Cookie } });
    assert.equal(response.status, 200); assert.deepEqual(await response.json(), sample);
    assert.equal(response.headers.get('cache-control'), 'no-store');
  }
  const logout = await request('/api/logout', { method: 'POST', headers: { Cookie } });
  assert.equal(logout.status, 204); assert.match(logout.headers.get('set-cookie'), /Max-Age=0/);
  assert.equal((await request('/api/data', { headers: { Cookie } })).status, 401);
  assert.equal((await request('/api/input-status', { headers: { Cookie } })).status, 401);
});

test('old session token is revoked on login rotation', async t => {
  const { request, login } = await fixture(t);
  const old = (await login()).headers.get('set-cookie').split(';')[0];
  const fresh = await login(password, { Cookie: old });
  assert.equal(fresh.status, 204);
  assert.equal((await request('/api/data', { headers: { Cookie: old } })).status, 401);
  const current = fresh.headers.get('set-cookie').split(';')[0];
  assert.equal((await request('/api/data', { headers: { Cookie: current } })).status, 200);
});

test('expired session cannot read data', async t => {
  const { request, login } = await fixture(t, { sessionTtl: 1 });
  const Cookie = (await login()).headers.get('set-cookie').split(';')[0];
  await new Promise(resolve => setTimeout(resolve, 10));
  assert.equal((await request('/api/data', { headers: { Cookie } })).status, 401);
});

test('source files, payload, and filesystem paths are never served', async t => {
  const { request } = await fixture(t);
  for (const path of ['/payload.enc', '/host/server.mjs', '/index.html', '/.git/config', '/%2e%2e/payload.enc']) {
    assert.equal((await request(path)).status, 404, path);
  }
  assert.deepEqual(await (await request('/healthz')).json(), { status: 'ok' });
  const redirect = await request('/margin-pressure/?stock=2492', { redirect: 'manual' });
  assert.equal(redirect.status, 302); assert.equal(redirect.headers.get('location'), '/?stock=2492');
});

test('cross-site login/logout and invalid JSON are rejected', async t => {
  const { request, login } = await fixture(t);
  assert.equal((await login(password, { Origin: 'https://other.example' })).status, 403);
  assert.equal((await request('/api/logout', { method: 'POST', headers: { Origin: 'https://other.example' } })).status, 403);
  assert.equal((await request('/api/login', { method: 'POST', body: '{}' })).status, 415);
  assert.equal((await request('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{' })).status, 400);
  assert.equal((await request('/api/login', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: 'null' })).status, 400);
});

test('login guessing is throttled', async t => {
  const { login } = await fixture(t);
  for (let i = 0; i < 10; i++) assert.equal((await login('incorrect')).status, 401);
  const blocked = await login('incorrect');
  assert.equal(blocked.status, 429); assert.ok(Number(blocked.headers.get('retry-after')) > 0);
});

test('HTTPS deployment uses Secure cookies and configured origin', async t => {
  const { login } = await fixture(t, { publicOrigin: 'https://radar.example' });
  const response = await login(password, { Origin: 'https://radar.example' });
  assert.equal(response.status, 204); assert.match(response.headers.get('set-cookie'), /; Secure/);
});

test('host adaptation preserves the stock model and hashes the delivered script', async t => {
  const original = await readFile(new URL('../../index.html', import.meta.url), 'utf8');
  const adapted = hostFrontend(original);
  assert.equal(adapted.slice(adapted.indexOf('    function init(){')), original.slice(original.indexOf('    function init(){')));
  assert.doesNotMatch(adapted, /crypto\.subtle|fetch\("payload\.enc"/);
  assert.match(adapted, /id="logout"/);
  assert.match(adapted, /id="excelFiles"/);
  assert.match(adapted, /fetch\('\/api\/input-status'/);
  assert.throws(() => hostFrontend('<html></html>'), /登入區段/);
  const { request } = await fixture(t);
  const response = await request('/?stock=2492');
  const html = await response.text();
  assert.equal(response.status, 200);
  const script = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)][0][1];
  const hash = createHash('sha256').update(script).digest('base64');
  assert.ok(response.headers.get('content-security-policy').includes(`'sha256-${hash}'`));
  new Function(script); // Syntax check only; browser runtime is checked separately.
});

async function readyFixture(t) {
  const dir = await mkdtemp(join(tmpdir(), 'margin-ready-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const ready = join(dir, 'ready'); await mkdir(join(ready, 'site'), { recursive: true });
  const fallbackFile = join(dir, 'payload.enc'); await writeFile(fallbackFile, JSON.stringify(encrypt(sample)));
  async function build(date, options = {}) {
    const data = { ...sample, asOf: date, editorial: { data_date: options.editorialDate || date } };
    const bytes = Buffer.from(JSON.stringify(encrypt(data)));
    await writeFile(join(ready, 'site/payload.enc'), bytes);
    await writeFile(join(ready, 'build-info.json'), JSON.stringify({ mode: 'local', as_of: options.receiptDate || date, stock_count: options.count || 1, payload_sha256: options.hash || createHash('sha256').update(bytes).digest('hex') }));
    return data;
  }
  return { dir, ready, fallbackFile, build };
}

test('completed local analysis is selected by verified receipt; failed sync and regressions keep last data', async t => {
  const { ready, fallbackFile, build } = await readyFixture(t);
  const reader = createDataSource({ fallbackFile, fallbackDate: sample.asOf, readyDirectory: ready, checkIntervalMs: 0 });
  assert.equal((await reader.read()).kind, 'bundled');
  await build('20261030');
  const current = await reader.read(); assert.equal(current.asOf, '20261030'); assert.equal(current.kind, 'completed_local');
  await writeFile(join(ready, 'site/payload.enc'), '{}');
  let retained = await reader.read(); assert.equal(retained.hash, current.hash); assert.match(retained.warning, /尚未通過驗證/);
  await build('20260821');
  retained = await reader.read(); assert.equal(retained.asOf, '20261030'); assert.match(retained.warning, /較舊/);
  await rm(join(ready, 'build-info.json'));
  assert.equal((await reader.read()).hash, current.hash);
});

test('new completed analysis changes real API data and footer; old sessions require login again', async t => {
  const { ready, build } = await readyFixture(t);
  const october = await build('20261030');
  const { request, login } = await fixture(t, { readyBuildDirectory: ready, sourceCheckIntervalMs: 0 });
  const cookie = (await login()).headers.get('set-cookie').split(';')[0];
  assert.deepEqual(await (await request('/api/data', { headers: { Cookie: cookie } })).json(), october);
  assert.match(await (await request('/')).text(), /資料日期：20261030/);
  const status = await (await request('/api/input-status', { headers: { Cookie: cookie } })).json();
  assert.equal(status.dataSource.kind, 'completed_local'); assert.equal(status.analysisDate, '20261030');
  const november = await build('20261103');
  const stale = await request('/api/data', { headers: { Cookie: cookie } });
  assert.equal(stale.status, 401); assert.equal((await stale.json()).code, 'data_updated');
  const newCookie = (await login()).headers.get('set-cookie').split(';')[0];
  assert.deepEqual(await (await request('/api/data', { headers: { Cookie: newCookie } })).json(), november);
});

test('hash-valid payload still rejects mismatched analysis date, stock count or AI judgment date', async t => {
  const { ready, build } = await readyFixture(t);
  const { login } = await fixture(t, { readyBuildDirectory: ready, sourceCheckIntervalMs: 0 });
  for (const options of [{ receiptDate: '20261103' }, { count: 2 }, { editorialDate: '20260814' }]) {
    await build('20261030', options);
    assert.equal((await login()).status, 500);
  }
});
