"""Read-only separate reports for focused Boss and retained-distribution tests."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from analyze_az_boss import analyze, read
from sts2_env.az.boss_curriculum import profile
from sts2_env.az.evaluation import summarize, promotion_gate
from sts2_env.az.rewards import V6


def run(root="output/az_g2_boss_curriculum_v1_quick", output="docs/az_boss_curriculum_mechanism_evidence.json"):
    root=Path(root)
    output=Path(output)
    evidence=analyze(root,output)
    profiles={}
    for seed in (42,43):
        for mode in ("network","search"):
            data=read(root/f"test-{seed}-{mode}.json")
            for group in ("focused","retained"):
                old,new=([r for r in data[role] if profile(r["scenario_id"])==group] for role in ("initial","final"))
                profiles[f"{seed}/{mode}/{group}"]=dict(initial=summarize(old),final=summarize(new),
                    diagnostic_paired=promotion_gate(old,new,required_count=len(old),reward_version=V6))
    evidence["final_by_profile"]=profiles
    evidence["focused_rule_baseline"]=read(root/"baseline-boss-block-rule.json")["summary"]
    evidence["subgroup_caveat"]="Descriptive/diagnostic groups, not extra promotion gates or general-quality acceptance"
    output.write_text(json.dumps(evidence,indent=2),encoding="utf-8")


if __name__=="__main__":
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",default="output/az_g2_boss_curriculum_v1_quick")
    parser.add_argument("--output",default="docs/az_boss_curriculum_mechanism_evidence.json")
    run(**vars(parser.parse_args()))
