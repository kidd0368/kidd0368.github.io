import { readFile } from 'node:fs/promises';
import { join, resolve } from 'node:path';
import { createHash } from 'node:crypto';

export function createDataSource({ fallbackFile, fallbackDate, readyDirectory, enabled = true, checkIntervalMs = 1000 }) {
  let current = null, pending = null, lastCheck = 0;
  async function snapshot(file, date, kind, receipt = null) {
    const bytes = await readFile(file);
    if (bytes.length > 32 * 1024 * 1024) throw new Error('分析資料超過32 MB。');
    const hash = createHash('sha256').update(bytes).digest('hex');
    if (receipt && hash !== receipt.payload_sha256) throw new Error('分析資料與建置紀錄雜湊不一致。');
    return { encrypted: JSON.parse(bytes.toString('utf8')), hash, asOf: date, file: resolve(file), kind, receipt, warning: null };
  }
  async function refresh() {
    const fallback = await snapshot(fallbackFile, fallbackDate, 'bundled');
    let chosen = fallback;
    if (enabled && readyDirectory) {
      let receiptExists = false;
      try {
        const raw = await readFile(join(readyDirectory, 'build-info.json'), 'utf8');
        receiptExists = true;
        const receipt = JSON.parse(raw.replace(/^\uFEFF/, ''));
        if (receipt.mode !== 'local' || !/^\d{8}$/.test(receipt.as_of || '') || !/^[0-9a-f]{64}$/.test(receipt.payload_sha256 || '') || !Number.isInteger(receipt.stock_count) || receipt.stock_count < 1) throw new Error('本機建置紀錄格式不符。');
        if (!fallbackDate || receipt.as_of >= fallbackDate) chosen = await snapshot(join(readyDirectory, 'site', 'payload.enc'), receipt.as_of, 'completed_local', receipt);
      } catch (error) {
        if (error.code !== 'ENOENT' || receiptExists) {
          chosen = { ...(current || fallback), warning: '已完成分析來源尚未通過驗證，暫時保留上次資料。' };
        } else if (current?.kind === 'completed_local') {
          chosen = { ...current, warning: '已完成分析來源暫時無法讀取，保留上次資料。' };
        }
      }
    }
    if (current?.asOf && chosen.asOf && chosen.asOf < current.asOf) chosen = { ...current, warning: '找到的分析資料日期較舊，保留目前版本。' };
    current = chosen;
    return current;
  }
  return {
    async read() {
      if (pending) return pending;
      if (current && Date.now() - lastCheck < checkIntervalMs) return current;
      lastCheck = Date.now();
      pending = refresh();
      try { return await pending; } finally { pending = null; }
    }
  };
}

export function dataSourceInfo(source) {
  return { kind: source.kind, analysisDate: source.asOf || null, file: source.file, warning: source.warning, label: source.kind === 'completed_local' ? '原本本機版已完成的分析資料（已驗證建置雜湊）' : '此主機版資料夾內的分析資料' };
}
