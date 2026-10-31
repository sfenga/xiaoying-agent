# 03 评估报告

## 1. 测试与材料的对应关系

- 可执行测试:`tests/`(113 个用例,全部离线、确定性,`python -m pytest tests/ -q` 一键运行;含检索召回评测集与真实模型协议端到端集成测试);
- 运行记录:`examples/case1..case7/`(每组含 `input.json` 输入、`output.json` 实际输出、`trace.md` 人类可读 Trace);
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
| 文档冲突(确认后收敛) | `case7_conflict_resolved/` | `test_agent_loop.py::test_conflict_resolved_by_explicit_doc`、`test_golden_traces.py` | 用户确认"按 D01"后,直读指定文档依其作答 30 天 | ✅ answered,2 步(read→finish),引用 D01 逐字 |
| 步数上限 → 明确未完成 | (测试内) | `test_agent_loop.py::test_step_limit_*` | 达到上限返回 unfinished + limit_reached + 明确 gaps | ✅ max_steps=2 时 2 步即止,answer 为空、无引用、gaps 写明"已达最大步数上限,任务未完成" |
| 检索召回质量(口语/改写/负例) | (测试内) | `test_retrieval_quality.py`(17 条查询:15 正例+2 负例) | 15 条正例召回指定文档,2 条资料外负例零命中 | ✅ 17/17 通过(评测驱动补齐「报到→入职」「打卡→补卡」「夏天→高温」别名) |
| 真实模型协议路径端到端 | (测试内) | `test_real_model_integration.py`(本地桩 OpenAI 兼容服务器) | HTTP 请求格式/鉴权、动作解析、finish 错误反馈与自我修正、编造引用剔除 | ✅ 3 个集成用例通过(无真实 key 也能验证协议全链路) |
| 引用逐字可核验 | 全部 case | `test_citation_integrity.py` | 所有 citations/conflicts 的 quote 逐字存在于被引文档,版本一致 | ✅ 实时运行与 examples/ 已提交 output.json 双重校验通过 |
| 替换文档内容 → 答案与动作改变 | (测试内) | `test_conflict.py::test_content_swap_*` | 改 30→45 冲突值跟着变;改一致不再报冲突;删数值不误判 | ✅ 三个替换用例全部通过 |
| 非法引用防幻觉 | (测试内) | `test_citation_integrity.py::test_dropped_citation_reported` | 模型给的假引用被剔除并记录,不透传 | ✅ 2 条非法引用被剔除,notes 如实记录 |

**测试执行结果**:113 passed(提交时版本,Python 3.11 / Windows;约 4 秒,无网络依赖;CI 另覆盖 py3.9–3.12 × Linux/Windows)。

## 3. 覆盖"至少两条执行路径"的运行记录

模型根据不同工具结果调整动作的路径至少包括:

1. **冲突路径**(search→read D01→read D02→finish):`examples/case2_doc_conflict/trace.md`;
2. **改写路径**(search→search(改写)→read→finish):`examples/case4_paraphrase/trace.md`;
3. **放弃路径**(search→search(改写)→finish out_of_scope):`examples/case3_out_of_scope/trace.md`;
4. **故障恢复路径**(search→read D01(失败)→read D02→finish):`examples/case6_tool_failure/trace.md`;
5. **确认收敛路径**(冲突 finish 后,用户指定文档 → read→finish):`examples/case7_conflict_resolved/trace.md`。

每个 Trace 均含:步骤号、决策依据、工具参数、观察摘要与数据、**后续动作**(该步观察引发的下一个动作,由循环自动回填到每一步,trace.md 与 output.json 均有 `next_action` 字段)。7 个用例的动作序列由 `tests/test_golden_traces.py` 固化为黄金轨迹,任何策略调整导致的路径变化都会被捕获。

## 4. 已知限制与边界

1. **提交材料的引擎边界**:本仓库提交的 `examples/` 由 **Mock 决策策略**生成(编写环境无模型凭据)。Mock 只证明 ReAct 流程、工具链路与交付格式正确,**不证明真实模型决策效果**。配置 `AGENT_LLM_*` 后执行 `python -m src.kb_agent.cli demo` 即可用真实模型重新生成同等材料(命令与文件格式不变)。
2. **检索能力边界**:字符 bigram 检索无语义泛化,依赖 `data/rules.json` 的别名/同义词做查询扩展;新口语说法若不在规则表中可能首查不中(仍会走改写路径,但改写词表也是有限的)。换更大文档库建议换 BM25 或向量检索。
3. **Mock 冲突判定的启发式**:依赖"标题含问题主题词 + 单位相同"两条规则区分"真冲突"与"不同方面";极端措辞下可能漏判(把冲突当单答案)或保守处理,不会反向编造。
4. **真实模型路径**:协议全链路已由本地桩 OpenAI 兼容服务器做端到端集成测试(`tests/test_real_model_integration.py`:请求路径与格式、动作解析、错误反馈自修正、编造引用剔除);尚未用真实商用模型跑通,提示词若需针对特定模型微调,调整点集中在 `src/kb_agent/real_model.py::SYSTEM_PROMPT`。
5. **检索条数配置影响冲突核查**:`--top-k` 调小时可见证据随之减少(如 top_k=1 时每个文档只返回最相关的一条片段,可能退化为单文档作答);默认值 4 足以覆盖冲突场景。
6. **Mock 的直读收敛为启发式**:「按 D01 算」的指定文档直读、新主题权重、条款相关性判断都是确定性规则,仅验证流程;Mock 无法区分同一文档内语义相近的条款(例如把"市内交通费报销审批线"当作"交通补贴标准"引用),这类语义级取舍依赖真实模型。
7. **单文档复合问题**:同一篇文档内的多方面复合问题(如"住宿费和交通费标准?")只会引用其中一条条款作答。
8. **read_all 注入模式**下所有读取都失败,Mock 会回退到片段证据或如实报告缺口,但不支持"等待重试"类策略(与真实生产场景的退避策略不同)。

## 5. 如何复现

```bash
pip install -r requirements.txt
python -m pytest tests/ -q                          # 113 个测试
python -m src.kb_agent.cli demo                     # 重新生成 examples/(默认引擎)
python examples/run_examples.py --engine mock       # 强制 Mock 重新生成
```

单条命令验证冲突场景:

```bash
python -m src.kb_agent.cli ask "报销申请的期限是多久?"
```
