"""重新生成 examples/ 下的全部验证材料(与 `python -m src.kb_agent.cli demo` 等价)。

用法(仓库根目录):
    python examples/run_examples.py            # 用当前配置引擎(无模型凭据时为 Mock)
    python examples/run_examples.py --engine mock
    python examples/run_examples.py --engine real  # 需在 .env 配置 AGENT_LLM_*
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.kb_agent.cli import main  # noqa: E402

if __name__ == "__main__":
    args = sys.argv[1:]
    if not any(a.startswith("--engine") or a == "--outdir" for a in args):
        args = ["--outdir", str(PROJECT_ROOT / "examples")] + args
    sys.exit(main(["demo"] + args))
