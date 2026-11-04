import { deflateRawSync } from 'node:zlib';
import { requiredSheets } from '../xlsx-dates.mjs';
function crc32(data) { let crc = 0xffffffff; for (const byte of data) { crc ^= byte; for (let bit = 0; bit < 8; bit++) crc = crc & 1 ? (crc >>> 1) ^ 0xedb88320 : crc >>> 1; } return (crc ^ 0xffffffff) >>> 0; }
export function zip(entries) {
  const local = [], central = []; let offset = 0;
  for (const [name, text] of Object.entries(entries)) {
    const plain = Buffer.from(text), packed = deflateRawSync(plain), filename = Buffer.from(name), crc = crc32(plain);
    const h = Buffer.alloc(30); h.writeUInt32LE(0x04034b50); h.writeUInt16LE(20, 4); h.writeUInt16LE(8, 8); h.writeUInt32LE(crc, 14); h.writeUInt32LE(packed.length, 18); h.writeUInt32LE(plain.length, 22); h.writeUInt16LE(filename.length, 26);
    const c = Buffer.alloc(46); c.writeUInt32LE(0x02014b50); c.writeUInt16LE(20, 4); c.writeUInt16LE(20, 6); c.writeUInt16LE(8, 10); c.writeUInt32LE(crc, 16); c.writeUInt32LE(packed.length, 20); c.writeUInt32LE(plain.length, 24); c.writeUInt16LE(filename.length, 28); c.writeUInt32LE(offset, 42);
    local.push(h, filename, packed); central.push(c, filename); offset += h.length + filename.length + packed.length;
  }
  const dir = Buffer.concat(central), end = Buffer.alloc(22); end.writeUInt32LE(0x06054b50); end.writeUInt16LE(central.length / 2, 8); end.writeUInt16LE(central.length / 2, 10); end.writeUInt32LE(dir.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...local, dir, end]);
}
export function workbook(kind, date, options = {}) {
  const sheets = requiredSheets[kind].filter(name => name !== options.omit);
  const entries = {
    'xl/workbook.xml': '<workbook><sheets>' + sheets.map((name, i) => `<sheet name="${name}" r:id="rId${i + 1}"/>`).join('') + '</sheets></workbook>',
    'xl/_rels/workbook.xml.rels': '<Relationships>' + sheets.map((_, i) => `<Relationship Id="rId${i + 1}" Target="worksheets/sheet${i + 1}.xml"/>`).join('') + '</Relationships>'
  };
  sheets.forEach((name, i) => { const d = options.mismatch === name ? '20261029' : date;
    entries[`xl/worksheets/sheet${i + 1}.xml`] = `<worksheet><sheetData><row r="3"><c r="C3" t="inlineStr"><is><t>${d}${name}</t></is></c></row></sheetData></worksheet>`;
  });
  return zip(entries);
}
