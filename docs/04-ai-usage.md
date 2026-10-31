# 04 AI 辅助使用说明

记录 AI 辅助范围、个人贡献与验证方式。

## 1. AI 辅助范围

本项目由 AI 编程助手(ZCode,底层模型 GLM-5.3-Flash)辅助完成,覆盖:

- 项目骨架搭建(`src/`、`tests/`、`examples/`、`docs/`、`data/`)与全部源代码:ReAct 循环(`agent.py`)、检索(`retrieval.py`、`textutils.py`)、工具与故障注入(`tools.py`)、真实模型接入(`llm.py`、`real_model.py`)、离线 Mock 策略(`mock_model.py`)、CLI(`cli.py`)、Trace 渲染(`trace.py`);
- 合成数据(`data/documents.json` 含 D01/D02 冲突实例、`data/rules.json`)、113 个测试用例与 `examples/` 验证材料;
- `docs/` 全部文档与 README;
- 增量完善:冲突确认收敛(用户指定文档直读)、检索召回评测集、真实模型协议端到端集成测试(本地桩服务器)、黄金轨迹测试、GitHub Actions CI。

## 2. 实际用时与完成度

- **实际用时:约 2 小时**(含编码、测试、示例生成与审查修复);
- **完成范围**:考核核心链路全部完成 —— ReAct 决策循环、两个业务工具、6 个验收点全覆盖(另含"冲突确认收敛"延伸场景)、113 个可执行测试、7 组运行记录、五份文档、GitHub Actions CI(py3.9–3.12 × Linux/Windows);无未完成的核心项;
- **有意不做**(考核说明明确非必需):图形界面、线上部署、多 Agent、生产级 Runtime、向量数据库。

## 3. 个人贡献与分工

- **候选人**:提供考核题目与目标设定;确认选题与关键取舍(原生实现、CLI 运行方式、字符 bigram 检索、双模型路径);执行提交前验证;
- **AI 助手**:完成全部设计、编码、测试、示例生成与文档撰写;
- 全部验证命令均可复现(见第 4 节),文档中的"实际结果"均以测试与命令输出为准。

## 4. 验证记录(均可复现)

- [x] 全新克隆与干净 venv 中执行 `pip install -r requirements.txt` 安装成功,测试全部通过;
- [x] `python -m pytest tests/ -q`:113 passed(离线、约 4 秒);
- [x] `python -m src.kb_agent.cli ask "报销申请的期限是多久?"` 输出 needs_confirmation,列出 D01/D02 双方原文并请求确认;
- [x] `python -m src.kb_agent.cli demo` 重新生成的材料与仓库提交的 examples/ 逐字节一致;
- [x] README 第 3 节全部命令逐条执行通过(含管道喂入的多轮 chat);
- [x] 修改 data/documents.json 中 D01 的"30 天"为"45 天"后重跑,冲突数值随之变为 45/15(并有自动化测试固化);
- [x] examples/ 各 output.json 中的引用经脚本逐字校验,全部命中对应文档原文。

## 5. 补充声明

- examples/ 下全部 output.json/trace.md 均为本仓库代码真实运行产物,删除后可用 `demo` 命令复现;
- 提交材料的引擎边界(Mock 与真实模型的关系)在 README §6、docs/02、docs/03 与每份 trace.md 顶部声明;
- 开发过程中发现并修复的缺陷均有测试覆盖回归,细节见 git 提交历史。
