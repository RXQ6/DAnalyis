# AGENTS.md

## 项目目标

本项目实现一个数据分析 Agent：用户上传单个 CSV / XLSX 文件并提出自然语言问题，Agent 选择受控工具完成真实数据分析并输出有依据的结论。

## 当前基线

- P0 功能与正式评测已经达到 100% 通过率。
- 当前产品范围以 `docs/PRD-v1.1.md` 为准。
- 引入 Day8 Agent Loop 时，不得改变现有 P0 / P1 功能边界。

## 修改原则

- 优先采用满足需求的最小改动，不推倒重构现有项目结构。
- 不允许为了通过测试修改、删除或放宽原有评测标准和预期结果。
- LLM 只负责理解问题、选择工具、决定是否继续分析以及解释工具结果。
- 数据读取、统计和其他真实计算必须由确定性程序工具完成。
- 不允许模型动态生成并执行任意 Python 代码。
- 新工具必须通过 Tool Registry 注册，不得绕过 Registry 直接由 Agent Loop 调用 Tool Handler。
- 每次主要修改后必须重新运行 P0 评测，并确认没有回归后再交付。
- 不得提前加入 RAG、Memory、Multi-Agent 或 Day9 安全层需求。

## 验证要求

- 基础测试：`npm test`
- P0 评测：`python tests/eval_agent.py`
- 评测失败时修复实现或客观的测试基础设施缺陷；不得修改评测目标来掩盖产品问题。

## 进度记录规则

- 每个阶段性开发任务完成并通过相关测试/回归后，自动根据当前真实代码和测试结果更新 `processed.md`；不要记录 Agent 运行时 Todo，不要编造未完成内容，不要修改业务代码或评测标准来配合进度记录。

## Memory 长期规则

- Memory 只提供上下文，不控制 Agent Loop，也不替代 Todo / Tool Registry。
- 当前文件数据和 ToolResult 优先于历史 Memory。
- 不把完整 CSV / XLSX、全部对话、Todo、工具 Observation 自动写入长期 Memory。
- 第一版长期 Memory 使用显式 remember。
- Memory 改动尽量保持最小侵入。
- Memory 改动后必须运行 Memory 专项测试、P0 和 robustness 回归。
- 阶段完成并验证通过后更新 `processed.md`。
- 只有长期项目规则变化时才修改 `AGENTS.md`。
