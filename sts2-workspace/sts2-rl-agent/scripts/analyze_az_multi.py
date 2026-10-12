"""Read-only mechanism and timeout audit of a completed G2.1 run."""
import json
from collections import Counter
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text(encoding="utf8"))


def analyze(root=Path("output/az_g2_multi_v1_quick")):
    assert read(root / "progress.json")["stage"] == "complete"
    schema = read(root / "encoder_schema.json")["schema"]
    features = {name: index for index, name in enumerate(schema["numeric_features"])}
    tokens = schema["card_vocabulary"]
    value = lambda row, key: row["observation"]["numeric"][features[key]]
    training = {}
    evaluations = {}
    for seed in (42, 43):
        counts = Counter()
        for path in (root / f"seed-{seed}" / "replay" / "episodes").glob("*.json"):
            rows = read(path)["rows"]
            counts["episodes"] += 1
            counts["decisions"] += len(rows)
            counts["timeouts"] += rows[0]["termination_reason"] == "time_limit"
            pair = rows[0]["encounter_id"] == "setup_nibbits_normal"
            counts["pair_episodes"] += pair
            for index, row in enumerate(rows):
                is_pair = bool(value(row, "enemy_slot1.present"))
                assert is_pair == pair
                normal = bool(value(row, "phase.normal"))
                counts["pair_decisions"] += is_pair
                counts["front_dead_back_alive_decisions"] += is_pair and not value(row, "enemy_slot0.alive") and bool(value(row, "enemy_slot1.alive"))
                if value(row, "pending.PURITY") or value(row, "pending.PURITY+"):
                    counts["purity_set_decisions"] += 1
                    if index + 1 < len(rows):
                        assert not (value(rows[index+1], "pending.PURITY") or value(rows[index+1], "pending.PURITY+"))
                        counts["purity_observed_completed"] += 1
                if is_pair and not normal and (value(row, "pending.HEADBUTT") or value(row, "pending.HEADBUTT+")):
                    counts["pair_headbutt_choices"] += 1
                    counts["pair_headbutt_back_target_choices"] += bool(value(row, "pending.target1"))
                action = row["chosen_action"]
                if not action or not normal or not is_pair:
                    continue
                slot = action - 1 if action <= 10 else (action - 11) // 5
                token = tokens[row["observation"]["card_ids"][slot]]
                if action > 10:
                    target = (action - 11) % 5
                    assert target in (0, 1) and value(row, f"enemy_slot{target}.alive")
                    counts[f"pair_target{target}_plays"] += 1
                    counts["back_target_after_front_death_plays"] += target == 1 and not value(row, "enemy_slot0.alive")
                if token.removesuffix("+") in ("THUNDERCLAP", "WHIRLWIND", "STOMP"):
                    counts["pair_aoe_plays." + token] += 1
        training[str(seed)] = counts
        for path in sorted((root / f"seed-{seed}").glob("evaluation-*.json")):
            data = read(path)
            for mode, report in data["modes"].items():
                for role in ("champion", "candidate"):
                    rows = report[role]
                    evaluations[f"{seed}/{path.stem}/{mode}/{role}"] = dict(
                        episodes=len(rows), timeouts=sum(r["termination_reason"] == "time_limit" for r in rows),
                        errors=sum(r["errors"] for r in rows), illegal_actions=sum(r["illegal_actions"] for r in rows))
        for mode in ("network", "search"):
            data = read(root / f"test-{seed}-{mode}.json")
            for role in ("initial", "final"):
                rows = data[role]
                pairs = [r for r in rows if r["encounter_id"] == "setup_nibbits_normal"]
                evaluations[f"{seed}/test/{mode}/{role}"] = dict(
                    episodes=len(rows), timeouts=sum(r["termination_reason"] == "time_limit" for r in rows),
                    errors=sum(r["errors"] for r in rows), illegal_actions=sum(r["illegal_actions"] for r in rows),
                    max_decisions=max(r["decisions"] for r in rows), pair_episodes=len(pairs),
                    pair_wins=sum(r["termination_reason"] == "win" for r in pairs))
    result = dict(training=training, evaluations=evaluations,
                  run_wall_seconds=(root / "report.json").stat().st_mtime - (root / "plan.json").stat().st_mtime,
                  caveat="Pre-decision observations; post-terminal mechanism events are not inferred")
    Path("docs/az_multi_mechanism_evidence.json").write_text(json.dumps(result, indent=2), encoding="utf8")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    analyze()
