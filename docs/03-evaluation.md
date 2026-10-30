# 03 评估报告

## 1. 测试与材料的对应关系

- 可执行测试:`tests/`(76 个用例,全部离线、确定性,`python -m pytest tests/ -q` 一键运行);
- 运行记录:`examples/case1..case6/`(每组含 `input.json` 输入、`output.json` 实际输出、`trace.md` 人类可读 Trace);
- 下表"实际结果"列均为本仓库提交时真实运行结果(引擎 = mock,边界见第 4 节)。

## 2. 验收点逐项结果

| 验收点 | 示例材料 | 相关测试 | 预期 | 实际结果 |
|--------|----------|----------|------|----------|
| 明确答案 | `case1_clear_answer/` | `test_agent_loop.py::test_case1_clear_answer` | 回答餐补 300 元并引用 D04 原文 | ✅ answered,3 步(search→read D04→finish),引用逐字 |
| 文档冲突 | `case2_doc_conflict/` | `test_conflict.py`(5 个用例) | 列出 D01 30 天 / D02 15 天冲突与双方原文,不擅自作答,请求确认 | ✅ needs_confirmation,4 步,冲突双方 quote 逐字可核验,gaps 注明"未注明适用范围与优先级" |
| 只命中 D01 且无冲突 → 依 D01 作答 | (测试内) | `test_conflict.py::test_single_document_no_false_conflict` | 住宿费标准问题依 D01 回答 500 元 | ✅ answered,冲突为空(注:该问题为复合主题,实际走了 D07→D01 的补充读取路径) |
| 资料外问题 | `case3_out_of_scope/` | `test_agent_loop.py::test_case3_out_of_scope_with_gaps` | 改写重试后仍无命中 → out_of_scope + 缺口,零引用 | ✅ out_of_scope,3 步,两次查询不同(真改写),citations=[] |
| 改写后的相似问题 | `case4_paraphrase/` | `test_agent_loop.py::test_case4_paraphrase_uses_rewrite` | "工作满一年能休几天假?"经同义词改写命中 D03 年假条款 | ✅ answered,首轮「年假」0 命中 → 改写「年假 年休假 带薪年假」命中,4 步 |
| 上下文追问 | `case5_context_followup/` | `test_agent_loop.py::test_case5_context_followup` | "那上下班路上的呢?"结合上一轮主题(补贴)答交通补贴 200 元 | ✅ answered,3 步,检索词含历史主题,引用 D04 交通补贴条款 |
| 工具失败 | `case6_tool_failure/` | `test_conflict.py::test_conflict_scenario_read_failure_still_flags_conflict`、`test_tools.py` 注入用例 | 读取 D01 故障 → 调整动作不重试同一失败 → 仍给出可核验结论 | ✅ 改读 D02,以 D01 检索片段(evidence=snippet)与 D02 原文(evidence=read)列冲突,4 步 |
| 步数上限 → 明确未完成 | (测试内) | `test_agent_loop.py::test_step_limit_*` | 达到上限返回 unfinished + limit_reached + 明确 gaps | ✅ max_steps=2 时 2 步即止,answer 为空、无引用、gaps 写明"已达最大步数上限,任务未完成" |
| 引用逐字可核验 | 全部 case | `test_citation_integrity.py` | 所有 citations/conflicts 的 quote 逐字存在于被引文档,版本一致 | ✅ 实时运行与 examples/ 已提交 output.json 双重校验通过 |
| 替换文档内容 → 答案与动作改变 | (测试内) | `test_conflict.py::test_content_swap_*` | 改 30→45 冲突值跟着变;改一致不再报冲突;删数值不误判 | ✅ 三个替换用例全部通过 |
| 非法引用防幻觉 | (测试内) | `test_citation_integrity.py::test_dropped_citation_reported` | 模型给的假引用被剔除并记录,不透传 | ✅ 2 条非法引用被剔除,notes 如实记录 |

**测试执行结果**:76 passed(提交时版本,Python 3.11 / Windows;约 2 秒,无网络依赖)。

## 3. 覆盖"至少两条执行路径"的运行记录

模型根据不同工具结果调整动作的路径至少包括:

1. **冲突路径**(search→read D01→read D02→finish):`examples/case2_doc_conflict/trace.md`;
2. **改写路径**(search→search(改写)→read→finish):`examples/case4_paraphrase/trace.md`;
3. **放弃路径**(search→search(改写)→finish out_of_scope):`examples/case3_out_of_scope/trace.md`;
4. **故障恢复路径**(search→read D01(失败)→read D02→finish):`examples/case6_tool_failure/trace.md`。

每个 Trace 均含:步骤号、决策依据、工具参数、观察摘要与数据、**后续动作**(该步观察引发的下一个动作,由循环自动回填到每一步,trace.md 与 output.json 均有 `next_action` 字段)。

## 4. 已知限制与边界(如实说明)

1. **提交材料的引擎边界**:本仓库提交的 `examples/` 由 **Mock 决策策略**生成(编写环境无模型凭据)。Mock 只证明 ReAct 流程、工具链路与交付格式正确,**不证明真实模型决策效果**。配置 `AGENT_LLM_*` 后执行 `python -m src.kb_agent.cli demo` 即可用真实模型重新生成同等材料(命令与文件格式不变)。
2. **检索能力边界**:字符 bigram 检索无语义泛化,依赖 `data/rules.json` 的别名/同义词做查询扩展;新口语说法若不在规则表中可能首查不中(仍会走改写路径,但改写词表也是有限的)。换更大文档库建议换 BM25 或向量检索。
3. **Mock 冲突判定的启发式**:依赖"标题含问题主题词 + 单位相同"两条规则区分"真冲突"与"不同方面";极端措辞下可能漏判(把冲突当单答案)或保守处理,不会反向编造。
4. **真实模型路径未经真实服务验证**:编写环境无可用模型凭据,`LLMReActModel` 的网络路径由单测用桩/不可达地址验证(错误处理、JSON 解析容错、引擎切换),未对真实 LLM 做端到端调优;若提示词对特定模型需微调,调整点集中在 `src/kb_agent/real_model.py::SYSTEM_PROMPT`。
5. **单文档复合问题**:同一篇文档内的多方面复合问题(如"住宿费和交通费标准?")只会引用其中一条条款作答。
6. **read_all 注入模式**下所有读取都失败,Mock 会回退到片段证据或如实报告缺口,但不支持"等待重试"类策略(与真实生产场景的退避策略不同)。

## 5. 如何复现

```bash
pip install -r requirements.txt
python -m pytest tests/ -q                          # 76 个测试
python -m src.kb_agent.cli demo                     # 重新生成 examples/(默认引擎)
python examples/run_examples.py --engine mock       # 强制 Mock 重新生成
```

单条命令验证冲突场景:

```bash
python -m src.kb_agent.cli ask "报销申请的期限是多久?"
```
