import { AgentError } from './errors.js';

const OP_PATTERNS = [
  ['average', /平均|均值|average|mean/i], ['sum', /总和|合计|总计|求和|sum|total/i],
  ['minimum', /最小|最低|min(?:imum)?/i], ['maximum', /最大|最高|max(?:imum)?/i],
  ['count', /数量|个数|计数|count/i]
];

function referencedColumns(question, headers) {
  const lower = question.toLocaleLowerCase();
  return headers.filter(header => lower.includes(header.toLocaleLowerCase())).sort((a, b) => b.length - a.length);
}

function columnAfterGroupingWord(question, headers) {
  const tail = question.match(/(?:按|by)\s*(.*)/i)?.[1]?.toLocaleLowerCase() || '';
  return headers.find(header => tail.startsWith(header.toLocaleLowerCase())) || null;
}

function missingCandidate(question, headers) {
  const patterns = [
    /(?:计算|统计|分析|排序|识别|找出)\s*[“"']?([\p{L}\p{N}_%-]+)[”"']?/u,
    /(?:按|by)\s*[“"']?([\p{L}\p{N}_%-]+)[”"']?/iu
  ];
  const stop = new Set(['平均值', '总和', '趋势', '异常值', '数据', '这个', 'the']);
  for (const pattern of patterns) {
    const value = question.match(pattern)?.[1];
    if (value && !stop.has(value) && !headers.some(h => h.toLocaleLowerCase() === value.toLocaleLowerCase())) return value;
  }
  return null;
}

export function selectTool(question, profile) {
  const headers = profile.columns.map(column => column.name);
  const refs = referencedColumns(question, headers);
  const operation = OP_PATTERNS.find(([, pattern]) => pattern.test(question))?.[0] || null;
  let intent;
  if (/趋势|随时间|over\s+time|trend/i.test(question)) intent = 'trend';
  else if (/异常|离群|outlier|anomal/i.test(question)) intent = 'anomaly';
  else if (/top\s*\d*|前\s*\d+|排名|排序|找出.*最高/i.test(question)) intent = 'top';
  else if (/(?:按|by)\s*.+?(?:分组|统计|对比|group)/i.test(question)) intent = 'group';
  else if (operation) intent = 'statistics';
  else return { status: 'needs_input', message: '请明确分析目标（基础统计、分组对比、趋势或异常识别）以及相关字段。' };

  if (!refs.length) {
    const candidate = missingCandidate(question, headers);
    if (candidate) throw new AgentError('missing_field', `字段“${candidate}”不存在。`, { availableFields: headers });
    return { status: 'needs_input', message: `请指定要分析的字段。可用字段：${headers.join('、')}。` };
  }

  if (intent === 'group') {
    const groupBy = columnAfterGroupingWord(question, headers) || refs[0];
    const metric = refs.find(ref => ref !== groupBy) || null;
    if (!metric) return { status: 'needs_input', message: '分组对比还需要指定一个数值指标字段。' };
    return { status: 'selected', tool: 'group_compare', args: { groupBy, metric, operation: operation || 'sum' } };
  }
  if (intent === 'trend') {
    const explicitDate = refs.find(ref => ['date', 'mixed_date'].includes(profile.columns.find(c => c.name === ref)?.type));
    const dateColumns = profile.columns.filter(c => ['date', 'mixed_date'].includes(c.type));
    const dateField = explicitDate || (dateColumns.length === 1 ? dateColumns[0].name : null);
    const metric = refs.find(ref => ref !== dateField && profile.columns.find(c => c.name === ref)?.type !== 'date') || null;
    if (!dateField || !metric) return { status: 'needs_input', message: '趋势分析需要指定日期字段和数值指标字段。' };
    return { status: 'selected', tool: 'trend', args: { dateField, metric, operation: operation || 'sum' } };
  }
  const numericRef = refs.find(ref => ['number', 'mixed'].includes(profile.columns.find(c => c.name === ref)?.type));
  const metric = intent === 'statistics' && operation === 'count' ? refs[0] : (numericRef || refs[0]);
  if (intent === 'anomaly') return { status: 'selected', tool: 'anomaly', args: { metric } };
  if (intent === 'top') {
    if (!numericRef) {
      throw new AgentError('missing_field', '未找到问题中要求用于排序的数值字段。', { availableFields: headers });
    }
    const count = Number(question.match(/(?:top|前)\s*(\d+)/i)?.[1] || 5);
    const label = refs.find(ref => ref !== metric && profile.columns.find(c => c.name === ref)?.type === 'text') || profile.columns.find(c => c.type === 'text')?.name || null;
    return { status: 'selected', tool: 'top_n', args: { metric, label, count } };
  }
  return { status: 'selected', tool: 'statistics', args: { metric, operation } };
}
