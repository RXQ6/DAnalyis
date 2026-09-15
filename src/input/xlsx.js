import { AgentError } from '../errors.js';
import { unzipEntries } from './zip.js';

function decodeXml(value = '') {
  return value.replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'").replace(/&amp;/g, '&').replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)))
    .replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16)));
}

function columnIndex(reference) {
  const letters = reference.match(/^[A-Z]+/i)?.[0] || '';
  let value = 0;
  for (const char of letters.toUpperCase()) value = value * 26 + char.charCodeAt(0) - 64;
  return value - 1;
}

function parseSharedStrings(xml = '') {
  return [...xml.matchAll(/<si\b[^>]*>([\s\S]*?)<\/si>/g)].map(match =>
    [...match[1].matchAll(/<t\b[^>]*>([\s\S]*?)<\/t>/g)].map(part => decodeXml(part[1])).join(''));
}

function dateStyleIndexes(xml = '') {
  const custom = new Map([...xml.matchAll(/<numFmt\b[^>]*numFmtId="(\d+)"[^>]*formatCode="([^"]+)"[^>]*\/?\s*>/g)]
    .map(match => [Number(match[1]), decodeXml(match[2])]));
  const builtInDates = new Set([14, 15, 16, 17, 22, 27, 30, 36, 45, 46, 47, 50, 57]);
  const dateStyles = new Set();
  const cellXfs = xml.match(/<cellXfs\b[^>]*>([\s\S]*?)<\/cellXfs>/)?.[1] || '';
  [...cellXfs.matchAll(/<xf\b([^>]*)\/?\s*>/g)].forEach((match, index) => {
    const id = Number(match[1].match(/numFmtId="(\d+)"/)?.[1] || 0);
    const format = custom.get(id)?.replace(/\[[^\]]*\]|"[^"]*"|\\./g, '') || '';
    if (builtInDates.has(id) || /[ymdhis]/i.test(format)) dateStyles.add(index);
  });
  return dateStyles;
}

function excelDate(serial) {
  const wholeDays = Math.floor(serial);
  const epoch = Date.UTC(1899, 11, 30);
  return new Date(epoch + wholeDays * 86400000).toISOString().slice(0, 10);
}

function firstSheetPath(entries) {
  const workbook = entries.get('xl/workbook.xml')?.toString('utf8');
  const rels = entries.get('xl/_rels/workbook.xml.rels')?.toString('utf8');
  if (!workbook || !rels) return 'xl/worksheets/sheet1.xml';
  const first = workbook.match(/<sheet\b[^>]*(?:r:id|id)="([^"]+)"[^>]*\/?\s*>/);
  if (!first) return 'xl/worksheets/sheet1.xml';
  const escaped = first[1].replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const relation = rels.match(new RegExp(`<Relationship\\b[^>]*Id="${escaped}"[^>]*Target="([^"]+)"`));
  if (!relation) return 'xl/worksheets/sheet1.xml';
  const target = relation[1].replace(/^\//, '');
  return target.startsWith('xl/') ? target : `xl/${target.replace(/^\.\//, '')}`;
}

export function parseXlsx(buffer) {
  let entries;
  try { entries = unzipEntries(buffer); }
  catch (error) { if (error instanceof AgentError) throw error; throw new AgentError('unreadable_file', 'XLSX 文件损坏或无法读取。'); }
  const sheetPath = firstSheetPath(entries);
  const xml = entries.get(sheetPath)?.toString('utf8');
  if (!xml) throw new AgentError('unreadable_file', 'XLSX 中未找到可读取的工作表。');
  const shared = parseSharedStrings(entries.get('xl/sharedStrings.xml')?.toString('utf8'));
  const dateStyles = dateStyleIndexes(entries.get('xl/styles.xml')?.toString('utf8'));
  const rows = [];
  for (const rowMatch of xml.matchAll(/<row\b[^>]*>([\s\S]*?)<\/row>/g)) {
    const row = [];
    for (const cell of rowMatch[1].matchAll(/<c\b([^>]*)>([\s\S]*?)<\/c>|<c\b([^>]*)\/>/g)) {
      const attrs = cell[1] || cell[3] || '';
      const body = cell[2] || '';
      const ref = attrs.match(/\br="([^"]+)"/)?.[1] || `A${rows.length + 1}`;
      const type = attrs.match(/\bt="([^"]+)"/)?.[1] || 'n';
      const style = Number(attrs.match(/\bs="(\d+)"/)?.[1] || 0);
      const raw = body.match(/<v>([\s\S]*?)<\/v>/)?.[1] ?? body.match(/<t\b[^>]*>([\s\S]*?)<\/t>/)?.[1] ?? '';
      let value = decodeXml(raw);
      if (type === 's') value = shared[Number(value)] ?? '';
      else if (type === 'b') value = value === '1' ? 'true' : 'false';
      else if (type === 'n' && value !== '' && dateStyles.has(style)) value = excelDate(Number(value));
      row[columnIndex(ref)] = value;
    }
    rows.push(Array.from({ length: Math.max(0, row.length) }, (_, index) => row[index] ?? ''));
  }
  while (rows.length && rows.at(-1).every(value => value === '')) rows.pop();
  if (rows.length < 2) throw new AgentError('empty_data', '文件没有可分析的数据行。');
  return rows;
}
