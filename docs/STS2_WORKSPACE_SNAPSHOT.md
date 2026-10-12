# Local workspace source snapshot

Imported from the current local workspace on 2026-10-12, based on the target
repository's alphazero branch. 4014 source/config/document/fixture files
were copied into sts2-workspace/; the existing target modules were retained.

## Included

- sts2-cli/: headless engine adapters, localization, Python interfaces and tests.
- sts2-rl-agent/: simulator, MCTS/AlphaZero implementation, configs, fixture
  manifests, experiment documentation and tests, including uncommitted local code.
- Top-level driver/probe sources and scripts/delegate_claude.py with its tests.
- The delegation role and acceptance rules in sts2-workspace/AGENTS.md.

## Import boundaries

Git metadata, local Claude configuration, .handoffs, virtual environments,
caches, build outputs, game assemblies and trained model/archive outputs are
excluded. Personal workspace/user-home paths in 4 files were
replaced with <workspace>/<user-home> placeholders only in this publication copy.
No local source files or original repository branches/remotes were changed.

## Verification

Source files were checked against a copy manifest. The delegation boundary tests
were run from the publication copy. This is a source snapshot; no full simulator,
training or game runtime regression is claimed by this import.

Run the delegate from sts2-workspace/, for example:

```powershell
python scripts/delegate_claude.py path/to/task.md --cwd sts2-rl-agent
```
