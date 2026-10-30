"""命令行入口(考核要求的运行方式:CLI)。

用法示例:
  python -m src.kb_agent.cli ask "每个月吃饭有补贴吗?能补多少?"
  python -m src.kb_agent.cli ask "报销申请的期限是多久?" --inject read_once
  python -m src.kb_agent.cli chat                 # 多轮对话(演示上下文追问)
  python -m src.kb_agent.cli demo                 # 生成 examples/ 下全部 7 组验证材料
  python -m src.kb_agent.cli doctor               # 查看当前生效配置
  python -m src.kb_agent.cli trace examples/case2_doc_conflict/output.json
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from .agent import ReActAgent
from .config import PROJECT_ROOT, Config, ConfigError
from .mock_model import MockReActModel
from .real_model import LLMReActModel
from .retrieval import RetrievalIndex
from .schemas import AgentResult, HistoryTurn
from .store import DocStore
from .tools import ReadDocumentTool, SearchDocumentsTool, ToolBox
from .trace import MOCK_BANNER, render_markdown, result_from_dict, result_to_dict


# ---------------------------------------------------------------------- #
# 组装
# ---------------------------------------------------------------------- #
def build_agent(cfg: Config, inject_override: Optional[str] = None) -> Tuple[ReActAgent, DocStore]:
    store = DocStore.load(cfg.data_path)
    rules = json.loads(Path(cfg.rules_path).read_text(encoding="utf-8"))
    index = RetrievalIndex(store, rules)
    search_tool = SearchDocumentsTool(index, rules=rules, default_top_k=cfg.top_k)
    read_tool = ReadDocumentTool(store)
    inject = cfg.inject_failure if inject_override is None else inject_override
    toolbox = ToolBox(search_tool, read_tool, inject_failure=inject)
    if cfg.engine == "real":
        from .llm import OpenAICompatLLM

        model = LLMReActModel(OpenAICompatLLM(cfg.base_url, cfg.api_key, cfg.model))
    else:
        model = MockReActModel(rules)
    agent = ReActAgent(
        model,
        toolbox,
        store,
        max_steps=cfg.max_steps,
        engine=cfg.engine,
        model_name=model.name,
    )
    return agent, store


def history_from_payload(payload: List[dict]) -> List[HistoryTurn]:
    turns = []
    for t in payload:
        turns.append(
            HistoryTurn(
                question=str(t.get("question", "")),
                answer=str(t.get("answer", "")),
                status=str(t.get("status", "answered")),
                cited_doc_ids=[str(x) for x in (t.get("cited_doc_ids") or [])],
                topics=[str(x) for x in (t.get("topics") or [])],
            )
        )
    return turns


# ---------------------------------------------------------------------- #
# 输出
# ---------------------------------------------------------------------- #
def _setup_stdout() -> None:
    try:
        if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def print_result(r: AgentResult) -> None:
    print(f"\n任务状态: {r.status}" + ("  [达到步数上限,未完成]" if r.limit_reached else ""))
    print(f"回答: {r.answer or '(无)'}")
    if r.citations:
        print("引用:")
        for c in r.citations:
            print(f"  - [{c.doc_id} v{c.version_date} §{c.section or '-'}] 「{c.quote}」")
    for conflict in r.conflicts:
        print(f"冲突「{conflict.topic}」:")
        for o in conflict.options:
            print(f"  - [{o.doc_id} v{o.version_date}] 「{o.quote}」→ {o.value or '(无数值)'}(证据: {o.evidence})")
    if r.gaps:
        print(f"资料缺口: {';'.join(r.gaps)}")
    if r.next_question_to_user:
        print(f"向你确认: {r.next_question_to_user}")
    if r.dropped_citations:
        print(f"⚠ 已剔除 {len(r.dropped_citations)} 条无法核验的引用,详见 trace")
    print(f"步数: {r.steps_used}/{r.max_steps} | 引擎: {r.engine}({r.model})")


def print_mock_warning(engine: str) -> None:
    if engine == "mock":
        print(MOCK_BANNER)


# ---------------------------------------------------------------------- #
# 子命令
# ---------------------------------------------------------------------- #
def cmd_ask(args: argparse.Namespace) -> int:
    cfg = _config_from_args(args)
    agent, _ = build_agent(cfg)
    if not args.json:  # --json 模式输出必须是纯 JSON
        print_mock_warning(cfg.engine)
    history: List[HistoryTurn] = []
    if args.history_file:
        payload = json.loads(Path(args.history_file).read_text(encoding="utf-8"))
        history = history_from_payload(payload)
    result = agent.run(args.question, history=history)
    if args.json:
        print(json.dumps(result_to_dict(result), ensure_ascii=False, indent=2))
    else:
        print_result(result)
    if args.trace_out:
        prefix = Path(args.trace_out)
        prefix.parent.mkdir(parents=True, exist_ok=True)
        prefix.with_suffix(".json").write_text(
            json.dumps(result_to_dict(result), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        prefix.with_suffix(".md").write_text(render_markdown(result), encoding="utf-8")
        print(f"\nTrace 已写入: {prefix.with_suffix('.json')} / {prefix.with_suffix('.md')}")
    return 0


def cmd_chat(args: argparse.Namespace) -> int:
    cfg = _config_from_args(args)
    agent, _ = build_agent(cfg)
    print("企业知识问答 Agent(多轮对话;输入 exit/quit/退出 结束)")
    print_mock_warning(cfg.engine)
    turns: List[HistoryTurn] = []
    while True:
        try:
            question = input("\n你> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not question:
            continue
        if question.lower() in ("exit", "quit", "退出"):
            break
        result = agent.run(question, history=turns)
        print_result(result)
        turns.append(
            HistoryTurn(
                question=result.question,
                answer=result.answer or "",
                status=result.status,
                cited_doc_ids=[c.doc_id for c in result.citations],
                topics=result.topics,
            )
        )
    return 0


# ---------------------------------------------------------------------- #
# demo:生成 examples/ 验证材料
# ---------------------------------------------------------------------- #
@dataclass
class DemoCase:
    case_id: str
    title: str
    acceptance: str  # 对应考核验收点
    question: str
    turn1_question: Optional[str] = None  # 两轮场景:先跑 turn1,其结果作为上下文
    inject: str = ""


DEMO_CASES: List[DemoCase] = [
    DemoCase(
        "case1_clear_answer",
        "明确答案:依据文档回答补贴问题",
        "明确答案",
        "每个月吃饭有补贴吗?能补多少?",
    ),
    DemoCase(
        "case2_doc_conflict",
        "文档冲突:报销期限 30 天 vs 15 天,列出冲突并请求确认",
        "文档冲突",
        "报销申请的期限是多久?",
    ),
    DemoCase(
        "case3_out_of_scope",
        "资料外问题:改写检索后仍无命中,如实说明缺口",
        "资料外问题",
        "公司附近有什么好吃的餐厅推荐?",
    ),
    DemoCase(
        "case4_paraphrase",
        "改写后的相似问题:口语化问年假天数(经同义词改写后命中)",
        "改写后的相似问题",
        "工作满一年能休几天假?",
    ),
    DemoCase(
        "case5_context_followup",
        "上下文追问:结合上一轮主题理解「那上下班路上的呢?」",
        "上下文追问",
        "那上下班路上的呢?",
        turn1_question="每个月吃饭有补贴吗?能补多少?",
    ),
    DemoCase(
        "case6_tool_failure",
        "工具失败:读取文档故障后改用其他证据恢复",
        "工具失败",
        "报销申请的期限是多久?",
        inject="read_once",
    ),
    DemoCase(
        "case7_conflict_resolved",
        "冲突确认收敛:用户确认制度版本后依指定文档作答",
        "文档冲突(确认后收敛)",
        "按 D01 的规定算",
        turn1_question="报销申请的期限是多久?",
    ),
]


def _write_case(outdir: Path, cfg: Config, case: DemoCase, result: AgentResult, history_payload: List[dict], turn1_result: Optional[AgentResult]) -> None:
    case_dir = outdir / case.case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    try:
        data_rel = Path(cfg.data_path).resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        data_rel = str(cfg.data_path)
    input_data = {
        "case_id": case.case_id,
        "title": case.title,
        "acceptance_point": case.acceptance,
        "engine": cfg.engine,
        "model": result.model,
        "max_steps": cfg.max_steps,
        "inject_failure": case.inject,
        "question": case.question,
        "turn1_question": case.turn1_question,
        "history": history_payload,
        "data_path": data_rel,
    }
    if turn1_result is not None:
        input_data["turn1_output"] = {
            "status": turn1_result.status,
            "answer": turn1_result.answer,
            "citations": [
                {"doc_id": c.doc_id, "version_date": c.version_date, "section": c.section, "quote": c.quote}
                for c in turn1_result.citations
            ],
        }
    (case_dir / "input.json").write_text(json.dumps(input_data, ensure_ascii=False, indent=2), encoding="utf-8")
    (case_dir / "output.json").write_text(
        json.dumps(result_to_dict(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md_title = f"{case.case_id} · {case.title}(验收点: {case.acceptance})"
    (case_dir / "trace.md").write_text(render_markdown(result, title=md_title), encoding="utf-8")


def cmd_demo(args: argparse.Namespace) -> int:
    cfg = _config_from_args(args)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    print_mock_warning(cfg.engine)
    rows = []
    for case in DEMO_CASES:
        agent, _ = build_agent(cfg, inject_override=case.inject)
        turn1_result: Optional[AgentResult] = None
        history_payload: List[dict] = []
        if case.turn1_question:
            turn1_result = agent.run(case.turn1_question, history=[])
            history_payload = [
                {
                    "question": turn1_result.question,
                    "answer": turn1_result.answer or "",
                    "status": turn1_result.status,
                    "cited_doc_ids": [c.doc_id for c in turn1_result.citations],
                    "topics": turn1_result.topics,
                }
            ]
        result = agent.run(case.question, history=history_from_payload(history_payload))
        _write_case(outdir, cfg, case, result, history_payload, turn1_result)
        rows.append((case, result))
        print(f"[OK] {case.case_id}: {case.title} → status={result.status}, steps={result.steps_used}")

    index_lines = [
        "# examples/ 验证材料索引",
        "",
        f"由 `python -m src.kb_agent.cli demo`(engine={cfg.engine}, model={rows[0][1].model if rows else '-'})生成;",
        "复现命令见仓库 README。以下 7 组输入/输出/Trace 覆盖全部 6 个验收点及「冲突确认收敛」延伸场景。",
        "",
        "| 用例 | 验收点 | 问题 | 任务状态 | 步数 | 材料 |",
        "|------|--------|------|----------|------|------|",
    ]
    for case, result in rows:
        q = case.question
        index_lines.append(
            f"| {case.case_id} | {case.acceptance} | {q} | `{result.status}` | {result.steps_used} |"
            f" [{case.case_id}/]({case.case_id}/) |"
        )
    index_lines += [
        "",
        "> 说明:若引擎为 mock,以下 Trace 仅验证流程与工具链路,不证明真实模型决策效果;",
        "配置 AGENT_LLM_* 后重跑 `demo` 即可用真实模型生成同等材料。",
        "",
    ]
    (outdir / "README.md").write_text("\n".join(index_lines), encoding="utf-8")
    print(f"\n全部用例已写入 {outdir}(含 README.md 索引)")
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.output_json).read_text(encoding="utf-8"))
    result = result_from_dict(payload)
    print(render_markdown(result))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    cfg = _config_from_args(args)
    print("当前生效配置:")
    print(f"  引擎(请求): {cfg.engine_request} → 实际: {cfg.engine}")
    print(f"  模型: {cfg.model or '(未配置)'} | base_url: {cfg.base_url or '(未配置)'}")
    print(f"  API Key: {'已配置(不显示)' if cfg.api_key else '未配置'}")
    print(f"  最大步数: {cfg.max_steps} | top_k: {cfg.top_k} | 故障注入: {cfg.inject_failure or '无'}")
    print(f"  文档库: {cfg.data_path} {'✓' if Path(cfg.data_path).is_file() else '✗ 文件不存在'}")
    print(f"  规则文件: {cfg.rules_path} {'✓' if Path(cfg.rules_path).is_file() else '✗ 文件不存在'}")
    if Path(cfg.data_path).is_file():
        store = DocStore.load(cfg.data_path)
        print(f"  文档数量: {len(store)}(" + ", ".join(d.doc_id for d in store.all()) + ")")
    print_mock_warning(cfg.engine)
    return 0


# ---------------------------------------------------------------------- #
# 参数解析
# ---------------------------------------------------------------------- #
def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--engine", choices=["auto", "mock", "real"], help="模型引擎(默认读 AGENT_MODEL_ENGINE,缺省 auto)")
    p.add_argument("--max-steps", type=int, help="ReAct 最大步数(默认 8)")
    p.add_argument("--top-k", type=int, help="每次检索返回条数(默认 4)")
    p.add_argument("--data", help="文档库 JSON 路径(默认 data/documents.json)")
    p.add_argument("--rules", help="规则 JSON 路径(默认 data/rules.json)")
    p.add_argument("--inject", dest="inject", help="故障注入: read_once / search_once / read_all / none")


def _config_from_args(args: argparse.Namespace) -> Config:
    cfg = Config.from_env()
    cfg.apply_overrides(
        engine=getattr(args, "engine", None),
        max_steps=getattr(args, "max_steps", None),
        top_k=getattr(args, "top_k", None),
        data_path=getattr(args, "data", None),
        rules_path=getattr(args, "rules", None),
        inject=getattr(args, "inject", None),
    )
    return cfg


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kb_agent",
        description="企业知识问答 Agent(ReAct 循环 + 文档检索/读取工具)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ask = sub.add_parser("ask", help="单轮问答")
    p_ask.add_argument("question", help="用户问题")
    p_ask.add_argument("--history-file", help="对话历史 JSON 文件(数组,元素含 question/answer)")
    p_ask.add_argument("--json", action="store_true", help="以 JSON 输出完整结果")
    p_ask.add_argument("--trace-out", help="将完整结果与 Trace 写入指定前缀(.json/.md)")
    _add_common(p_ask)
    p_ask.set_defaults(func=cmd_ask)

    p_chat = sub.add_parser("chat", help="多轮对话(自动携带上下文)")
    _add_common(p_chat)
    p_chat.set_defaults(func=cmd_chat)

    p_demo = sub.add_parser("demo", help="生成 examples/ 下全部验证材料")
    p_demo.add_argument("--outdir", default=str(PROJECT_ROOT / "examples"), help="输出目录(默认 examples/)")
    _add_common(p_demo)
    p_demo.set_defaults(func=cmd_demo)

    p_trace = sub.add_parser("trace", help="渲染查看一次运行的 Trace")
    p_trace.add_argument("output_json", help="output.json / --trace-out 生成的 JSON 文件")
    p_trace.set_defaults(func=cmd_trace)

    p_doctor = sub.add_parser("doctor", help="查看当前生效配置")
    _add_common(p_doctor)
    p_doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    _setup_stdout()
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except ConfigError as exc:
        print(f"[配置错误] {exc}", file=sys.stderr)
        return 2
    except FileNotFoundError as exc:
        print(f"[文件错误] {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
