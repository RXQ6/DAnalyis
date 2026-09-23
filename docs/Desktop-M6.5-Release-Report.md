# Desktop M6.5 Release Report

验收时间：2026-09-23 12:54 CST。版本：`0.1.0`（`desktop/package.json`）。
结论：**Release Gate PASS；Desktop M6 完成。** 本结论针对本机 Windows x64 构建和下列 required gates，不等同于已验证干净机器部署或可信代码签名。

## Required gates

| Gate | 结果 | 本次证据 |
| --- | --- | --- |
| TypeScript build | PASS | `cd desktop; npm.cmd run build`，退出码 0 |
| Desktop M1–M6 tests | PASS | `cd desktop; npm.cmd test`：27/27 单元/集成、原 Electron smoke、M6.3 E2E 7 步 |
| Electron E2E | PASS | 开发态 7/7；`npm.cmd run test:e2e:packaged` 打包资源态 7/7 |
| Windows unpacked packaged smoke | PASS | 从真实 unpacked exe 双启动；CSV 分析 1580、6 条 Runtime Events、completed、重启恢复原 Session；`desktop/release/m6.4-smoke-FDFl4S/{first,resume}.json` |
| NSIS installed smoke | PASS | NSIS 静默安装退出码 0；从安装目录 exe 双启动，CSV 分析 1580、6 条 Runtime Events、completed、重启恢复原 Session；`desktop/release/m6.5-installed-smoke-xR3Qia/{first,resume}.json` |
| Packaged Python sidecar | PASS | `npm.cmd run verify:packaged-sidecar`：真实 run_completed，8 条协议 JSONL，stderr 无协议帧 |
| Python 全量 | PASS | `python -m unittest discover -s tests -p 'test_*.py'`：261/261 |
| 根项目 Node | PASS | `npm.cmd test`：13/13 |
| P0 / P1 / Robustness | PASS | 15/15、20/20、25/25 |
| Day19 Eval Harness | PASS | `tests/run_day19_eval.py`：60/60 |
| Regression Gate | PASS | Day19 统一报告中 11/11；average/p95/max latency 分别为 0.238/0.642/0.769 秒，均在既有容差内 |
| Security violations | PASS | Day19 统一报告：0（60 个案例） |
| Contract failures | PASS | Day19 统一报告：0（40 个具备 contract 检查的案例） |

Day19 的完整数据位于 `tests/results/day19-unified-report.json`；未更改 baseline、阈值或评测预期。Python Runtime、Dataset、Session、Guardrail 和 HITL 的业务语义未改。

## Release artifacts

下列 build 时间为文件系统最后修改时间（CST），用作产物构建完成时间证据。

| 产物 | 路径 | 大小（bytes） | build 时间 | SHA256 |
| --- | --- | ---: | --- | --- |
| NSIS installer | `D:\DAnalyis\desktop\release\Data Analysis Agent Setup 0.1.0.exe` | 131,814,356 | 2026-09-23 12:14:18 CST | `DDDC7AC2051CA06A579FEC4CFAEFA459319554FCCD667086BF516D397A98325F` |
| Windows unpacked exe | `D:\DAnalyis\desktop\release\win-unpacked\Data Analysis Agent.exe` | 210,150,400 | 2026-09-23 12:13:10 CST | `42001F1496DCEAB3ADED5E0C3EA0E5E01AC554466C584B95AF1894BE94899D7C` |
| NSIS installed exe | `D:\DAnalyis\desktop\release\m6.5-installed\Data Analysis Agent.exe` | 210,150,400 | 2026-09-23 12:14:10 CST | `42001F1496DCEAB3ADED5E0C3EA0E5E01AC554466C584B95AF1894BE94899D7C` |

安装方式：使用当前 NSIS installer 执行 `/S /D=D:\DAnalyis\desktop\release\m6.5-installed`；安装退出码 0，目标目录包含 `Data Analysis Agent.exe`、`Uninstall Data Analysis Agent.exe`、`resources/app.asar` 与 `resources/python-runtime/python.exe`。安装后的 exe 哈希与 unpacked exe 一致。验收启动方式是通过 `node desktop/scripts/verify-packaged-smoke.cjs --executable <安装目录exe> --label m6.5-installed-smoke` 直接启动真实 exe 两次；未使用 dev 模式。

安装态第一次进程 PID 3568，`thread_0cdbfabcf2ad4973a2e0f647b653c331`、`trace_9c00d68335fe4004bbaa91e9f01302d2`，文件状态 `sales.csv · 5 rows · 4 columns`，run 为 completed；第二次进程 PID 63636，从同一标准 Electron userData `C:\Users\29486\AppData\Roaming\data-analysis-agent-desktop` 恢复同一 thread、4 条持久化消息、6 条 Trace，没有新 run。Renderer URL 位于安装目录的 `resources/app.asar`，sidecar 路径位于安装目录 `resources`，证明不是 unpacked/dev 路径。

## 本轮修复与剩余风险

- 为 M6.4 双启动 smoke 增加可执行文件路径参数，复用于安装态；修复一次测试结果目录标签校验误拒绝点号的问题。该失败发生在应用启动前；修复后 unpacked 与 installed smoke 均重跑 PASS。没有修改 Python Runtime、业务逻辑或评测门槛。
- 自动化只为原生文件选择框提供确定性的 CSV 返回路径；Renderer、Preload、Main IPC、Python DatasetRegistry、Runtime Events 和 SessionStore 均为真实链路。原生选择框的鼠标/键盘交互尚未自动验证。
- 本次在同一开发机的独立安装目录验证，不覆盖全新用户配置、干净机器依赖或安装包升级/卸载路径。
- installer 与 exe 的 Authenticode 状态均为 `NotSigned`；公开分发前仍需可信签名、许可清单与 Windows SmartScreen 验证。
- Day19 现有 20 个 P1 案例无完整 Trace，token 用量未暴露；报告保持 unavailable，未以 0 代替。
