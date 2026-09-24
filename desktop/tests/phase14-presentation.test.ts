import assert from "node:assert/strict";
import test from "node:test";
import type { SessionSnapshot } from "../src/shared/ipc";
import { humanAction, humanError, presentAnswer, readableTitle, safePlainText, sessionTitle } from "../src/renderer/presentation";

test("Session title uses the first real user question instead of a structured assistant summary", () => {
  const snapshot: SessionSnapshot = {
    threadId: "thread_hidden",
    traceIds: ["trace_hidden"],
    events: [],
    messages: [
      { role: "user", content: "华东区销售分析？" },
      { role: "assistant", content: "分析完成：{\"metric\":\"销售额\",\"value\":1580}" },
    ],
  };
  assert.equal(sessionTitle(snapshot), "华东区销售分析");
  assert.equal(readableTitle('{"metric":"销售额"}'), "未命名分析");
  assert.equal(sessionTitle({ ...snapshot, messages: [] }), "未命名分析");
});

test("structured answers become labeled values without inventing metrics", () => {
  assert.deepEqual(presentAnswer('分析完成：{"metric":"销售额","value":1580}'), {
    kind: "table",
    rows: [["指标", "销售额"], ["结果", "1580"]],
  });
  assert.deepEqual(presentAnswer('分析完成：{"metric":"销售额","operation":"sum","value":1580,"validCount":5}'), {
    kind: "table",
    rows: [["指标", "销售额"], ["计算方式", "求和"], ["结果", "1580"], ["有效记录数", "5"]],
  });
  assert.deepEqual(presentAnswer("销售情况较好。"), { kind: "text", text: "销售情况较好。" });
  assert.deepEqual(presentAnswer('{"unrecognized":{"secret":"value"}}'), { kind: "unsupported" });
});

test("presentation hides internal identifiers and secrets from ordinary text", () => {
  assert.equal(safePlainText("api_key: sk-example123456789"), null);
  assert.equal(presentAnswer("本次使用 thread_abc123 完成分析。").kind, "text");
  assert.doesNotMatch(JSON.stringify(presentAnswer("本次使用 thread_abc123 完成分析。")), /thread_abc123/);
  assert.doesNotMatch(JSON.stringify(presentAnswer("sequence: 42、tool args 已记录。")), /sequence|tool args/i);
  assert.equal(humanAction("mcp_write"), "向外部服务写入数据");
  assert.match(humanError("session_not_found", "thread_abc123"), /刷新/);
});
