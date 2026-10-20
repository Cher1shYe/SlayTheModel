"""Build the vendored worker into an isolated directory; never install a game mod."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess


def sha_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def build(repo, game, ritsu, dotnet='dotnet'):
    repo, game, ritsu = (Path(p).resolve() for p in (repo, game, ritsu))
    if platform.machine().lower() not in ('amd64', 'x86_64'):
        raise ValueError('Only x86_64 Windows/Linux hosts are supported')
    windows = os.name == 'nt'
    if not windows and platform.system() != 'Linux':
        raise ValueError('Only Windows and Linux are supported')
    suffix = 'windows' if windows else 'linuxbsd'
    managed = game/f'data_sts2_{suffix}_x86_64'
    executable = game/('SlayTheSpire2.exe' if windows else 'SlayTheSpire2.x86_64')
    dependencies = [managed/name for name in ('sts2.dll', 'GodotSharp.dll', '0Harmony.dll')]
    dependencies += [game/'SlayTheSpire2.pck', executable, game/'release_info.json']
    dependencies += [ritsu/'compat/0.111.0'/name for name in ('STS2-RitsuLib.dll', 'STS2-RitsuLib.Runtime.dll')]
    dependencies += [ritsu/'shared'/name for name in
                     ('STS2-RitsuLib.Shared.dll', 'STS2-RitsuLib.Ui.dll', 'STS2-RitsuLib.Settings.dll')]
    missing = [str(p) for p in dependencies if not p.is_file()]
    if missing:
        raise ValueError('Missing licensed game/RitsuLib files:\n' + '\n'.join(missing))
    contract = json.loads((repo/'contracts/sts2-v0.111.0-windows.json').read_text(encoding='utf-8'))
    actual = sha_file(managed/'sts2.dll')
    if actual != contract['sha256']:
        raise ValueError(f'Unverified sts2.dll SHA256 {actual}; expected {contract["sha256"]}. '
                         'Linux assemblies are admitted only if byte-identical to the pinned ABI. '
                         'A different build requires a separate ABI/semantic audit, not a hash override.')
    stage = repo/'artifacts/native-host'
    if stage.exists():
        raise ValueError('Runtime output exists; use a new experiment directory instead of overwriting DLLs')
    output = stage/f'data_NativeWorker_{suffix}_x86_64'
    output.mkdir(parents=True)
    command = [str(dotnet), 'publish', str(repo/'tools/Sts2.NativeWorker'),
        '-c', 'ExportRelease', '-r', 'win-x64' if windows else 'linux-x64',
        '--self-contained', 'true', '-o', str(output),
        f'-p:Sts2ManagedDir={managed}', f'-p:Sts2DataDir={managed}',
        f'-p:CombatSolverRoot={repo/"combat"}', f'-p:RitsuLibRoot={ritsu}',
        f'-p:RitsuWorkshopRoot={ritsu}', f'-p:RitsuLibDir={ritsu/"compat/0.111.0"}',
        '-p:CopyModOnBuild=false', '-p:SkipMemoryCleaner=true']
    subprocess.run(command, cwd=repo, check=True)
    shutil.copy2(managed/'GodotSharp.dll', output/'GodotSharp.dll')
    shutil.copy2(executable, stage/('NativeWorker.exe' if windows else 'NativeWorker.x86_64'))
    shutil.copy2(game/'release_info.json', stage/'release_info.json')
    return {str(p): sha_file(p) for p in dependencies}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', type=Path, required=True)
    parser.add_argument('--game', type=Path, required=True)
    parser.add_argument('--ritsu', type=Path, required=True)
    parser.add_argument('--dotnet', default='dotnet')
    args = parser.parse_args()
    receipt = build(args.repo, args.game, args.ritsu, args.dotnet)
    (args.repo/'artifacts/build-inputs.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
