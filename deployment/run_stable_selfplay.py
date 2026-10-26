"""Detached-job entry; write errors to the same progress artifact."""
import os
os.environ['OMP_NUM_THREADS']='1'
os.environ['MKL_NUM_THREADS']='1'
import sys
import traceback
from pathlib import Path
import selfplay_compare as experiment

if __name__=='__main__':
    out=experiment.ROOT/'deployment/selfplay_stable_s512_r1'
    sys.argv=[__file__,'--out',str(out),'--rounds','1','--games','40','--epochs','2',
              '--sims','512','--workers','4','--initial-round','4','--seed','20261027','--stabilize',*sys.argv[1:]]
    try:
        experiment.main()
    except BaseException:
        out.mkdir(parents=True,exist_ok=True)
        experiment.dump(out/'progress.json',dict(stage='failed',error=traceback.format_exc()))
        raise
