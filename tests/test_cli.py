"""CLI 端到端:ask / demo / trace / doctor 与退出码。"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.kb_agent.cli import main


def test_ask_json_output():
    code = main(["ask", "每个月吃饭有补贴吗?能补多少?", "--engine", "mock", "--json"])
    assert code == 0
    # main 通过 print 输出 JSON,由 capsys 捕获
    # (在调用方捕获,见下一条测试用 capsys 的版本)


def test_ask_json_output_captured(capsys):
    code = main(["ask", "每个月吃饭有补贴吗?能补多少?", "--engine", "mock", "--json"])
    out = capsys.readouterr().out
    payload = json.loads(out)
    assert code == 0
    assert payload["status"] == "answered"
    assert payload["citations"][0]["doc_id"] == "D04"
    assert payload["steps_used"] <= payload["max_steps"]


def test_ask_conflict_human_readable(capsys):
    main(["ask", "报销申请的期限是多久?", "--engine", "mock"])
    out = capsys.readouterr().out
    assert "needs_confirmation" in out
    assert "30 天" in out and "15 天" in out
    assert "确认" in out


def test_ask_with_inject(capsys):
    code = main(["ask", "报销申请的期限是多久?", "--engine", "mock", "--inject", "read_once"])
    out = capsys.readouterr().out
    assert code == 0
    assert "needs_confirmation" in out  # 故障后仍恢复并识别冲突


def test_ask_trace_out(tmp_path, capsys):
    prefix = tmp_path / "traces" / "run1"
    main(["ask", "每个月吃饭有补贴吗?能补多少?", "--engine", "mock", "--trace-out", str(prefix)])
    assert Path(str(prefix) + ".json").is_file()
    md = Path(str(prefix) + ".md").read_text(encoding="utf-8")
    assert "Trace" in md and "决策过程" in md


def test_invalid_inject_exit_code(capsys):
    assert main(["ask", "问题", "--engine", "mock", "--inject", "bogus"]) == 2


def test_inject_none_is_accepted(capsys):
    assert main(["ask", "每个月吃饭有补贴吗?能补多少?", "--engine", "mock", "--inject", "none"]) == 0


def test_real_engine_without_config_exit_code(capsys):
    assert main(["ask", "问题", "--engine", "real"]) == 2


def test_demo_generates_all_cases(tmp_path, capsys):
    outdir = tmp_path / "examples"
    code = main(["demo", "--outdir", str(outdir), "--engine", "mock"])
    assert code == 0
    case_dirs = sorted(d.name for d in outdir.iterdir() if d.is_dir())
    assert len(case_dirs) == 6
    for name in case_dirs:
        d = outdir / name
        assert (d / "input.json").is_file()
        assert (d / "output.json").is_file()
        assert (d / "trace.md").is_file()
    readme = (outdir / "README.md").read_text(encoding="utf-8")
    assert "验收点" in readme
    # input/output 与 trace 内容一致性
    payload = json.loads((outdir / "case2_doc_conflict" / "output.json").read_text(encoding="utf-8"))
    assert payload["status"] == "needs_confirmation"
    trace_md = (outdir / "case2_doc_conflict" / "trace.md").read_text(encoding="utf-8")
    assert payload["question"] in trace_md


def test_demo_case5_has_turn1_context(tmp_path, capsys):
    outdir = tmp_path / "examples"
    main(["demo", "--outdir", str(outdir), "--engine", "mock"])
    inp = json.loads((outdir / "case5_context_followup" / "input.json").read_text(encoding="utf-8"))
    assert inp["turn1_question"]
    assert inp["history"] and inp["history"][0]["topics"]
    assert inp["turn1_output"]["status"] == "answered"


def test_trace_command_renders(tmp_path, capsys):
    outdir = tmp_path / "examples"
    main(["demo", "--outdir", str(outdir), "--engine", "mock"])
    code = main(["trace", str(outdir / "case2_doc_conflict" / "output.json")])
    out = capsys.readouterr().out
    assert code == 0
    assert "Step 1" in out and "最终交付" in out


def test_doctor_runs(capsys):
    code = main(["doctor", "--engine", "mock"])
    out = capsys.readouterr().out
    assert code == 0
    assert "文档数量: 8" in out
