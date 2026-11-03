import { readdir } from 'node:fs/promises';
import { resolve, join } from 'node:path';

const definitions = [
  { id: 'history', pattern: /^chatgpt\s+計算融資維持率\s+(\d{8})\.xlsx$/i, name: 'chatgpt 計算融資維持率 YYYYMMDD.xlsx', purpose: '近180個交易日的股價、成交量／金額、融資買進／賣出／現金償還／餘額；保留原 CMoney 匯出格式與固定基準日。' },
  { id: 'margin', pattern: /^融資融券\s+(\d{8})\.xlsx$/i, name: '融資融券 YYYYMMDD.xlsx', purpose: '長期融資餘額與歷史回溯，供上一輪融資部位與成本情境計算。' },
  { id: 'prices', pattern: /^個股日k線\s+(\d{8})\.xlsx$/i, name: '個股日k線 YYYYMMDD.xlsx', purpose: '長期股價、成交量與成交金額，供歷史平均成交成本與回檔幅度計算。' }
];

function validDate(value) {
  const iso = `${value.slice(0, 4)}-${value.slice(4, 6)}-${value.slice(6, 8)}`;
  const parsed = new Date(`${iso}T00:00:00Z`);
  return !Number.isNaN(+parsed) && parsed.toISOString().slice(0, 10) === iso;
}
async function entries(directory) {
  try { return { available: true, files: (await readdir(directory, { withFileTypes: true })).filter(e => e.isFile()).map(e => e.name) }; }
  catch (error) {
    if (['ENOENT', 'ENOTDIR', 'EACCES', 'EPERM'].includes(error.code)) return { available: false, files: [] };
    throw error;
  }
}

export async function readInputStatus(directory, analysisDate) {
  const root = resolve(directory);
  const legacy = join(root, 'gpt 維持率追蹤');
  const locations = [root, legacy];
  const listings = await Promise.all(locations.map(entries));
  const files = definitions.map(definition => {
    const candidates = locations.flatMap((location, rank) => listings[rank].files.flatMap(name => {
      if (rank > 0 && definition.id !== 'history') return [];
      const match = name.match(definition.pattern);
      return match && validDate(match[1]) ? [{ name, date: match[1], path: join(location, name), rank }] : [];
    })).sort((a, b) => b.date.localeCompare(a.date) || a.rank - b.rank || a.name.localeCompare(b.name));
    const latest = candidates[0] || null;
    const sameDateCount = latest ? candidates.filter(c => c.date === latest.date && c.rank === latest.rank).length : 0;
    return { id: definition.id, expectedName: definition.name, purpose: definition.purpose, latest, duplicate: sameDateCount > 1 };
  });
  const anchorDirectory = join(legacy, '備份');
  const anchorFiles = (await entries(anchorDirectory)).files.filter(name => /^融資維持率\s+20260728\.xlsx$/i.test(name));
  const fallbackAnchor = listings[1].files.filter(name => /^融資維持率\s+20260728\.xlsx$/i.test(name));
  const anchorName = anchorFiles[0] || fallbackAnchor[0];
  const anchor = {
    expectedName: '融資維持率 20260728.xlsx', dataDate: '20260727',
    found: Boolean(anchorName), path: anchorName ? join(anchorFiles.length ? anchorDirectory : legacy, anchorName) : null,
    note: '永久保留；這是2026/07/27最後可用維持率的固定基準，不是每日更新檔。'
  };
  const missing = files.filter(file => !file.latest).length;
  const dates = files.filter(file => file.latest).map(file => file.latest.date);
  let summary;
  if (!listings.some(item => item.available)) summary = '找不到來源資料夾；請核對來源路徑或 INPUT_DIRECTORY 設定。';
  else if (missing) summary = `尚未找到 ${missing} 份每日 Excel，請更新並存入來源資料夾。`;
  else if (files.some(file => file.duplicate)) summary = '同一資料夾有同日重複檔；請確認應使用哪一份。';
  else if (new Set(dates).size > 1) summary = '三份 Excel 的檔名日期不同，請補齊到同一個目標匯出日，再核對檔內交易日。';
  else if (dates[0] > String(analysisDate)) summary = '已找到較新的 Excel 檔名；網站仍須完成重算、AI判讀與資料套用。';
  else if (dates[0] < String(analysisDate)) summary = '來源檔名日期早於網站資料日，請核對實際選用的檔案。';
  else summary = '來源檔名日期與網站資料日相同；仍請以檔內最新完整交易日核對。';
  return { analysisDate: String(analysisDate), sourceDirectory: root, checkedAt: new Date().toISOString(), available: listings.some(item => item.available), files, anchor, summary, dateBasis: 'filename_only' };
}
