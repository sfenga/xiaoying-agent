# 04 AI 辅助使用说明

> 如实记录 AI 辅助范围、个人贡献与验证方式,符合考核"允许使用 AI 辅助工具,须如实记录"的要求。

## 1. AI 辅助范围

本项目在开发过程中使用了 AI 编程助手(**ZCode,底层模型 GLM-5.3-Flash**),辅助范围:

- 按考核题目要求搭建项目骨架(`src/`、`tests/`、`examples/`、`docs/`、`data/`);
- 编写全部源代码:ReAct 循环(`agent.py`)、检索(`retrieval.py`、`textutils.py`)、工具与故障注入(`tools.py`)、真实模型接入(`llm.py`、`real_model.py`)、离线 Mock 策略(`mock_model.py`)、CLI(`cli.py`)、Trace 渲染(`trace.py`);
- 编写合成数据(`data/documents.json` 含 D01/D02 冲突实例、`data/rules.json`)、76 个测试用例与 `examples/` 验证材料;
- 起草 `docs/` 全部文档与本 README。

## 2. 实际用时与完成度

- **实际用时:约 1 小时**(单人 + AI 辅助,从 23:00 建库到 00:00 前完成编码、测试、示例生成与双轴审查修复;候选人可按实际情况修正);
- **完成范围**:考核要求的核心链路全部完成 —— ReAct 决策循环、两个业务工具、6 个验收点全覆盖、76 个可执行测试、6 组运行记录、五份考核文档;无未完成的核心项;
- **有意不做**(考核说明明确非必需):图形界面、线上部署、多 Agent、生产级 Runtime、向量数据库;
- **边界项**:真实模型路径的端到端调优依赖模型凭据(见 docs/03-evaluation.md §4),属于如实标注的边界而非未完成项。

## 3. 个人贡献(候选人确认部分)

- 题目理解与验收标准拆解:确认 6 个验收点与冲突参考实例的处理口径(列冲突请求确认,不擅自选边);
- 关键取舍确认:原生实现(不用框架)、CLI 运行方式、字符 bigram 检索、双模型路径(Mock 边界如实标注);
- 交付审核:运行全部测试与示例命令,逐条核对 `docs/03-evaluation.md` 的验收点结果表;
- 【候选人补充:你实际复核/修改过的文件、你不同意或调整过的地方】

## 4. 验证方式

**开发过程中已执行并通过的验证(可随时复跑)**:

- [x] `pip install -r requirements.txt` 在干净 venv 中安装成功,随后测试全部通过;
- [x] `python -m pytest tests/ -q`:76 passed(离线、约 2 秒);
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

- 代码由 AI 生成后经过运行验证与测试把关;开发与审查中发现并修复的缺陷包括:finish 校验失败路径的 NameError(会使循环崩溃而非反馈模型)、`--inject none` 被误拒、复合问题漏读相关文档、`--json` 输出混入日志等;
- 未使用 AI 生成虚假运行结果:examples/ 下所有 output.json/trace.md 均为本仓库代码真实运行产物,可删除后用 `demo` 命令复现;
- 文档中所有"实际结果"均以测试与命令输出为准,无人工夸大描述;
- 提交材料的引擎边界(Mock vs 真实模型)在 README §6、docs/02、docs/03 与每份 trace.md 顶部均有明确声明。
