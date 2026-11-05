"""Export reviewable text changes against the immutable alphazero base.
Does not stage, commit, push, or modify that base. Verify in a temporary tree.
"""
from pathlib import Path
import difflib, hashlib, json, shutil, subprocess, tempfile
root = Path(__file__).resolve().parent.parent
base = root.parents[1] / 'reference/alphazero-be401e8'
out = root / 'validation/round2'
prior = json.loads((root / 'validation/changed-files.json').read_text())
paths = {row['path'] for row in prior['files']}
allowed = {'.py','.cs','.csproj','.md','.json','.h','.cpp','.inc','.txt','.godot','.plist','.tscn','.toml','.ps1','.sh'}
for folder in ('agent','deployment','docs','tests','scripts','tools','bridge',
               'simulator/src','simulator/include','simulator/bindings','simulator/content','simulator/tools','simulator/tests'):
    for path in (root / folder).rglob('*'):
        rel=path.relative_to(root)
        if path.is_file() and path.suffix in allowed and not set(rel.parts).intersection({'__pycache__','obj','bin','.godot'}):
            paths.add(str(rel))
for folder in ('native-relic-round2-fixtures','native-event-round2-fixtures','native-boundary-fixtures'):
    for path in (root / folder).iterdir():
        if path.is_file() and path.suffix in allowed: paths.add(str(path.relative_to(root)))
paths.update({'validation/export_port.py', 'validation/round2/summary.json',
              'validation/round2/cpp-tests.json','validation/round2/engine-contract.json',
              'validation/round2/python-integration.txt','validation/round2/python-identity-results.txt',
              'validation/round2/benchmark-1000.txt','validation/round2/bridge-build.txt',
              'validation/round2/round1-status.md','validation/round2/puct-training-smoke-audit.json',
              'validation/round2/puct-training-smoke-summary.md','validation/round2/puct-classification-tests.txt',
              'validation/round2/python-identity-results-final.txt'})
# The previous round's immutable evidence is kept, including its old summary.
rows=[];chunks=[]
for rel in sorted(paths):
    src=root/rel;old=base/rel
    if not src.is_file(): continue
    newtext=src.read_text();oldtext=old.read_text() if old.is_file() else ''
    if newtext==oldtext: continue
    # All source artifacts are text with newline endings, enabling normal git patches.
    if newtext and not newtext.endswith('\n'): newtext+='\n'
    if oldtext and not oldtext.endswith('\n'): oldtext+='\n'
    chunks.append(f'diff --git a/{rel} b/{rel}\n')
    if not old.exists(): chunks.append('new file mode 100644\n')
    chunks.extend(difflib.unified_diff(oldtext.splitlines(True),newtext.splitlines(True),
                  fromfile=f'a/{rel}' if old.exists() else '/dev/null',tofile=f'b/{rel}'))
    rows.append({'path':rel,'status':'modified' if old.exists() else 'added',
                 'sha256':hashlib.sha256(src.read_bytes()).hexdigest()})
patch=out/'native-rules-port-v2.patch';patch.write_text(''.join(chunks))
with tempfile.TemporaryDirectory(prefix='sts2-port-v2-check-') as tmp:
    stage=Path(tmp)
    for row in rows:
        rel=row['path'];src=base/rel
        if src.is_file():
            dest=stage/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dest)
    check=subprocess.run(['git','apply','--check',str(patch)],cwd=stage,text=True,capture_output=True)
    if check.returncode: raise RuntimeError(check.stdout+check.stderr)
report={'base_commit':prior['base_commit'],'files':rows,'patch_sha256':hashlib.sha256(patch.read_bytes()).hexdigest(),
        'source_patch_applies_to_base':True,'patch_bytes':patch.stat().st_size}
(out/'changed-files.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({'files':len(rows),'patch_bytes':report['patch_bytes'],'apply_check':True}))
