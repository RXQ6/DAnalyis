import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { validateInput } from '../input/validate.js';
import { loadTable } from '../input/load.js';
import { parseDate, profileTable } from '../profile.js';

export function loadDataset(filePath) {
  const input = validateInput(filePath, 'dataset registration');
  const table = loadTable(filePath, input.extension || path.extname(filePath).toLowerCase());
  return { input, table, profile: profileTable(table) };
}

export function datasetSummary(filePath) {
  const { input, table, profile } = loadDataset(filePath);
  const dateRanges = profile.columns
    .filter(column => column.type === 'date')
    .map(column => {
      const dates = table.rows.map(row => parseDate(row[column.name])).filter(Boolean).sort();
      return {
        column: column.name,
        minimum: dates[0],
        maximum: dates.at(-1)
      };
    });
  return {
    filename: path.basename(filePath),
    format: input.extension.slice(1),
    sizeBytes: input.sizeBytes,
    fingerprint: crypto.createHash('sha256').update(fs.readFileSync(filePath)).digest('hex'),
    rowCount: profile.rowCount,
    columnCount: profile.columnCount,
    columns: profile.columns,
    dateRanges
  };
}
