"""Create a reproducible M0 manifest, without running training or final evaluation."""
import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sts2_env.az.scenarios import save_manifest, starter_scenario


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="data/az/m0_manifest.json")
    parser.add_argument("--train", type=int, default=256)
    parser.add_argument("--validation", type=int, default=256)
    parser.add_argument("--test", type=int, default=150)
    args = parser.parse_args()
    if any(n < 1 for n in (args.train, args.validation, args.test)):
        parser.error("All split sizes must be positive")
    recipes = []
    seed = 0
    for split, count in (("train", args.train), ("validation", args.validation), ("test", args.test)):
        recipes.extend(starter_scenario(seed + i, split) for i in range(count))
        seed += count
    save_manifest(args.output, recipes)
    print(f"Saved {len(recipes)} recipes to {args.output}; no test outcomes were evaluated.")


if __name__ == "__main__":
    main()
