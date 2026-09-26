"""Run every test module in its own Qt process; preserve all failures and reports.

Qt native process failures cannot be recovered inside pytest. Module isolation
keeps each module's session fixtures intact while collecting evidence from the
rest of the suite. No failed module is skipped, retried, or treated as passing.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--coverage", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report_root = root / "build" / "test-reports"
    report_root.mkdir(parents=True, exist_ok=True)
    run_dir = Path(tempfile.mkdtemp(prefix="run-", dir=report_root))
    env = os.environ.copy()
    env["PYTHONFAULTHANDLER"] = "1"
    env["COVERAGE_FILE"] = str(run_dir / ".coverage")
    failures = []
    modules = sorted((root / "main" / "tests").glob("test_*.py"))
    print(f"Running {len(modules)} modules; reports: {run_dir}", flush=True)
    for module in modules:
        cmd = [sys.executable, "-m", "pytest", str(module),
               "-c", str(root / "main/tests/pytest.ini"), "-q", "-s",
               f"--junitxml={run_dir / (module.stem + '.xml')}"]
        if args.coverage:
            cmd += ["--cov", "--cov-append", "--cov-report=",
                    f"--cov-config={root / '.coveragerc'}"]
        print(f"\n=== {module.name} ===", flush=True)
        result = subprocess.run(cmd, cwd=root, env=env, check=False)
        if result.returncode:
            failures.append((module.name, result.returncode))
    if args.coverage:
        for extra in (["xml", "-o", str(root / "coverage.xml")],
                      ["report", "--skip-covered", "--fail-under=37"]):
            result = subprocess.run(
                [sys.executable, "-m", "coverage", *extra], cwd=root, env=env, check=False,
            )
            if result.returncode:
                failures.append(("coverage " + extra[0], result.returncode))
    print(f"\nCompleted {len(modules)} modules; failed modules/checks: {failures}", flush=True)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
