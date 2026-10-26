"""Regression checks for transient and persistent Windows replacement locks."""
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import selfplay_compare as experiment

with tempfile.TemporaryDirectory() as directory:
    path=Path(directory)/'progress.json'
    original=Path.replace
    attempts=[]
    def transient(self,target):
        attempts.append(1)
        if len(attempts)<3: raise PermissionError('simulated Windows viewer lock')
        return original(self,target)
    with patch.object(Path,'replace',transient),patch.object(experiment.time,'sleep'):
        assert experiment.dump(path,{'stage':'running'})
    assert len(attempts)==3 and json.loads(path.read_text())['stage']=='running'
    with patch.object(Path,'replace',side_effect=PermissionError('persistent lock')),patch.object(experiment.time,'sleep'):
        assert experiment.dump(path,{'stage':'next'}) is False
        assert json.loads(path.with_suffix('.tmp').read_text())['stage']=='next'
        try: experiment.dump(Path(directory)/'results.json',{'important':True})
        except PermissionError: pass
        else: raise AssertionError('Important output write failure was swallowed')
    assert experiment.dump(path,{'stage':'complete'})
    assert json.loads(path.read_text())['stage']=='complete'
print('PASS: transient retry, nonfatal progress lock, strict results, recovery')
