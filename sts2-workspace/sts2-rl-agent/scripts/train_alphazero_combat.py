"""Run or resume synchronous observable AlphaZero training (JSON configuration)."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sts2_env.az.coordinator import Coordinator, TrainingConfig

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/alphazero_combat.json")
    parser.add_argument("--manifest", default="data/az/hp_v2_manifest.json")
    parser.add_argument("--output", default="output/az_hp_v2_combat")
    parser.add_argument("--resume")
    args = parser.parse_args()
    if args.resume:
        coordinator = Coordinator(args.resume)
    else:
        config = TrainingConfig(**json.loads(Path(args.config).read_text(encoding="utf-8")))
        coordinator = Coordinator(args.output, args.manifest, config)
    coordinator.run()
