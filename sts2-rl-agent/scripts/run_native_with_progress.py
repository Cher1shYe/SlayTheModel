"""Run ALL with event-driven progress; no polling or observer process."""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import sys
import traceback

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--progress-file',type=Path,required=True)
    args,runner_args=parser.parse_known_args()
    from sts2_env.az import config
    write=config.atomic_json
    progress=dict(status='starting',pid=os.getpid(),runner_args=runner_args)
    def publish():
        progress['updated_at']=datetime.now(timezone.utc).isoformat()
        write(args.progress_file,progress)
    def observed_write(path,value):
        write(path,value)
        if isinstance(value,dict) and Path(path).name in ('progress.json','state.json','report.json','native-initialization.json'):
            progress.update(status='running',last_artifact=str(Path(path).resolve()))
            if Path(path).name=='progress.json':
                progress['collection']=value
                progress['phase']='validation' if 'native-validation' in str(path) else 'collection'
            elif Path(path).name=='native-initialization.json':
                progress['phase']='initial_baseline'
            else:
                progress['completed_iterations']=len(value.get('history',[]))
                progress['pending']=value.get('pending')
                progress['champion_checkpoint']=value.get('champion_checkpoint')
                progress['learner_checkpoint']=value.get('learner_checkpoint')
                if value.get('pending'): progress['phase']='update_or_candidate_validation'
            publish()
    config.atomic_json=observed_write
    publish()
    try:
        from sts2_env.az.all_runner import main as run
        run(runner_args)
    except BaseException as error:
        progress.update(status='failed',error=repr(error),traceback=traceback.format_exc())
        publish()
        raise
    else:
        progress.update(status='completed')
        publish()


if __name__=='__main__': main()
