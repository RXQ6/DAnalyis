# P1 Formal Evaluation

- Passed: 20/20 (100.0%)
- Average response: 0.643s
- Maximum response: 1.238s
- Average cost: CNY 0.000
- Maximum cost: CNY 0.000

## Case Mapping

| Case | Category | Input / fixture | Capability | Test mapping | Expected | Actual | Result | Time | Cost |
| --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: |
| P1-01 | chart | tests/fixtures/sales.csv | 趋势 ToolResult → line chart | tests/eval_chart.py CHART-01 | 生成 line SVG，来源为 trend_analysis | {"success":true,"chartType":"line"} | PASS | 0.315s | CNY 0.000 |
| P1-02 | chart | tests/fixtures/sales.csv | 类别占比 → bar chart | tests/test_chart_tool.py + tests/eval_p1.py | 柱高表示占比，总计为 1 或 100 | {"success":true,"values":[{"x":"华南","y":0.759493670886076},{"x":"华东","y":0.24050632911392406}],"valueTotal":1.0} | PASS | 0.349s | CNY 0.000 |
| P1-03 | chart | generated scatter.csv | scatter chart | tests/test_chart_tool.py + tests/eval_p1.py | 成功生成 scatter chart | {"success":true,"chartType":"scatter"} | PASS | 0.319s | CNY 0.000 |
| P1-04 | chart | tests/fixtures/sales.csv | 显式 line chart | tests/eval_chart.py CHART-01/04 | 按用户指定生成 line chart | {"success":true,"chartType":"line"} | PASS | 0.345s | CNY 0.000 |
| P1-05 | chart | tests/fixtures/sales.csv | 不支持的单值图表来源 | tests/eval_chart.py CHART-05 | 拒绝生成并返回 unsupported_chart_source | {"success":false,"errorCode":"unsupported_chart_source"} | PASS | 0.339s | CNY 0.000 |
| P1-06 | multifile | generated same-left.csv + same-right.csv | CSV 一对一安全合并 | tests/test_multifile_tools.py + tests/eval_p1.py | preflight 安全且生成派生数据集 | {"preflightOk":true,"safeToExecute":true,"mergeOk":true,"rowCount":2} | PASS | 1.106s | CNY 0.000 |
| P1-07 | multifile | generated left.xlsx + right.xlsx | XLSX 一对一安全合并 | tests/eval_p1.py | preflight 安全且生成派生数据集 | {"preflightOk":true,"safeToExecute":true,"mergeOk":true,"rowCount":3} | PASS | 1.238s | CNY 0.000 |
| P1-08 | multifile | generated 客户/客户ID CSV | join 字段映射校验 | tests/eval_p1.py | 明确返回 missing_join_field，不执行合并 | {"ok":false,"errorCode":"missing_join_field"} | PASS | 0.791s | CNY 0.000 |
| P1-09 | multifile | generated sales-2025.csv + sales-2026.csv | 跨文件同比计算 | tests/test_multifile_tools.py + tests/eval_p1.py | 确定性返回同比变化率 | {"ok":true,"groups":[{"group":"sales-2025.csv","datasetId":"ds_7da2d34f0e35","value":50,"validCount":2},{"group":"sales-2026.csv","datasetId":"ds_663193a8a8af","value":100,"validCount":2}],"yearOverYearRate":1.0} | PASS | 1.089s | CNY 0.000 |
| P1-10 | multifile | generated category-a.csv + category-b.csv | 跨文件分组对比 | tests/test_multifile_tools.py + tests/eval_p1.py | 按类别比较两个文件的分组结果 | {"ok":true,"categories":[{"group":"B","values":[{"datasetId":"ds_d5bf20953018","filename":"category-a.csv","value":40,"validCount":1,"missing":false},{"datasetId":"ds_31736852677a","filename":"category-b.csv","value":70,"validCount":1,"missing":false}]},{"group":"A","values":[{"datasetId":"ds_d5bf20953018","filename":"category-a.csv","value":10,"validCount":1,"missing":false},{"datasetId":"ds_31736852677a","filename":"category-b.csv","value":30,"validCount":1,"missing":false}]}]} | PASS | 1.121s | CNY 0.000 |
| P1-11 | multifile | generated empty-p1.csv | 空文件注册校验 | tests/test_dataset_registry.py + tests/eval_p1.py | 拒绝空文件且不继续分析 | {"accepted":false,"errorCode":"empty_file"} | PASS | 0.294s | CNY 0.000 |
| P1-12 | multifile | generated structure-left/right.csv | 结构/关联字段校验 | tests/test_multifile_tools.py + tests/eval_p1.py | 拒绝不兼容合并，不产生结论 | {"ok":false,"errorCode":"missing_join_field"} | PASS | 0.754s | CNY 0.000 |
| P1-13 | conversation | generated history.csv + 2 turns | 历史 ToolResult recall | tests/test_conversation.py + tests/eval_p1.py | 回答华南 | {"answer":"华南"} | PASS | 0.602s | CNY 0.000 |
| P1-14 | conversation | generated history.csv + 2 turns | 历史对象与结果 recall | tests/eval_p1.py | 回答华东 | {"answer":"华东"} | PASS | 0.554s | CNY 0.000 |
| P1-15 | conversation | generated history.csv + 2 turns | filter 覆盖 | tests/eval_conversation.py CONV-01 + tests/eval_p1.py | 第二轮使用华南筛选 | {"filters":{"地区":"华南"}} | PASS | 0.768s | CNY 0.000 |
| P1-16 | conversation | generated history.csv + 2 turns | metric 覆盖 | tests/eval_conversation.py CONV-04 + tests/eval_p1.py | 第二轮改用利润 | {"metric":"利润"} | PASS | 0.692s | CNY 0.000 |
| P1-17 | conversation | generated old/new-history.csv | 活动数据集隔离 | tests/test_conversation.py + tests/eval_p1.py | 只使用新文件并得到 100 | {"value":100,"oldDatasetId":"ds_51e1e67550ed","currentDatasetId":"ds_40f3c2994914"} | PASS | 0.895s | CNY 0.000 |
| P1-18 | conversation | generated history.csv + 15 turns | 长历史 ToolResult recall | tests/test_conversation.py + tests/eval_p1.py | 仍回答华南 | {"answer":"华南","turns":15} | PASS | 0.543s | CNY 0.000 |
| P1-19 | conversation | generated history.csv + 2 turns | 当前问题覆盖旧 metric | tests/eval_conversation.py CONV-04 + tests/eval_p1.py | 按当前请求改用利润 | {"metric":"利润","answer":"已识别冲突并改看利润"} | PASS | 0.616s | CNY 0.000 |
| P1-20 | conversation | no dataset/history | needs_user_input | tests/eval_conversation.py CONV-08 + tests/eval_p1.py | stop_reason=needs_user_input | {"stopReason":"needs_user_input","answer":"请重新提供文件和分析目标。"} | PASS | 0.136s | CNY 0.000 |
