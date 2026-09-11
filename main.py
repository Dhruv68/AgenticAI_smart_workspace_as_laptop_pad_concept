from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from agentic_workspace.app import run
except ImportError:
    print(
        "Cannot start: the app package 'src/agentic_workspace' is not in "
        "this checkout.\n"
        "This repo currently holds the reference HTML prototype "
        "(reference_canvas.html) and the vision smoke test (test_vision.py).\n"
        "Either push the src/ package, or open reference_canvas.html in a "
        "browser to try the interaction prototype.",
        file=sys.stderr,
    )
    raise SystemExit(1)

if __name__ == "__main__":
    raise SystemExit(run())
