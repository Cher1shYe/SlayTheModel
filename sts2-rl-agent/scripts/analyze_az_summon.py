"""Read completed frozen artifacts; write counts for the read-only observer."""
from collections import Counter
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf8"))


def analyze(root=Path("output/az_g2_summon_v1_quick")):
    assert read(root / "progress.json")["stage"] == "complete"
    schema = read(root / "encoder_schema.json")["schema"]
    indices = {key: i for i, key in enumerate(schema["numeric_features"])}
    value = lambda row, key: row["observation"]["numeric"][indices[key]]
    training, evaluations = {}, {}
    for seed in (42, 43):
        counts = Counter()
        for path in (root / f"seed-{seed}" / "replay" / "episodes").glob("*.json"):
            rows = read(path)["rows"]
            fogmog = rows[0]["encounter_id"] == "setup_fogmog_normal"
            counts["episodes"] += 1
            counts["decisions"] += len(rows)
            counts["fogmog_episodes"] += fogmog
            counts["timeouts"] += rows[0]["termination_reason"] == "time_limit"
            if fogmog:
                counts["observed_dazed_generated"] += round(max(value(r, "generated.DAZED/400") for r in rows)*400)
                counts["episodes_with_observed_summon"] += any(value(r, "summon_slot1.spawned") for r in rows)
                counts["episodes_with_observed_revival"] += any(
                    value(a,"summon_slot1.reviving") and value(b,"summon_slot1.alive")
                    for a,b in zip(rows,rows[1:]))
            for i,row in enumerate(rows):
                counts["fogmog_decisions"] += fogmog
                counts["eye_reviving_decisions"] += fogmog and bool(value(row,"summon_slot1.reviving"))
                counts["dazed_in_hand_decisions"] += schema["card_vocabulary"].index("DAZED") in row["observation"]["card_ids"]
                if value(row,"pending.PURITY") or value(row,"pending.PURITY+"):
                    counts["purity_submissions"] += 1
                    if i+1 < len(rows):
                        assert not value(rows[i+1],"pending.PURITY") and not value(rows[i+1],"pending.PURITY+")
                        counts["purity_observed_exits"] += 1
                action=row["chosen_action"]
                if action>10 and value(row,"phase.normal") and fogmog:
                    target=(action-11)%5
                    assert target in (0,1) and value(row,f"summon_slot{target}.alive")
                    assert not value(row,f"summon_slot{target}.reviving")
                    counts[f"fogmog_target{target}_plays"] += 1
        training[str(seed)] = dict(counts)
        paths = list((root/f"seed-{seed}").glob("evaluation-*.json"))
        for path in paths:
            for mode,data in read(path)["modes"].items():
                for role in ("champion","candidate"):
                    evaluations[f"{seed}/{path.stem}/{mode}/{role}"] = summary(data[role])
        for mode in ("network","search"):
            for role,rows in read(root/f"test-{seed}-{mode}.json").items():
                if role in ("initial","final"):
                    evaluations[f"{seed}/test/{mode}/{role}"] = summary(rows)
    result=dict(training=training,evaluations=evaluations,
                run_wall_seconds=(root/"report.json").stat().st_mtime-(root/"plan.json").stat().st_mtime,
                caveat="Observed pre-decision states; no inference of unobserved terminal events; same-family test")
    output=Path("docs/az_summon_mechanism_evidence.json")
    output.write_text(json.dumps(result,indent=2),encoding="utf8")
    return result


def summary(rows):
    return dict(episodes=len(rows),timeouts=sum(r["termination_reason"]=="time_limit" for r in rows),
                errors=sum(r["errors"] for r in rows),illegal_actions=sum(r["illegal_actions"] for r in rows),
                max_decisions=max(r["decisions"] for r in rows),
                encounters={name:dict(episodes=len(group),wins=sum(r["termination_reason"]=="win" for r in group))
                    for name in sorted({r["encounter_id"] for r in rows})
                    for group in [[r for r in rows if r["encounter_id"]==name]]},
                timeout_cases=[{k:r[k] for k in ("scenario_id","encounter_id","turns","decisions","final_hp","enemy_final_hp")}
                               for r in rows if r["termination_reason"]=="time_limit"])


if __name__ == "__main__":
    analyze()
