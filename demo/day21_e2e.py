"""Day21.3 end-to-end composition without adding a new execution core."""
from __future__ import annotations
import copy
import json
from pathlib import Path
from typing import Any
from agent import AgentLoop, ConversationRunner
from datasets import DatasetRegistry
from hitl import PersistentApprovalManager
from mcp_adapter import MCPToolAdapter, MockMCPClient, MockMCPServer
from memory import ThreeLayerMemory
from session import SQLiteApprovalRepository, SQLiteSessionStore
from skill_runtime import SkillRegistry, SkillRuntime
from subagents import data_check_delegate_definition
from tools import ToolRegistry, build_default_registry
from workflow import AnalysisNode, CalcNode, ChatNode, MemoryRecallNode, RuleRouter, Workflow

class QueueModel:
    def __init__(self, decisions:list[Any]): self.decisions=decisions; self.calls=[]
    def complete(self, *, messages, tools):
        self.calls.append({"messages":messages,"tools":tools}); item=self.decisions.pop(0); return item(messages) if callable(item) else item

class Day21Demo:
    def __init__(self, root:str|Path, *, approval_key:bytes) -> None:
        self.root=Path(root); self.root.mkdir(parents=True,exist_ok=True); self.database=self.root/"sessions.sqlite3"; self.memory_db=self.root/"memory.sqlite3"; self.approval_key=approval_key

    def happy_path(self, dataset_path:str|Path, *, thread_id:str) -> dict[str,Any]:
        store=SQLiteSessionStore(self.database)
        if store.get_session(thread_id) is None: store.create_session(thread_id)
        datasets=DatasetRegistry(self.root/f"datasets-{thread_id}"); dataset_id=datasets.register(dataset_path)["datasetId"]
        memory=ThreeLayerMemory.from_sqlite(self.memory_db); memory.remember(scope_id="demo-user",requests={"type":"kv","key":"preferred_metric","value":"销售额"})
        contract=json.dumps({"status":"completed","summary":"数据诊断完成。","findings":[{"title":"结构可用","severity":"low","detail":"检查完成。","evidenceCallIds":["diag-1"]}],"recommendations":["继续分析"],"limitations":[]},ensure_ascii=False)
        main=QueueModel([{"type":"tool_call","id":"diag-1","name":"inspect_data","arguments":{"datasetId":dataset_id}},{"type":"final_answer","content":contract},{"type":"tool_call","id":"delegate-1","name":"delegate_data_check","arguments":{"task":"检查字段","datasetId":dataset_id}},{"type":"final_answer","content":"主 Agent 已整合子任务结果。"}])
        sub=QueueModel([{"type":"tool_call","id":"sub-1","name":"inspect_data","arguments":{"datasetId":dataset_id}},{"type":"final_answer","content":"检查完成"}])
        registry=build_default_registry(); registry.register(data_check_delegate_definition(sub,registry))
        runner=ConversationRunner(AgentLoop(main,registry,memory=memory),dataset_registry=datasets,conversation_id=thread_id); runner.set_active_datasets([dataset_id])
        skill=SkillRuntime(runner,SkillRegistry()); workflow=Workflow(router=RuleRouter(),nodes={"chat":ChatNode(),"analysis":AnalysisNode(runner,skill_runtime=skill),"calc":CalcNode(),"memory_recall":MemoryRecallNode(memory)})
        first=workflow.invoke({"query":"请做数据诊断，为什么最近销量下降","active_dataset_ids":[dataset_id],"memory_scope":"demo-user"}); self._persist(store,runner,first,"turn_1")
        second=workflow.invoke({"query":"再委派检查数据并给出结论","active_dataset_ids":[dataset_id],"memory_scope":"demo-user"}); self._persist(store,runner,second,"turn_2")
        memory.close(); events=store.get_events(thread_id); messages=store.get_messages(thread_id); store.close()
        return {"thread_id":thread_id,"trace_id":second["data"]["observability"]["trace_id"],"first_trace_id":first["data"]["observability"]["trace_id"],"route":first["route"],"skill":first["data"]["skill_invocation"]["skill_name"],"final_answer":second["response"],"first_answer":first["response"],"subagent_completed":any(e.get("event_type")=="subagent_completed" for e in events),"messages":messages,"events":events,"context_reports":second["data"]["agent_state"]["context_reports"]}

    def start_hitl(self, *, thread_id:str, text:str="external-secret") -> dict[str,Any]:
        store=SQLiteSessionStore(self.database)
        if store.get_session(thread_id) is None: store.create_session(thread_id)
        manager=PersistentApprovalManager(SQLiteApprovalRepository(store,self.approval_key),thread_id=thread_id); registry=ToolRegistry(approval_manager=manager); server=MockMCPServer(); MCPToolAdapter(MockMCPClient(server),server_id="mock",allowed_tools={"echo"},tool_policies={"echo":"mcp_write"}).register_into(registry)
        model=QueueModel([{"type":"tool_call","id":"write-1","name":"mcp_mock__echo","arguments":{"text":text}}]); state=AgentLoop(model,registry).run("执行外部写操作",conversation_id=thread_id,turn_id="turn_1")
        for message in state.messages:
            if message.get("role") in {"user","assistant","tool"}:
                persisted=copy.deepcopy(message)
                if persisted.get("role")=="assistant" and persisted.get("tool_calls"):
                    for call in persisted["tool_calls"]:
                        function=call.get("function",{})
                        if function.get("name")=="mcp_mock__echo": function["arguments"]="<sealed-pending-action>"
                store.append_message(thread_id,{**persisted,"turn_id":"turn_1"},trace_id=state.trace_id)
        result={"thread_id":thread_id,"trace_id":state.trace_id,"pending":state.pending_approval}; store.close(); return result

    def resume_hitl(self, *, thread_id:str, approval_id:str, action_hash:str, decision:str) -> dict[str,Any]:
        store=SQLiteSessionStore(self.database); manager=PersistentApprovalManager(SQLiteApprovalRepository(store,self.approval_key),thread_id=thread_id); registry=ToolRegistry(approval_manager=manager); server=MockMCPServer(); MCPToolAdapter(MockMCPClient(server),server_id="mock",allowed_tools={"echo"},tool_policies={"echo":"mcp_write"}).register_into(registry)
        result=registry.resolve_approval(approval_id=approval_id,action_hash=action_hash,decision=decision); events=store.get_events(thread_id); store.close(); return {"thread_id":thread_id,"trace_id":result.trace_events[-1]["trace_id"] if result.trace_events else None,"result":result.to_dict(),"remote_calls":server.calls,"events":events}

    @staticmethod
    def _persist(store,runner,result,turn_id):
        for message in runner.state.turns[-1].messages: store.append_message(runner.state.conversation_id,{**message,"turn_id":turn_id},trace_id=result["data"]["observability"]["trace_id"])
        for event in result["data"]["observability"]["events"]: store.append_event(runner.state.conversation_id,event,trace_id=event.get("trace_id"))
