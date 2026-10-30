# examples/ 验证材料索引

由 `python -m src.kb_agent.cli demo`(engine=mock, model=mock-policy-v1)生成;
复现命令见仓库 README。以下 6 组输入/输出/Trace 覆盖全部 6 个验收点。

| 用例 | 验收点 | 问题 | 任务状态 | 步数 | 材料 |
|------|--------|------|----------|------|------|
| case1_clear_answer | 明确答案 | 每个月吃饭有补贴吗?能补多少? | `answered` | 3 | [case1_clear_answer/](case1_clear_answer/) |
| case2_doc_conflict | 文档冲突 | 报销申请的期限是多久? | `needs_confirmation` | 4 | [case2_doc_conflict/](case2_doc_conflict/) |
| case3_out_of_scope | 资料外问题 | 公司附近有什么好吃的餐厅推荐? | `out_of_scope` | 3 | [case3_out_of_scope/](case3_out_of_scope/) |
| case4_paraphrase | 改写后的相似问题 | 工作满一年能休几天假? | `answered` | 4 | [case4_paraphrase/](case4_paraphrase/) |
| case5_context_followup | 上下文追问 | 那上下班路上的呢? | `answered` | 3 | [case5_context_followup/](case5_context_followup/) |
| case6_tool_failure | 工具失败 | 报销申请的期限是多久? | `needs_confirmation` | 4 | [case6_tool_failure/](case6_tool_failure/) |

> 说明:若引擎为 mock,以下 Trace 仅验证流程与工具链路,不证明真实模型决策效果;
配置 AGENT_LLM_* 后重跑 `demo` 即可用真实模型生成同等材料。
