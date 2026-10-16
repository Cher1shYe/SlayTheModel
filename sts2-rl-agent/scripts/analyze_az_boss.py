"""Read completed Boss artifacts; no training or simulation side effects."""
from collections import Counter
import json
from pathlib import Path
from analyze_az_summon import summary


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def analyze(root=Path("output/az_g2_boss_v1_quick"), output=Path("docs/az_boss_mechanism_evidence.json")):
    if read(root / "progress.json")["stage"] != "complete":
        raise ValueError("Run is incomplete")
    schema = read(root / "encoder_schema.json")["schema"]
    indices = {name: i for i,name in enumerate(schema["numeric_features"])}
    value = lambda row,key: row["observation"]["numeric"][indices[key]]
    training, evaluations, coverage_groups = {}, {}, {}
    for seed in (42,43):
        counts = Counter()
        for path in (root / f"seed-{seed}" / "replay" / "episodes").glob("*.json"):
            episode = read(path)
            rows = episode["rows"]
            profile = "focused" if "-focus-" in rows[0]["scenario_id"] else "retained"
            group = coverage_groups.setdefault(f"{seed}/{episode['iteration']}/{profile}", Counter())
            group["episodes"] += 1
            group["decisions"] += len(rows)
            group["wins"] += rows[0]["termination_reason"] == "win"
            group["timeouts"] += rows[0]["termination_reason"] == "time_limit"
            counts["episodes"] += 1
            counts["decisions"] += len(rows)
            counts["timeouts"] += rows[0]["termination_reason"] == "time_limit"
            boss = rows[0]["encounter_id"] == "setup_test_subject_boss"
            counts["boss_episodes"] += boss
            if boss:
                group["boss_episodes"] += 1
                counts["boss_wins"] += rows[0]["termination_reason"] == "win"
                for phase in (1,2,3):
                    observed = any(round(value(r,"boss.phase/3")*3)==phase for r in rows)
                    counts[f"boss_episodes_observed_phase{phase}"] += observed
                    group[f"boss_episodes_observed_phase{phase}"] += observed
            for i,row in enumerate(rows):
                counts["boss_reviving_decisions"] += bool(value(row,"boss.reviving"))
                for token in ("BURN","WOUND","DAZED"):
                    counts[f"{token.lower()}_in_hand_decisions"] += schema["card_vocabulary"].index(token) in row["observation"]["card_ids"]
                if value(row,"pending.PURITY") or value(row,"pending.PURITY+"):
                    counts["purity_submissions"] += 1
                    if i+1 < len(rows):
                        if value(rows[i+1],"pending.PURITY") or value(rows[i+1],"pending.PURITY+"):
                            raise ValueError("Purity choice did not exit")
                        counts["purity_observed_exits"] += 1
        training[str(seed)] = dict(counts)
        for path in (root / f"seed-{seed}").glob("evaluation-*.json"):
            for mode,data in read(path)["modes"].items():
                for role in ("champion","candidate"):
                    evaluations[f"{seed}/{path.stem}/{mode}/{role}"] = summary(data[role])
        for mode in ("network","search"):
            for role,rows in read(root/f"test-{seed}-{mode}.json").items():
                if role in ("initial","final"):
                    evaluations[f"{seed}/test/{mode}/{role}"] = summary(rows)
    result = dict(training=training,evaluations=evaluations,training_by_round_profile=coverage_groups,
                  run_wall_seconds=(root/"report.json").stat().st_mtime-(root/"plan.json").stat().st_mtime,
                  caveat="Pre-decision observations only; controlled later-form tests are separate from training coverage; no general quality claim")
    Path(output).write_text(json.dumps(result,indent=2),encoding="utf-8")
    return result


if __name__ == "__main__":
    analyze()
