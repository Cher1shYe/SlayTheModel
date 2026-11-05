import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "simulator"


def test_relic_raw_rarity_generated_table_is_current():
    spec = importlib.util.spec_from_file_location("gen_relic_raw_rarity", ROOT / "tools/gen_relic_raw_rarity.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    rows = json.loads((ROOT / "content/relics.json").read_text(encoding="utf-8"))
    assert (ROOT / "include/sts2/relic_raw_rarity.h").read_text(encoding="utf-8") == module.render(rows)
