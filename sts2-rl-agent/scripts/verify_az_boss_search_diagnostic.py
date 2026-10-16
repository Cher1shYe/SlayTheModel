"""Read-only provenance, completeness and statistic checks for G2.3d."""
import argparse
import json
from pathlib import Path
import numpy as np
from diagnose_az_boss_search import summarize, generate, code_digest, file_digest, atomic_json


def verify(directory, output):
    root=Path(directory)
    plan=json.loads((root/"plan.json").read_text())
    if plan["split"]!="train" or plan["code_digest"]!=code_digest():
        raise ValueError("Wrong split or changed engine")
    if plan["script_digest"]!=file_digest(Path(__file__).with_name("diagnose_az_boss_search.py")):
        raise ValueError("Diagnostic source changed")
    for seed in plan["seeds"]:
        source=plan["sources"][str(seed)]
        if file_digest(source["final"])!=source["final_sha256"]:
            raise ValueError("Source checkpoint changed")
    recipes=plan["recipes"]
    canonical_recipes=json.loads(json.dumps([generate(48,0,j).to_dict() for j in range(90,90+len(recipes))]))
    if recipes!=canonical_recipes:
        raise ValueError("Diagnostic recipes changed")
    expected={(s,m,r["scenario_id"]) for s in plan["seeds"] for m in plan["modes"] for r in recipes}
    seen=set()
    cases=[]
    hashes={}
    for path in sorted(root.glob("case-*.json")):
        case=json.loads(path.read_text())
        key=(case["seed"],case["mode"],case["recipe"]["scenario_id"])
        if key not in expected or key in seen or case["recipe"] not in recipes:
            raise ValueError("Unexpected/duplicate case")
        if not case["outcome"]["done"] or len(case["rows"])!=case["outcome"]["decisions"]:
            raise ValueError("Incomplete episode")
        for step,row in enumerate(case["rows"]):
            if row["step"]!=step or not 1<=row["phase"]<=3:
                raise ValueError("Invalid diagnostic row")
            edges=row.get("edges",[])
            if edges:
                if row["action"] not in {e["action"] for e in edges}:
                    raise ValueError("Chosen search action outside legal edges")
                budget=32 if case["mode"]=="search32" else 8
                if sum(e["visits"] for e in edges)!=budget:
                    raise ValueError("Visit budget mismatch")
        seen.add(key)
        cases.append(case)
        hashes[path.name]=file_digest(path)
    if seen!=expected:
        raise ValueError("Missing diagnostic cases")
    recorded=json.loads((root/"report.json").read_text())
    # Preserve original execution order for floating-point reductions.
    order={(s,m,r["scenario_id"]):i for i,(s,m,r) in enumerate(
        (s,m,r) for s in plan["seeds"] for m in plan["modes"] for r in recipes)}
    cases.sort(key=lambda c:order[(c["seed"],c["mode"],c["recipe"]["scenario_id"])])
    if summarize(cases)!=recorded:
        raise ValueError("Recorded summary differs from raw evidence")
    labels_path=Path("output/az_boss_label_diagnostic_v1.json")
    labels=json.loads(labels_path.read_text())
    if (labels["source_plan_sha256"]!=file_digest(root/"plan.json") or
            labels["script_sha256"]!=file_digest(Path(__file__).with_name("diagnose_az_boss_labels.py")) or
            labels["code_digest"]!=plan["code_digest"]):
        raise ValueError("Label probe provenance changed")
    label_expected={(s,r["scenario_id"],t) for s in plan["seeds"] for r in recipes for t in (False,True)}
    label_seen=set()
    for row in labels["rows"]:
        key=(row["seed"],row["scenario_id"],row["training"])
        if key not in label_expected or key in label_seen:
            raise ValueError("Unexpected label case")
        visits=np.asarray(row["visits"])
        target=np.asarray(row["target"])
        entropy=-sum(p*np.log(p) for p in target if p>0)/np.log(len(row["legal"]))
        if (visits.sum()!=8 or not np.array_equal(target,visits/8) or
                not np.isclose(entropy,row["target_normalized_entropy"]) or
                row["chosen_action"] not in row["legal"]):
            raise ValueError("Invalid label evidence")
        label_seen.add(key)
    if label_seen!=label_expected:
        raise ValueError("Missing label cases")
    for seed in plan["seeds"]:
        for noisy in (False,True):
            group=[r for r in labels["rows"] if r["seed"]==seed and r["training"]==noisy]
            expected_summary=dict(count=len(group),
                mean_normalized_entropy=float(np.mean([r["target_normalized_entropy"] for r in group])),
                tied_max=sum(r["tied_max"] for r in group))
            if labels["summary"][str(seed)][str(noisy)]!=expected_summary:
                raise ValueError("Label summary mismatch")
    result=dict(status="passed",cases=len(cases),source_sha256=hashes,
                label_probes=len(label_seen),label_sha256=file_digest(labels_path),
                engine_unchanged=True,weights_unchanged=True,training_started=False,
                final_test_read=False,limitations=["Recomputes with same summary implementation",
                "Does not rerun combat", "Training-only small diagnostic; not quality acceptance"])
    atomic_json(output,result)
    print(json.dumps({k:v for k,v in result.items() if k!="source_sha256"},indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory",default="output/az_boss_search_diagnostic_v1")
    parser.add_argument("--output",default="docs/az_boss_search_diagnostic_verification.json")
    verify(**vars(parser.parse_args()))
