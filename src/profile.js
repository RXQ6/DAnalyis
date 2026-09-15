const NUMBER_PATTERN = /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/;
const DATE_PATTERN = /^(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})(?:日)?(?:[ T].*)?$/;

export function parseNumber(value) {
  const normalized = String(value).trim().replace(/,/g, '');
  return NUMBER_PATTERN.test(normalized) ? Number(normalized) : null;
}

export function parseDate(value) {
  const match = String(value).trim().match(DATE_PATTERN);
  if (!match) return null;
  const year = Number(match[1]), month = Number(match[2]), day = Number(match[3]);
  const date = new Date(Date.UTC(year, month - 1, day));
  if (date.getUTCFullYear() !== year || date.getUTCMonth() !== month - 1 || date.getUTCDate() !== day) return null;
  return date.toISOString().slice(0, 10);
}

export function profileTable(table) {
  const columns = table.headers.map(name => {
    const values = table.rows.map(row => row[name]);
    const nonEmpty = values.filter(value => value !== '');
    const numeric = nonEmpty.filter(value => parseNumber(value) !== null).length;
    const dates = nonEmpty.filter(value => parseDate(value) !== null).length;
    let type = 'text';
    if (nonEmpty.length && numeric === nonEmpty.length) type = 'number';
    else if (nonEmpty.length && dates === nonEmpty.length) type = 'date';
    else if (numeric > 0 && numeric < nonEmpty.length) type = 'mixed';
    else if (dates > 0 && dates < nonEmpty.length) type = 'mixed_date';
    return {
      name, type, missing: values.length - nonEmpty.length, nonEmpty: nonEmpty.length,
      invalidNumeric: type === 'mixed' ? nonEmpty.length - numeric : 0,
      invalidDate: type === 'mixed_date' ? nonEmpty.length - dates : 0,
      distinct: new Set(nonEmpty).size
    };
  });
  return { rowCount: table.rows.length, columnCount: table.headers.length, columns };
}
