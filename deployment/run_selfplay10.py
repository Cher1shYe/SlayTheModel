"""Persistent local 10-round stabilized/optimized PUCT512 experiment."""
import os
os.environ['OMP_NUM_THREADS']='1'
os.environ['MKL_NUM_THREADS']='1'
import sys
import traceback
import selfplay_compare as experiment

if __name__=='__main__':
    out=experiment.ROOT/'deployment/selfplay_fast_s512_r10'
    sys.argv=[__file__,'--out',str(out),'--rounds','10','--games','40','--epochs','2',
              '--sims','512','--workers','4','--initial-round','1',
              '--initial-dir',str(experiment.ROOT/'deployment/selfplay_stable_s512_r1'),
              '--seed','20261028','--stabilize','--fast-puct']
    try:
        experiment.main()
    except BaseException:
        out.mkdir(parents=True,exist_ok=True)
        experiment.dump(out/'progress.json',dict(stage='failed',error=traceback.format_exc()))
        raise
