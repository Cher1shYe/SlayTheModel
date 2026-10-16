"""Frozen G2.2b local validation pipeline, launched by the Claude monitor wrapper.

No background jobs: each subprocess is joined. A failed smoke, training or
verification halts the pipeline. The observer, not Codex, reads live metrics.
"""
from pathlib import Path
import subprocess
import sys


def run():
    root=Path(__file__).resolve().parents[1]
    common=[sys.executable,"-u","scripts/run_alphazero_continuous.py",
            "--summon","--quick","--iterations","3","--workers","8"]
    commands=[
        common+["--smoke","--output","output/az_g2_summon_v1_smoke"],
        common+["--output","output/az_g2_summon_v1_quick","--smoke-evidence",
                "output/az_g2_summon_v1_smoke/smoke_report.json"],
        [sys.executable,"scripts/verify_az_continuous_results.py","--directory",
         "output/az_g2_summon_v1_quick","--output","docs/az_summon_verification.json"],
        [sys.executable,"scripts/analyze_az_summon.py"],
    ]
    for command in commands:
        subprocess.run(command,cwd=root,check=True)
    print("G2.2b pipeline completed: smoke, three rounds per seed, final tests and artifact verification.",flush=True)


if __name__ == "__main__":
    run()
