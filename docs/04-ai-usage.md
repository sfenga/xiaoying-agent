# 04 AI 辅助使用说明

> 如实记录 AI 辅助范围、个人贡献与验证方式,符合考核"允许使用 AI 辅助工具,须如实记录"的要求。

## 1. AI 辅助范围

本项目在开发过程中使用了 AI 编程助手(**ZCode,底层模型 GLM-5.3-Flash**),辅助范围:

- 按考核题目要求搭建项目骨架(`src/`、`tests/`、`examples/`、`docs/`、`data/`);
- 编写全部源代码:ReAct 循环(`agent.py`)、检索(`retrieval.py`、`textutils.py`)、工具与故障注入(`tools.py`)、真实模型接入(`llm.py`、`real_model.py`)、离线 Mock 策略(`mock_model.py`)、CLI(`cli.py`)、Trace 渲染(`trace.py`);
- 编写合成数据(`data/documents.json` 含 D01/D02 冲突实例、`data/rules.json`)、109 个测试用例与 `examples/` 验证材料;
- 起草 `docs/` 全部文档与本 README;
- 第二轮增量:冲突确认收敛(用户指定文档直读)、检索召回评测集、真实模型协议端到端集成测试(本地桩服务器)、黄金轨迹测试、GitHub Actions CI。

## 2. 实际用时与完成度

- **实际用时:约 2 小时**(第一轮 1 小时完成核心交付并双轴审查;第二轮 1 小时增量完善:冲突确认收敛闭环、检索召回评测集、真实模型协议端到端集成测试、黄金轨迹、CI;候选人可按实际情况修正);
- **完成范围**:考核要求的核心链路全部完成 —— ReAct 决策循环、两个业务工具、6 个验收点全覆盖(另加"冲突确认收敛"延伸场景)、109 个可执行测试、7 组运行记录、五份考核文档、GitHub Actions CI(py3.9–3.12 × Linux/Windows);无未完成的核心项;
- **有意不做**(考核说明明确非必需):图形界面、线上部署、多 Agent、生产级 Runtime、向量数据库;
- **边界项**:真实商用模型的提示词调优依赖模型凭据(协议路径已由桩服务器集成测试覆盖,见 docs/03-evaluation.md §4),属于如实标注的边界而非未完成项。

## 3. 个人贡献(如实记录)

- **候选人**:提供考核题目材料与任务目标(限定用时、按考核要求冲高分、完成后须审核);确认选题为「企业知识问答 Agent」;按第 4 节清单执行提交前最终验证与确认;
- **AI 助手**:完成全部设计、编码、测试、示例生成与文档撰写(范围见第 1 节);
- **分工说明**:源码与文档均由 AI 完成,候选人未直接修改代码;候选人可在提交前对任何部分复核、修改或调整,调整后请同步更新本节与 `docs/03-evaluation.md` 的验证记录。

## 4. 验证方式

**开发过程中已执行并通过的验证(可随时复跑)**:

- [x] `pip install -r requirements.txt` 在干净 venv 中安装成功,随后测试全部通过;
- [x] `python -m pytest tests/ -q`:109 passed(离线、约 4 秒);
- [x] `python -m src.kb_agent.cli ask "报销申请的期限是多久?"` 输出 needs_confirmation,列出 D01/D02 双方原文并请求确认;
- [x] `python -m src.kb_agent.cli demo` 重新生成的材料与仓库提交的 `examples/` 逐字节一致(diff 校验);
- [x] README 第 3 节全部命令在干净 venv 中逐条执行通过(含管道喂入的多轮 chat);
- [x] 抽查 trace.md:每步有决策依据、工具参数、观察摘要、后续动作;引用可逐字在 data/documents.json 中找到(亦有自动化测试);
- [x] 修改 data/documents.json 中 D01 的"30 天"为"45 天"后重跑,冲突数值随之变为 45/15(`tests/test_conflict.py::test_content_swap_changes_conflict_values` 亦覆盖)。

**候选人提交前应完成的确认**:

- [ ] 本地重跑上述命令,确认结果与本文件记录一致;
- [ ] 按个人实际情况修改第 3 节,补充个人复核与调整内容;
- [ ] 建库推送后回填 README 顶部的 GitHub URL 与最终 commit SHA;
- [ ] 确认未提交任何真实密钥或隐私数据(`.env` 已被 .gitignore 排除)。

## 5. AI 使用边界声明

- 代码由 AI 生成后经过运行验证与测试把关;开发与审查中发现并修复的缺陷包括:finish 校验失败路径的 NameError(会使循环崩溃而非反馈模型)、`--inject none` 被误拒、复合问题漏读相关文档、`--json` 输出混入日志、指定文档直读缺少已读守卫导致重复读取、追问新主题被历史主题压制、测试中全局 monkey-patch `requests` 造成跨测试污染、`_build_final` 重复调用时剔除记录被清空等;
- 未使用 AI 生成虚假运行结果:examples/ 下所有 output.json/trace.md 均为本仓库代码真实运行产物,可删除后用 `demo` 命令复现;
- 文档中所有"实际结果"均以测试与命令输出为准,无人工夸大描述;
- 提交材料的引擎边界(Mock vs 真实模型)在 README §6、docs/02、docs/03 与每份 trace.md 顶部均有明确声明。
