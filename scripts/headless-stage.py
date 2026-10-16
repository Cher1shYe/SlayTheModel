#!/usr/bin/env python3
"""Stage the user's installed game runtime without modifying the game installation."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import struct


def copy_native_caches(pack, runtime_project):
    """Keep native global script names and resource UIDs available at engine startup."""
    wanted = {".godot/global_script_class_cache.cfg", ".godot/uid_cache.bin"}
    with pack.open("rb") as stream:
        if stream.read(4) != b"GDPC":
            raise ValueError("The installed game pack has an unexpected header.")
        version = struct.unpack("<I", stream.read(4))[0]
        if version != 3:
            raise ValueError(f"Expected the pinned game's PCK version 3, got {version}.")
        stream.seek(24)
        base, directory = struct.unpack("<QQ", stream.read(16))
        stream.seek(directory)
        count = struct.unpack("<I", stream.read(4))[0]
        entries = []
        for _ in range(count):
            size = struct.unpack("<I", stream.read(4))[0]
            path = stream.read(size).rstrip(b"\0").decode("utf-8")
            offset, length = struct.unpack("<QQ", stream.read(16))
            stream.read(16)  # Original MD5 entry; the whole pack remains unchanged.
            flags = struct.unpack("<I", stream.read(4))[0]
            if path in wanted:
                if flags:
                    raise ValueError(f"Unsupported compressed/encrypted native cache: {path}")
                entries.append((path, base + offset, length))
        for path, offset, length in entries:
            stream.seek(offset)
            (runtime_project / path).write_bytes(stream.read(length))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--game", required=True, type=Path)
    parser.add_argument("--platform", choices=("macos", "windows"), required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parent.parent
    project = repo / "tools/Sts2.HeadlessHost"
    stage = repo / "artifacts/headless"
    runtime_project = stage / "project"
    runtime_project.mkdir(parents=True, exist_ok=True)
    if args.platform == "macos":
        source = args.game / "Contents/Resources/data_sts2_macos_arm64"
        pack = args.game / "Contents/Resources/Slay the Spire 2.pck"
        app = stage / "HeadlessHost.app/Contents"
        target = app / "Resources/data_HeadlessHost_macos_arm64"
        target.mkdir(parents=True, exist_ok=True)
        (app / "MacOS").mkdir(parents=True, exist_ok=True)
        exe = app / "MacOS/HeadlessHost"
        shutil.copy2(args.game / "Contents/MacOS/Slay the Spire 2", exe)
        shutil.copytree(args.game / "Contents/Frameworks", app / "Frameworks", dirs_exist_ok=True)
        with (args.game / "Contents/Info.plist").open("rb") as stream:
            info = plistlib.load(stream)
        info.update(CFBundleExecutable="HeadlessHost", CFBundleIdentifier="dev.slaythemodel.HeadlessHost")
        with (app / "Info.plist").open("wb") as stream:
            plistlib.dump(info, stream)
        shutil.copy2(args.game / "Contents/Resources/release_info.json", app / "Resources/release_info.json")
    else:
        source = args.game / "data_sts2_windows_x86_64"
        pack = args.game / "SlayTheSpire2.pck"
        target = stage / "data_HeadlessHost_windows_x86_64"
        exe = stage / "HeadlessHost.exe"
        shutil.copy2(args.game / "SlayTheSpire2.exe", exe)
        for path in args.game.iterdir():
            if path.is_file() and path.suffix.lower() in (".dll", ".json"):
                shutil.copy2(path, stage / path.name)
    shutil.copytree(source, target, dirs_exist_ok=True)
    build = project / ".godot/mono/temp/bin/ExportRelease"
    for path in build.iterdir():
        if path.suffix in (".dll", ".pdb") and path.name not in ("GodotSharp.dll", "sts2.dll", "0Harmony.dll"):
            shutil.copy2(path, target / path.name)
    with (source / "sts2.deps.json").open() as stream:
        deps = json.load(stream)
    with (build / "HeadlessHost.deps.json").open() as stream:
        host = json.load(stream)
    deps["targets"][deps["runtimeTarget"]["name"]].update(
        {k: v for k, v in host["targets"][host["runtimeTarget"]["name"]].items() if k.startswith("HeadlessHost/")})
    deps["libraries"].update({k: v for k, v in host["libraries"].items() if k.startswith("HeadlessHost/")})
    (target / "HeadlessHost.deps.json").write_text(json.dumps(deps))
    shutil.copy2(source / "sts2.runtimeconfig.json", target / "HeadlessHost.runtimeconfig.json")
    for name in ("Host.cs", "Host.tscn"):
        shutil.copy2(project / name, runtime_project / name)
    config = (project / "project.godot").read_text()
    (runtime_project / "project.godot").write_text(config)
    (runtime_project / ".godot").mkdir(exist_ok=True)
    (runtime_project / ".godot/global_script_class_cache.cfg").write_text("list=Array[Dictionary]([])\n")
    copy_native_caches(pack, runtime_project)
    if args.platform == "macos":
        libs = app / "Frameworks"
        extensions = {
            "fmod": ("fmod_library_init", libs / "libGodotFmod.macos.template_release.framework"),
            "spine": ("spine_godot_library_init", libs / "libspine_godot.macos.template_release.framework"),
        }
        feature = "macos"
    else:
        extensions = {
            "fmod": ("fmod_library_init", stage / "libGodotFmod.windows.template_release.x86_64.dll"),
            "spine": ("spine_godot_library_init", stage / "libspine_godot.windows.template_release.x86_64.dll"),
        }
        feature = "windows.x86_64"
    for name, (entry, library) in extensions.items():
        (runtime_project / f"native_{name}.gdextension").write_text(
            f'[configuration]\nentry_symbol="{entry}"\ncompatibility_minimum="4.5"\n\n'
            f'[libraries]\n{feature}={json.dumps(str(library).replace(chr(92), "/"))}\n')
    (runtime_project / ".godot/extension_list.cfg").write_text(
        "res://native_fmod.gdextension\nres://native_spine.gdextension\n")
    print(f"Staged isolated headless runtime: {exe}")


if __name__ == "__main__":
    main()
