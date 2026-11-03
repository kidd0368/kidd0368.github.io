// Read CMoney date headers only. Never load stock values or execute workbook content.
import { open, stat } from 'node:fs/promises';
import { createReadStream } from 'node:fs';
import { inflateRawSync, createInflateRaw } from 'node:zlib';
import { posix } from 'node:path';
import { StringDecoder } from 'node:string_decoder';

export const requiredSheets = {
  history: ['開盤價', '最高價', '最低價', '收盤價', '成交量', '成交金額', '資買', '資賣', '融資現金償還', '資餘', '資券註'],
  margin: ['融資餘額'], prices: ['收盤價', '成交量', '成交金額']
};
const cache = new Map();
const xmlText = text => text.replace(/&#x([0-9a-f]+);|&#(\d+);|&(amp|lt|gt|quot|apos);/gi, (_, hex, decimal, named) => hex || decimal ? String.fromCodePoint(parseInt(hex || decimal, hex ? 16 : 10)) : ({ amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" })[named.toLowerCase()]);
const attrs = tag => Object.fromEntries([...tag.matchAll(/([\w:]+)\s*=\s*"([^"]*)"/g)].map(m => [m[1], xmlText(m[2])]));
async function bytes(handle, position, length) {
  if (length < 0 || length > 32 * 1024 * 1024) throw new Error('ZIP區塊大小不符');
  const buffer = Buffer.alloc(length); let offset = 0;
  while (offset < length) { const result = await handle.read(buffer, offset, length - offset, position + offset); if (!result.bytesRead) throw new Error('檔案尚未完整同步'); offset += result.bytesRead; }
  return buffer;
}
async function archive(handle, size) {
  const tailSize = Math.min(size, 65557), tail = await bytes(handle, size - tailSize, tailSize);
  let eocd = -1;
  for (let i = tail.length - 22; i >= 0; i--) if (tail.readUInt32LE(i) === 0x06054b50 && i + 22 + tail.readUInt16LE(i + 20) === tail.length) { eocd = i; break; }
  if (eocd < 0 || tail.readUInt16LE(eocd + 4) || tail.readUInt16LE(eocd + 6)) throw new Error('不支援的Excel壓縮格式');
  const count = tail.readUInt16LE(eocd + 10), length = tail.readUInt32LE(eocd + 12), start = tail.readUInt32LE(eocd + 16);
  if (count === 65535 || length > 4 * 1024 * 1024 || start + length > size) throw new Error('Excel目錄超出檢查限制');
  const central = await bytes(handle, start, length), entries = new Map(); let at = 0;
  for (let i = 0; i < count; i++) {
    if (at + 46 > central.length || central.readUInt32LE(at) !== 0x02014b50) throw new Error('Excel目錄不完整');
    const nameSize = central.readUInt16LE(at + 28), extra = central.readUInt16LE(at + 30), comment = central.readUInt16LE(at + 32);
    const end = at + 46 + nameSize + extra + comment;
    if (end > central.length) throw new Error('Excel目錄不完整');
    const name = central.subarray(at + 46, at + 46 + nameSize).toString('utf8');
    entries.set(name, { flags: central.readUInt16LE(at + 8), method: central.readUInt16LE(at + 10), compressed: central.readUInt32LE(at + 20), size: central.readUInt32LE(at + 24), offset: central.readUInt32LE(at + 42) });
    at = end;
  }
  return entries;
}
async function range(handle, entry) {
  if (!entry || entry.flags & 1 || ![0, 8].includes(entry.method)) throw new Error('工作表不存在或壓縮格式不支援');
  const header = await bytes(handle, entry.offset, 30);
  if (header.readUInt32LE(0) !== 0x04034b50) throw new Error('Excel區塊不完整');
  return entry.offset + 30 + header.readUInt16LE(26) + header.readUInt16LE(28);
}
async function smallXml(handle, entry, limit) {
  if (!entry || entry.size > limit || entry.compressed > limit) throw new Error('日期索引超出檢查限制');
  const start = await range(handle, entry), packed = await bytes(handle, start, entry.compressed);
  const plain = entry.method === 8 ? inflateRawSync(packed, { maxOutputLength: limit }) : packed;
  if (plain.length !== entry.size) throw new Error('日期索引不完整');
  return plain.toString('utf8');
}
async function headerRow(file, handle, entry) {
  const start = await range(handle, entry);
  const raw = createReadStream(file, { start, end: start + entry.compressed - 1 });
  const stream = entry.method === 8 ? raw.pipe(createInflateRaw()) : raw;
  // Also propagate input I/O errors to the inflate stream.
  if (stream !== raw) raw.on('error', error => stream.destroy(error));
  let xml = ''; const decoder = new StringDecoder('utf8');
  try {
    for await (const chunk of stream) {
      xml += decoder.write(chunk);
      const match = xml.match(/<row\b[^>]*\br="3"[^>]*>[\s\S]*?<\/row>/);
      if (match) return match[0];
      if (xml.length > 2 * 1024 * 1024) throw new Error('前2 MB內找不到CMoney日期表頭');
    }
    throw new Error('找不到CMoney第3列日期表頭');
  } finally { stream.destroy(); if (raw !== stream) raw.destroy(); }
}
function datesFromRow(xml, shared) {
  const dates = [];
  for (const cell of xml.matchAll(/<c\b([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g)) {
    const a = attrs(cell[1]), column = (a.r || '').match(/^[A-Z]+/)?.[0];
    if (!column || ['A', 'B'].includes(column)) continue;
    const body = cell[2] || '', value = body.match(/<v\b[^>]*>([\s\S]*?)<\/v>/)?.[1];
    const text = a.t === 's' ? shared[Number(value)] : a.t === 'inlineStr' ? [...body.matchAll(/<t\b[^>]*>([\s\S]*?)<\/t>/g)].map(m => xmlText(m[1])).join('') : value;
    const match = typeof text === 'string' && text.trim().match(/^(\d{8})(?:\D|$)/);
    if (!match) continue;
    const d = match[1], iso = `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`;
    const parsed = new Date(iso + 'T00:00:00Z');
    if (!Number.isNaN(+parsed) && parsed.toISOString().slice(0, 10) === iso) dates.push(d);
  }
  if (!dates.length || dates.some((date, i) => i && date <= dates[i - 1])) throw new Error('日期表頭缺失或順序不符');
  return dates;
}
async function inspect(file, kind) {
  const handle = await open(file, 'r');
  try {
    const before = await handle.stat(), entries = await archive(handle, before.size);
    const workbook = await smallXml(handle, entries.get('xl/workbook.xml'), 1024 * 1024);
    const rels = await smallXml(handle, entries.get('xl/_rels/workbook.xml.rels'), 1024 * 1024);
    const targets = new Map([...rels.matchAll(/<Relationship\b([^>]*?)\/?\s*>/g)].map(m => { const a = attrs(m[1]); return [a.Id, a.TargetMode === 'External' ? '' : a.Target]; }));
    const sheets = new Map([...workbook.matchAll(/<sheet\b([^>]*?)\/?\s*>/g)].map(m => { const a = attrs(m[1]), target = targets.get(a['r:id']) || ''; return [a.name, target.startsWith('/') ? target.slice(1) : posix.normalize(posix.join('xl', target))]; }));
    const sharedXml = entries.has('xl/sharedStrings.xml') ? await smallXml(handle, entries.get('xl/sharedStrings.xml'), 16 * 1024 * 1024) : '';
    const shared = [...sharedXml.matchAll(/<si\b[^>]*>([\s\S]*?)<\/si>/g)].map(m => [...m[1].matchAll(/<t\b[^>]*>([\s\S]*?)<\/t>/g)].map(t => xmlText(t[1])).join(''));
    let reference; const checked = [];
    for (const name of requiredSheets[kind] || []) {
      const dates = datesFromRow(await headerRow(file, handle, entries.get(sheets.get(name))), shared);
      if (reference && (dates.length !== reference.length || dates.some((date, i) => date !== reference[i]))) throw new Error(`「${name}」日期與其他工作表不一致`);
      reference = dates; checked.push(name);
    }
    if (!reference) throw new Error('沒有可檢查的工作表');
    const after = await handle.stat(), pathAfter = await stat(file);
    if (before.size !== after.size || before.mtimeMs !== after.mtimeMs || before.ino !== pathAfter.ino || before.mtimeMs !== pathAfter.mtimeMs) throw new Error('Excel正在更新，請儲存並關閉後重試');
    return { code: 'header_verified', lastDate: reference.at(-1), firstDate: reference[0], dateCount: reference.length, sheets: checked, note: '已核對各必要工作表的日期表頭；個股數值完整性仍須重算流程驗證。' };
  } finally { await handle.close(); }
}
export async function inspectXlsxDates(file, kind) {
  try {
    const s = await stat(file), key = `${file}\0${kind}`, signature = `${s.size}:${s.mtimeMs}:${s.ctimeMs}:${s.ino}`;
    if (cache.get(key)?.signature === signature) return cache.get(key).result;
    const result = await inspect(file, kind);
    if (cache.size > 30) cache.delete(cache.keys().next().value);
    cache.set(key, { signature, result }); return result;
  } catch (error) { return { code: 'unknown', lastDate: null, note: `無法確認檔內日期：${error.code || error.message}。請確認Excel已同步、儲存並關閉。` }; }
}
