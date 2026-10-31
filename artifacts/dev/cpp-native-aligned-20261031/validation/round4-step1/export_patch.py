"""Export this step only against its preserved pre-step source; never commits."""
from pathlib import Path
import difflib, hashlib, json, shutil, subprocess, tempfile
out = Path(__file__).resolve().parent
root = out.parents[1]
base = out / "source-before"
paths = set(json.loads((out / "source-before-manifest.json").read_text()))
paths.update(str(p.relative_to(root)) for p in (root / "simulator/tests").glob("native_step1_*.cpp"))
paths.add("tests/test_native_step1_state.py")
allowed = {".py", ".cs", ".csproj", ".md", ".json", ".inc", ".txt", ".godot", ".plist", ".tscn", ".props"}
for folder in root.glob("native-round4-step1-*-fixtures"):
    paths.update(str(p.relative_to(root)) for p in folder.iterdir() if p.is_file() and p.suffix in allowed)
paths.update(str(p.relative_to(root)) for p in out.iterdir()
             if p.is_file() and p.suffix in {".py", ".json", ".txt", ".md"}
             and p.name not in {"changed-files.json", "source-before-manifest.json"})
rows, chunks = [], []
for rel in sorted(paths):
    src, old = root / rel, base / rel
    if not src.is_file():
        continue
    newtext = src.read_text()
    oldtext = old.read_text() if old.is_file() else ""
    if newtext == oldtext:
        continue
    if newtext and not newtext.endswith("\n"): newtext += "\n"
    if oldtext and not oldtext.endswith("\n"): oldtext += "\n"
    chunks.append(f"diff --git a/{rel} b/{rel}\n")
    if not old.exists(): chunks.append("new file mode 100644\n")
    chunks.extend(difflib.unified_diff(oldtext.splitlines(True), newtext.splitlines(True),
                  fromfile=f"a/{rel}" if old.exists() else "/dev/null", tofile=f"b/{rel}"))
    rows.append({"path": rel, "status": "modified" if old.exists() else "added",
                 "sha256": hashlib.sha256(src.read_bytes()).hexdigest()})
patch = out / "native-rules-port-v4-step1.patch"
patch.write_text("".join(chunks))
with tempfile.TemporaryDirectory(prefix="sts2-step1-patch-") as temp:
    stage = Path(temp)
    for row in rows:
        old = base / row["path"]
        if old.is_file():
            dst = stage / row["path"]
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(old, dst)
    result = subprocess.run(["git", "apply", "--check", str(patch)], cwd=stage,
                            text=True, capture_output=True)
    if result.returncode: raise RuntimeError(result.stdout + result.stderr)
report = {"base_ruleset": "native-41cef1ea-port-v3", "new_ruleset": "native-41cef1ea-port-v4",
          "patch_kind": "incremental_against_step1_source_before", "files": rows,
          "patch_sha256": hashlib.sha256(patch.read_bytes()).hexdigest(),
          "patch_bytes": patch.stat().st_size, "apply_check": True,
          "excludes": ["game DLLs", "native host binaries", "weights", "root AGENTS.md"]}
(out / "changed-files.json").write_text(json.dumps(report, indent=2)+"\n")
print(json.dumps({"files": len(rows), "patch_bytes": report["patch_bytes"], "apply_check": True}))
