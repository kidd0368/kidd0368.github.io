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

export async function readInputStatus(directory, analysisDate, options = {}) {
  const targetDate = options.targetDate || taipeiCalendarDate(options.now || new Date());
  if (typeof targetDate !== 'string' || !/^\d{8}$/.test(targetDate) || !validDate(targetDate)) {
    const error = new Error('Invalid target date'); error.status = 400; throw error;
  }
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
  const available = listings.some(item => item.available);
  const displayDate = value => `${value.slice(0, 4)}/${value.slice(4, 6)}/${value.slice(6, 8)}`;
  for (const file of files) {
    let code, label;
    if (!available) { code = 'unavailable'; label = '無法檢查'; }
    else if (!file.latest) { code = 'missing'; label = '缺少檔案'; }
    else if (file.latest.date < targetDate) { code = 'outdated'; label = '尚未更新'; }
    else if (file.duplicate) { code = 'duplicate'; label = '同日重複，需確認'; }
    else if (file.latest.date > targetDate) { code = 'future'; label = '檔名超過目標，需核對'; }
    else { code = 'at_target'; label = '檔名已到目標'; }
    file.freshness = { code, label, targetDate, contentVerified: false };
    file.expectedTargetName = file.expectedName.replace('YYYYMMDD', targetDate);
    file.action = code === 'outdated' || code === 'missing'
      ? `請重新匯出 ${file.expectedTargetName}，並確認檔內最新完整交易日。`
      : code === 'at_target' ? '檔名日期符合；Excel內容仍須由原本重算流程檢核。'
      : code === 'future' ? '請核對目標資料日及檔內最新完整交易日。'
      : code === 'duplicate' ? '同一資料夾同日請只保留一份應使用的檔案。'
      : '請核對來源資料夾是否存在或可讀取。';
  }
  const counts = Object.fromEntries(['outdated', 'missing', 'at_target', 'future', 'duplicate', 'unavailable'].map(code => [code, files.filter(file => file.freshness.code === code).length]));
  const websiteCode = String(analysisDate) < targetDate ? 'outdated' : String(analysisDate) > targetDate ? 'ahead' : 'at_target';
  const website = {
    code: websiteCode,
    label: websiteCode === 'outdated'
      ? `網站資料仍為 ${displayDate(String(analysisDate))}，尚未套用到目標 ${displayDate(targetDate)}。`
      : websiteCode === 'ahead' ? `網站資料日 ${displayDate(String(analysisDate))} 晚於目前選定的目標日。`
      : `網站資料日已達目標 ${displayDate(targetDate)}。`
  };
  const overdue = files.filter(file => ['outdated', 'missing'].includes(file.freshness.code));
  let alert;
  if (!available) alert = summary;
  else if (overdue.length) alert = `目標 ${displayDate(targetDate)}：${overdue.map(file => file.expectedName.replace(' YYYYMMDD.xlsx', '') + (file.latest ? `（目前檔名 ${displayDate(file.latest.date)}）` : '（缺檔）')).join('、')} 尚未更新。`;
  else if (counts.future || counts.duplicate) alert = '來源檔名超過目標日或有重複檔，請逐項核對；目前不標示為已更新。';
  else if (websiteCode === 'outdated') alert = `三份 Excel 的檔名都已達 ${displayDate(targetDate)}，但網站數據尚未套用重算結果。`;
  else alert = `三份 Excel 的檔名都已達 ${displayDate(targetDate)}；檔內交易日與欄位仍須由原本重算流程檢核。`;
  const tone = !available || overdue.length || websiteCode === 'outdated' || !anchor.found ? 'danger' : counts.future || counts.duplicate ? 'warning' : 'info';
  return { analysisDate: String(analysisDate), sourceDirectory: root, checkedAt: new Date().toISOString(), available, files, anchor, summary, dateBasis: 'filename_only', targetDate, targetSource: options.targetDate ? 'selected' : 'taipei_today', counts, website, alert, tone };
}

export function taipeiCalendarDate(now = new Date()) {
  const parts = new Intl.DateTimeFormat('en', { timeZone: 'Asia/Taipei', year: 'numeric', month: '2-digit', day: '2-digit' }).formatToParts(now);
  return ['year', 'month', 'day'].map(type => parts.find(part => part.type === type).value).join('');
}
