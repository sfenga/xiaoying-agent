# 企业知识问答 Agent(小影校招 AI Agent 开发岗 · 考核项目)

> **提交信息**:选题为考核**「企业知识问答 Agent」**题 | GitHub:https://github.com/sfenga/xiaoying-agent(私有仓库,已授权指定评审账号后可读)| 最终 commit SHA:**以本仓库最新提交为准**(评审按提交材料中所填 SHA 检出即为完整交付)。

基于合成制度/FAQ 文档库的企业知识问答 Agent:**ReAct 决策循环**(模型选动作 → 执行工具 → 观察结果 → 模型调整下一步或结束)+ **文档检索/片段读取**两个工具,回答必须附**文档 ID、版本日期与逐字原文引用**;文档冲突时列冲突并请求确认,不擅自作答。

- 运行方式:**CLI**(单轮 ask / 多轮 chat / 批量 demo)
- 技术选型:**原生 Python 实现**(不用 Agent 框架),依赖仅 `requests`
- 模型:OpenAI 兼容真实模型(智谱 GLM / DeepSeek / OpenAI 等,配环境变量即用)+ **离线 Mock 决策策略**(无凭据时自动回退;仅验证流程,不证明真实模型决策效果)

## 1. 环境

- Python **3.9+**(开发验证环境:3.11,Windows)
- 无网络也可完整运行(Mock 路径 + 全部测试);配真实模型需外网

## 2. 安装

```bash
pip install -r requirements.txt
```

模型配置(可选):复制 `.env.example` 为 `.env`,填入任一 OpenAI 兼容服务:

```ini
AGENT_LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4   # 智谱示例;DeepSeek: https://api.deepseek.com/v1
AGENT_LLM_API_KEY=sk-xxx
AGENT_LLM_MODEL=glm-4-flash
```

未配置时自动使用 Mock 引擎,并打印边界警告。

## 3. 运行(可复制的评审入口)

```bash
# ① 冲突场景(考核参考实例):D01 写 30 天、D02 写 15 天 → 列冲突请求确认,不擅自作答
python -m src.kb_agent.cli ask "报销申请的期限是多久?"

# ② 明确答案
python -m src.kb_agent.cli ask "每个月吃饭有补贴吗?能补多少?"

# ③ 资料外问题(改写重试后如实说明缺口)
python -m src.kb_agent.cli ask "公司附近有什么好吃的餐厅推荐?"

# ④ 工具失败场景(注入读取故障,观察恢复路径)
python -m src.kb_agent.cli ask "报销申请的期限是多久?" --inject read_once

# ⑤ 多轮对话(演示上下文追问:先问餐补,再问「那上下班路上的呢?」)
python -m src.kb_agent.cli chat

# ⑥ 一键生成全部 6 组验证材料(input/output/trace,写入 examples/)
python -m src.kb_agent.cli demo

# ⑦ 全部测试(离线、约 2 秒)
python -m pytest tests/ -q        # 76 个用例

# ⑧ 查看当前配置 / 渲染某个 Trace
python -m src.kb_agent.cli doctor
python -m src.kb_agent.cli trace examples/case2_doc_conflict/output.json
```

`ask` 常用参数:`--engine mock|real|auto`、`--max-steps N`(默认 8,达到上限返回明确未完成状态)、`--inject read_once|search_once|read_all|none`、`--json`(纯 JSON 输出)、`--trace-out 前缀`(写出 .json/.md Trace)。

## 4. 评审指引(建议阅读顺序)

| 材料 | 内容 |
|------|------|
| [docs/01-requirements.md](docs/01-requirements.md) | 用户、目标、范围、6 个验收点的成功标准 |
| [docs/02-solution.md](docs/02-solution.md) | 架构、ReAct 协议、动态决策路径、冲突判定规则、技术取舍 |
| [docs/03-evaluation.md](docs/03-evaluation.md) | **验收点 × 测试 × 示例材料对照表**、实际结果、已知限制 |
| [docs/04-ai-usage.md](docs/04-ai-usage.md) | AI 辅助范围、个人贡献与验证清单 |
| [docs/05-retrospective.md](docs/05-retrospective.md) | 最难问题、学习收获、下一步 |
| [examples/](examples/) | 6 组输入/实际输出/Trace(README.md 有索引表) |
| [tests/](tests/) | 76 个可执行测试(含引用逐字校验、内容替换敏感性、步数上限、finish 校验自修正) |
| [data/](data/) | 合成文档库(D01/D02 为考核指定的冲突实例)与检索规则 |
| [docs/00-exam-brief.md](docs/00-exam-brief.md) | 考核题目原文备档 |

**核心验收点速览**:

| 验收点 | 看哪里 |
|--------|--------|
| 明确答案 | `examples/case1_clear_answer/`(D04 餐补 300 元,引用逐字) |
| 文档冲突 | `examples/case2_doc_conflict/`(30 天 vs 15 天,needs_confirmation + 请求确认) |
| 资料外问题 | `examples/case3_out_of_scope/`(两次改写查询,out_of_scope + 缺口,零引用) |
| 改写相似问题 | `examples/case4_paraphrase/`(口语问年假 → 改写命中 D03) |
| 上下文追问 | `examples/case5_context_followup/`(「那上下班路上的呢?」→ 交通补贴 200 元) |
| 工具失败 | `examples/case6_tool_failure/`(读取故障 → 改用片段证据恢复并识别冲突) |

**替换文档内容做审核**:评审可直接修改 `data/documents.json`(如把 D01 的"30 天"改为"45 天")后重跑上面的命令,答案与动作会随之改变;`tests/test_conflict.py::test_content_swap_*` 自动化了这一检查。也可用 `--data 自定义.json` 指向替换后的文档库。

## 5. 项目结构

```
src/kb_agent/
  agent.py        # ReAct 循环:决策→工具→观察→调整;finish 校验与引用逐字核验;步数上限
  mock_model.py   # 离线 Mock 决策策略(边界:只验证流程)
  real_model.py   # 真实模型决策器 + 提示词
  llm.py          # OpenAI 兼容客户端 + 动作 JSON 解析
  retrieval.py    # 字符 bigram TF-IDF 检索 + 查询扩展
  tools.py        # search / read 工具 + 故障注入 + ToolBox
  store.py        # 文档库加载
  textutils.py    # 分句/数值提取/bigram 特征
  schemas.py      # 数据结构(动作/观察/Trace/最终交付)
  trace.py        # Trace JSON/Markdown 渲染
  config.py       # 环境变量 + .env 加载
  cli.py          # ask / chat / demo / trace / doctor
data/             # documents.json(8 篇合成文档)、rules.json(主题词/别名/同义词)
tests/            # 72 个测试:6 验收点 + 引用完整性 + 内容替换 + 上限 + CLI
examples/         # 6 组输入/输出/Trace + README 索引 + run_examples.py
docs/             # 00 题目备档 + 01~05 考核要求的五份文档
```

## 6. Mock 边界声明

提交的 `examples/` 材料由离线 Mock 决策策略生成(编写环境无模型凭据):Mock 与真实模型共用同一 ReAct 循环、工具与校验,能证明**流程、工具链路、交付格式与冲突处理逻辑**正确;但它的"决策"是确定性规则,**不证明真实语言模型的决策效果**。配置 `AGENT_LLM_*` 后执行 `python -m src.kb_agent.cli demo` 即可用真实模型重新生成全部材料。
