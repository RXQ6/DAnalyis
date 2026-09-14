import { AgentError } from '../errors.js';

function detectDelimiter(text) {
  const sample = text.split(/\r?\n/, 5).filter(Boolean);
  const candidates = [',', '\t', ';'];
  let best = { delimiter: ',', score: -Infinity };
  for (const delimiter of candidates) {
    const counts = sample.map(line => {
      let count = 0, quoted = false;
      for (let i = 0; i < line.length; i++) {
        if (line[i] === '"') quoted = !quoted;
        else if (!quoted && line[i] === delimiter) count++;
      }
      return count;
    });
    const headerCount = counts[0] || 0;
    const deviations = counts.slice(1).reduce((sum, value) => sum + Math.abs(value - headerCount), 0);
    const score = headerCount * 10 - deviations;
    if (score > best.score) best = { delimiter, score };
  }
  return best.delimiter;
}

export function parseCsv(buffer) {
  let text = buffer.toString('utf8');
  if (text.includes('\ufffd')) throw new AgentError('encoding_error', 'CSV 不是有效的 UTF-8 编码。');
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  if (!text.trim()) throw new AgentError('empty_file', '文件为空，无法分析。');
  const delimiter = detectDelimiter(text);
  const records = [];
  let row = [], value = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (quoted) {
      if (char === '"' && text[i + 1] === '"') { value += '"'; i++; }
      else if (char === '"') quoted = false;
      else value += char;
    } else if (char === '"') quoted = true;
    else if (char === delimiter) { row.push(value); value = ''; }
    else if (char === '\n') {
      row.push(value.replace(/\r$/, '')); records.push(row); row = []; value = '';
    } else value += char;
  }
  if (quoted) throw new AgentError('unreadable_file', 'CSV 引号未闭合，无法可靠读取。');
  if (value.length || row.length) { row.push(value.replace(/\r$/, '')); records.push(row); }
  while (records.length && records.at(-1).every(cell => cell === '')) records.pop();
  if (records.length < 2) throw new AgentError('empty_data', '文件没有可分析的数据行。');
  return records;
}
