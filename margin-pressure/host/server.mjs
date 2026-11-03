import { createServer } from 'node:http';
import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { resolve } from 'node:path';
import { createDecipheriv, createHash, pbkdf2, randomBytes } from 'node:crypto';
import { promisify } from 'node:util';
import { hostFrontend } from './frontend.mjs';

const deriveKey = promisify(pbkdf2);
const here = fileURLToPath(new URL('.', import.meta.url));
const COOKIE = 'mp_session';
const TTL = 12 * 60 * 60 * 1000;
const ATTEMPT_WINDOW = 15 * 60 * 1000;
const MAX_ATTEMPTS = 10;

export async function decryptPayload(encrypted, password) {
  if (typeof password !== 'string' || !password || Buffer.byteLength(password) > 1024) throw new Error('password');
  if (!Number.isInteger(encrypted.iterations) || encrypted.iterations < 10000 || encrypted.iterations > 2000000) throw new Error('iterations');
  const salt = Buffer.from(encrypted.salt, 'base64');
  const iv = Buffer.from(encrypted.iv, 'base64');
  const packed = Buffer.from(encrypted.ciphertext, 'base64');
  if (salt.length < 8 || iv.length !== 12 || packed.length < 17) throw new Error('payload');
  const key = await deriveKey(password, salt, encrypted.iterations, 32, 'sha256');
  try {
    const decipher = createDecipheriv('aes-256-gcm', key, iv);
    decipher.setAuthTag(packed.subarray(-16));
    const plain = Buffer.concat([decipher.update(packed.subarray(0, -16)), decipher.final()]);
    const data = JSON.parse(plain.toString('utf8'));
    if (!Array.isArray(data.stockColumns) || !Array.isArray(data.stocks) || !data.segments || !data.asOf) throw new Error('schema');
    return plain;
  } finally { key.fill(0); }
}

export async function createApp(options = {}) {
  const dataFile = resolve(options.dataFile || process.env.DATA_FILE || resolve(here, '../payload.enc'));
  const templateFile = resolve(options.templateFile || process.env.TEMPLATE_FILE || resolve(here, '../index.html'));
  const publicOriginValue = options.publicOrigin ?? process.env.PUBLIC_ORIGIN ?? '';
  const publicOrigin = publicOriginValue ? new URL(publicOriginValue).origin : '';
  const secureCookie = publicOrigin.startsWith('https://');
  const sessionTtl = options.sessionTtl ?? TTL;
  const encryptedText = await readFile(dataFile, 'utf8');
  if (encryptedText.length > 32 * 1024 * 1024) throw new Error('資料檔超過 32 MB。');
  const encrypted = JSON.parse(encryptedText);
  const html = hostFrontend(await readFile(templateFile, 'utf8'));
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)]
    .map(match => `'sha256-${createHash('sha256').update(match[1]).digest('base64')}'`).join(' ');
  const sessions = new Map();
  const attempts = new Map();
  let activeDecryptions = 0;

  function cleanup() {
    const now = Date.now();
    for (const [key, entry] of sessions) if (entry.expires <= now) sessions.delete(key);
    for (const [key, entry] of attempts) if (entry.expires <= now) attempts.delete(key);
  }
  const timer = setInterval(cleanup, 60000);
  timer.unref();
  function sessionToken(req) {
    return (req.headers.cookie || '').split(';').map(s => s.trim()).find(s => s.startsWith(`${COOKIE}=`))?.slice(COOKIE.length + 1);
  }
  function cookie(token, maxAge) {
    return `${COOKIE}=${token}; HttpOnly; SameSite=Strict; Path=/; Max-Age=${maxAge}${secureCookie ? '; Secure' : ''}`;
  }
  function send(res, status, value, type = 'application/json; charset=utf-8') {
    res.writeHead(status, { 'Content-Type': type });
    res.end(status === 204 ? undefined : type.startsWith('application/json') && !Buffer.isBuffer(value) ? JSON.stringify(value) : value);
  }
  async function body(req) {
    let size = 0;
    const chunks = [];
    for await (const chunk of req) {
      size += chunk.length;
      if (size > 8192) { const error = new Error('body'); error.status = 413; throw error; }
      chunks.push(chunk);
    }
    try { return JSON.parse(Buffer.concat(chunks).toString('utf8')); }
    catch { const error = new Error('body'); error.status = 400; throw error; }
  }
  const server = createServer(async (req, res) => {
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('X-Frame-Options', 'DENY');
    res.setHeader('Content-Security-Policy', `default-src 'none'; script-src ${scripts}; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'; frame-ancestors 'none'`);
    try {
      const url = new URL(req.url, 'http://localhost');
      const path = url.pathname;
      if (req.method === 'POST') {
        const expectedOrigin = publicOrigin || `http://${req.headers.host}`;
        if (req.headers.origin && req.headers.origin !== expectedOrigin) return send(res, 403, { error: '請從本站登入。' });
      }
      if (req.method === 'GET' && path === '/healthz') return send(res, 200, { status: 'ok' });
      if (req.method === 'GET' && ['/margin-pressure', '/margin-pressure/'].includes(path)) {
        res.writeHead(302, { Location: `/${url.search}` }); return res.end();
      }
      if (req.method === 'GET' && path === '/') return send(res, 200, html, 'text/html; charset=utf-8');
      if (req.method === 'POST' && path === '/api/login') {
        if (!/^application\/json(?:\s*;|$)/i.test(req.headers['content-type'] || '')) return send(res, 415, { error: '請使用 JSON 登入。' });
        cleanup();
        const address = req.socket.remoteAddress;
        let entry = attempts.get(address);
        if (!entry) {
          if (attempts.size >= 1000) return send(res, 503, { error: '登入忙碌中，請稍後重試。' });
          entry = { count: 0, expires: Date.now() + ATTEMPT_WINDOW }; attempts.set(address, entry);
        }
        if (entry.count >= MAX_ATTEMPTS) {
          res.setHeader('Retry-After', String(Math.ceil((entry.expires - Date.now()) / 1000)));
          return send(res, 429, { error: '登入嘗試過多，請 15 分鐘後重試。' });
        }
        if (activeDecryptions >= 4) return send(res, 503, { error: '登入忙碌中，請稍後重試。' });
        entry.count++;
        const input = await body(req);
        if (!input || typeof input.password !== 'string') return send(res, 400, { error: '請輸入密碼。' });
        if (activeDecryptions >= 4) return send(res, 503, { error: '登入忙碌中，請稍後重試。' });
        activeDecryptions++;
        let data;
        try { data = await decryptPayload(encrypted, input.password); }
        catch { return send(res, 401, { error: '密碼不正確，或資料檔無法解鎖。' }); }
        finally { activeDecryptions--; input.password = ''; }
        const oldToken = sessionToken(req);
        if (oldToken) sessions.delete(oldToken);
        if (sessions.size >= 20) sessions.delete(sessions.keys().next().value);
        const token = randomBytes(32).toString('hex');
        sessions.set(token, { data, expires: Date.now() + sessionTtl });
        res.setHeader('Set-Cookie', cookie(token, Math.ceil(sessionTtl / 1000)));
        return send(res, 204);
      }
      if (req.method === 'POST' && path === '/api/logout') {
        sessions.delete(sessionToken(req));
        res.setHeader('Set-Cookie', cookie('', 0));
        return send(res, 204);
      }
      if (req.method === 'GET' && path === '/api/data') {
        const token = sessionToken(req);
        const session = sessions.get(token);
        if (!session || session.expires <= Date.now()) {
          sessions.delete(token); res.setHeader('Set-Cookie', cookie('', 0));
          return send(res, 401, { error: '請先登入。' });
        }
        return send(res, 200, session.data);
      }
      return send(res, 404, { error: '找不到頁面。' });
    } catch (error) {
      if (!res.headersSent) send(res, error.status || 500, { error: error.status ? '請求格式不正確。' : '主機處理失敗，請稍後重試。' });
      else res.end();
    }
  });
  server.requestTimeout = 10000;
  server.headersTimeout = 12000;
  server.keepAliveTimeout = 5000;
  server.on('close', () => { clearInterval(timer); sessions.clear(); attempts.clear(); });
  return server;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    const host = process.env.HOST || '127.0.0.1';
    const port = Number(process.env.PORT || 8787);
    if (!Number.isInteger(port) || port < 1 || port > 65535) throw new Error('PORT 必須介於 1 與 65535。');
    const app = await createApp();
    app.on('error', error => { console.error(`主機無法啟動：${error.code || 'unknown'}`); process.exitCode = 1; });
    app.listen(port, host, () => console.log(`融資賣壓風險雷達已啟動：http://${host}:${port}/`));
    for (const signal of ['SIGTERM', 'SIGINT']) process.on(signal, () => { app.close(); app.closeIdleConnections(); });
  } catch (error) { console.error(`主機無法啟動：${error.message}`); process.exitCode = 1; }
}
