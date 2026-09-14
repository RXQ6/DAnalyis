function number(value) {
  return new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 12 }).format(value);
}

export function explain(tool, result) {
  if (tool === 'statistics') return `${result.metric}的${operationName(result.operation)}为 ${number(result.value)}（有效记录 ${result.validCount} 条）。`;
  if (tool === 'group_compare') {
    const leader = result.groups[0];
    return `共比较 ${result.groups.length} 个${result.groupBy}分组；${leader.group}的${result.metric}${operationName(result.operation)}最高，为 ${number(leader.value)}。`;
  }
  if (tool === 'trend') {
    const first = result.points[0], last = result.points.at(-1);
    const direction = last.value > first.value ? '上升' : last.value < first.value ? '下降' : '持平';
    return `趋势覆盖 ${result.points.length} 个日期；${first.date} 至 ${last.date}，${result.metric}从 ${number(first.value)} 到 ${number(last.value)}，首尾相比${direction}。`;
  }
  if (tool === 'anomaly') return `使用 1.5×IQR 规则识别出 ${result.anomalyCount} 个${result.metric}异常值。`;
  if (tool === 'top_n') return `已按${result.metric}从高到低返回前 ${result.count} 条记录。`;
  return '分析已完成。';
}

function operationName(operation) {
  return ({ sum: '总和', average: '平均值', count: '计数', minimum: '最小值', maximum: '最大值' })[operation] || operation;
}
