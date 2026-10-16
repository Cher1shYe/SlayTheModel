"""Read-only checks of the G2.3e factorial probe, including visit labels."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import numpy as np
from sts2_env.az.config import atomic_json
from sts2_env.az.network import code_digest
from sts2_env.az.search_config import VERSIONS,PRIOR,COMBINED
from sts2_env.az.self_play import file_digest


def verify():
    root=Path("output/az_search_v1_probe_v4")
    plan=json.loads((root/"plan.json").read_text())
    report=json.loads((root/"report.json").read_text())
    assert plan["code_digest"]==code_digest()
    assert plan["script_digest"]==file_digest(Path(__file__).with_name("probe_az_search_v1.py"))
    for source in plan["sources"].values():
        assert file_digest(source["final"])==source["final_sha256"]
    cases=[json.loads(p.read_text()) for p in sorted(root.glob("case-*.json"))]
    expected={(s,v,j) for s in (42,43) for v in VERSIONS for j in range(90,99)}
    assert len(cases)==72
    assert {(c["seed"],c["search_version"],int(c["recipe"]["scenario_id"].split('-')[-1])) for c in cases}==expected
    for c in cases:
        assert c["recipe"]["split"]=="train" and c["outcome"]["done"]
        assert len(c["rows"])==c["outcome"]["decisions"]
        for r in c["rows"]:
            if r["visits"]:
                assert sum(r["visits"].values())==8
                if c["search_version"] in (PRIOR,COMBINED):
                    tied=[int(a) for a,n in r["visits"].items() if n==max(r["visits"].values())]
                    assert r["action"]==max(tied,key=lambda a:(r["prior"][str(a)],-a))
        visits=np.asarray(c["initial_noisy_visits"])
        assert visits.sum()==8
        target=visits[visits>0]/8
        entropy=-sum(p*np.log(p) for p in target)/np.log(len(c["rows"][0]["visits"]))
        assert np.isclose(entropy,c["initial_label_entropy"])
    for key,recorded in report.items():
        s,v=key.split('/')
        group=[c for c in cases if c["seed"]==int(s) and c["search_version"]==v]
        group.sort(key=lambda c:int(c["recipe"]["scenario_id"].split('-')[-1]))
        expected_summary=dict(episodes=len(group),wins=sum(c["outcome"]["termination_reason"]=="win" for c in group),
            phase2=sum(any(r["phase"]>=2 for r in c["rows"]) for c in group),
            phase3=sum(any(r["phase"]==3 for r in c["rows"]) for c in group),
            mean_reward=float(np.mean([c["outcome"]["reward"] for c in group])),
            noisy_label_entropy=float(np.mean([c["initial_label_entropy"] for c in group])),
            tied=sum(r["tied"] for c in group for r in c["rows"]),
            decisions=sum(len(c["rows"]) for c in group),seconds=sum(c["seconds"] for c in group))
        assert expected_summary==recorded
    result=dict(status="passed",full_fights=72,noisy_root_probes=72,source_code_digest=code_digest(),
                timeouts=sum(c["outcome"]["termination_reason"]=="time_limit" for c in cases))
    atomic_json("docs/az_search_v1_probe_verification.json",result)
    print(result)


if __name__=="__main__":
    verify()
