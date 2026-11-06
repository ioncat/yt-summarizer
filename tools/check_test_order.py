"""Run the backend test suite in reverse order and in a few random orders: it must pass in all of them (NS-22).

    python tools/check_test_order.py              # reverse + seeds 1, 2, 3
    python tools/check_test_order.py --seeds 5    # reverse + seeds 1..5
    python tools/check_test_order.py --quick      # reverse only

The orders come from the --reverse and --shuffle=SEED options of app/backend/tests/conftest.py (no plugin to install).
Exit code 0 when every run passed, 1 otherwise; a failing run prints its last lines and how to repeat it.
"""
import argparse
import os
import subprocess
import sys
import time

BACKEND = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "app", "backend")


def run(label: str, extra: list[str]) -> bool:
    cmd = [sys.executable, "-m", "pytest", "-q", "-W", "ignore", "-p", "no:cacheprovider", *extra]
    started = time.time()
    proc = subprocess.run(cmd, cwd=BACKEND, capture_output=True, text=True, encoding="utf8", errors="replace")
    lines = [l for l in proc.stdout.splitlines() if l.strip()]
    summary = lines[-1] if lines else "(no output)"
    print(f"{label:<14} {'ok  ' if proc.returncode == 0 else 'FAIL'} {summary} [{time.time() - started:.0f}s]")
    if proc.returncode != 0:
        for l in [l for l in lines if l.startswith(("FAILED", "ERROR"))][:15]:
            print("   ", l)
        print(f"    repeat: cd app/backend && python -m pytest -q {' '.join(extra)}")
    return proc.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seeds", type=int, default=3, help="how many random orders to run after the reverse one (default 3)")
    parser.add_argument("--quick", action="store_true", help="the reverse order only")
    args = parser.parse_args()
    results = [run("reverse", ["--reverse"])]
    if not args.quick:
        results += [run(f"shuffle {n}", [f"--shuffle={n}"]) for n in range(1, args.seeds + 1)]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
