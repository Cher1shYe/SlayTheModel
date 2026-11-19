"""Compare all active monster HP and attack numbers with immutable real DLL data.

The DLL samples use fresh mutable models without a Creature. Stateful attack
getters are named exceptions; their combat progression needs execution tests.
"""
from __future__ import annotations
import argparse
import ast
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
FIXTURE=Path("sim/native-fixtures/native-monster-numbers-41cef1ea")
DLL_SHA="9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4"
FILE_HASHES={
    "monster-numbers-a7.json":"604fe7d24d845a4c32aee72159832118c960824bff04ee23c4d41f5486c07212",
    "monster-numbers-a8.json":"35172103711fd69d077883954272473965de8d051fe37a541a031c8927aea320",
    "monster-numbers-a9.json":"17fc803d0c733fb65f1240856ae7f375e0ff023e91a9125e68354ed1e1d5f6f2",
    "monster-numbers-a10.json":"ee17dfb9a25bb2d911e1f1d788a44860122d8738fb1231dfafc0a5aaf81ea666",
}
RETAINED_MOVES={"AXEBOT.SHARPEN_MOVE","CUBEX_CONSTRUCT.SUBMERGE_MOVE",
                "HAUNTED_SHIP.RAMMING_SPEED_MOVE","TEST_SUBJECT.POUNCE_MOVE"}


def content(root):
    root=Path(root)
    models=json.loads((root/"sim/content/monsters.json").read_text())["monsters"]
    # Read the generator's literal late entry, never run a generator/mutate files.
    tree=ast.parse((root/"sim/tools/gen_monsters.py").read_text())
    nodes=[node for node in ast.walk(tree) if isinstance(node,ast.Assign) and
           any(isinstance(target,ast.Name) and target.id=="late_monsters" for target in node.targets)]
    if len(nodes)!=1:raise ValueError("late monster declarations require review")
    late=ast.literal_eval(nodes[0].value)
    if set(models)&set(late):raise ValueError("duplicate late monster identity")
    models.update(late)
    damage=json.loads((root/"sim/content/monsters_a9_damage.json").read_text())
    # Same explicit late-Aeonglass declaration from gen_monsters; require its shape.
    updates=[node for node in ast.walk(tree) if isinstance(node,ast.Call) and
        isinstance(node.func,ast.Attribute) and node.func.attr=="update" and
        isinstance(node.func.value,ast.Call) and isinstance(node.func.value.func,ast.Attribute) and
        isinstance(node.func.value.func.value,ast.Name) and node.func.value.func.value.id=="deadly_damage"]
    for node in updates:
        key=ast.literal_eval(node.func.value.args[0])
        damage.setdefault(key,{}).update(ast.literal_eval(node.args[0]))
    hits=json.loads((root/"sim/content/monsters_a9_hits.json").read_text())
    return models,damage,hits


def audit(root=ROOT):
    root=Path(root)
    manifest=json.loads((root/FIXTURE/"manifest.json").read_text())
    differences=[];checks=[];exceptions=[]
    def check(name,actual,expected,**context):
        item={"field":name,**context,"simulator":actual,"native":expected,"matched":actual==expected}
        checks.append(item)
        if not item["matched"]:differences.append(item)
    check("manifest.file_hashes",manifest.get("files"),FILE_HASHES)
    check("manifest.dll_sha256",manifest.get("gameDllSha256"),DLL_SHA)
    archives={}
    for filename,expected in FILE_HASHES.items():
        raw=(root/FIXTURE/filename).read_bytes()
        check("fixture.sha256",hashlib.sha256(raw).hexdigest(),expected,file=filename)
        archive=json.loads(raw)
        check("fixture.dll_sha256",archive.get("gameDllSha256"),DLL_SHA,file=filename)
        archives[filename]=archive
    before=archives["monster-numbers-a7.json"]["beforeRun"]
    digest=lambda value:hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    for filename,archive in archives.items():
        check("before_run_a0_repeat_sha256",digest(archive["beforeRun"]),digest(before),file=filename)
    contexts=[before]+[archives[f"monster-numbers-a{a}.json"]["run"] for a in (7,8,9,10)]
    check("ascension_contexts",[row["ascension"] for row in contexts],[0,7,8,9,10])
    models,deadly_damage,deadly_hits=content(root)
    registry=json.loads((root/"sim/native-fixtures/native-registry-41cef1ea.json").read_text())
    expected_ids=sorted(row["id"] for row in registry["monsters"])
    number_checks=0;move_instances=0;attack_instances=0;seen_retained=set()
    def member(row,suffix):
        matches=[v for k,v in row["members"].items() if k.endswith("."+suffix)]
        if len(matches)!=1:raise ValueError(f"{row['id']}.{suffix}: expected one inherited numeric member")
        return matches[0]
    for context in contexts:
        asc=context["ascension"]
        check("active_registry",sorted(row["id"] for row in context["monsters"]),expected_ids,ascension=asc)
        for row in context["monsters"]:
            identity=row["id"]
            key="DECIMILLIPEDE_SEGMENT" if identity.startswith("DECIMILLIPEDE_SEGMENT_") else identity
            model=models.get(key)
            if model is None:
                check("model_mapping",None,key,id=identity,ascension=asc);continue
            for index,label in enumerate(("MinInitialHp","MaxInitialHp")):
                check("hp."+label,model["hp"]["A8" if asc>=8 else "A0"][index],member(row,label),id=identity,ascension=asc)
                number_checks+=1
            states=model.get("states8",model["states"]) if asc>=8 else model["states"]
            native_states={move["id"] for move in row["moves"]}
            for state,definition in states.items():
                if definition["kind"]=="move" and state not in native_states:
                    seen_retained.add(key+"."+state)
            for move in row["moves"]:
                state=move["id"];move_instances+=1
                if state not in states:
                    check("move_mapping",None,state,id=identity,ascension=asc);continue
                ours=[intent for intent in states[state].get("intents",[]) if intent["type"] in ("ATTACK","MULTI_ATTACK","DEATH_BLOW")]
                native=[intent for intent in move["intents"] if intent["type"] in ("SingleAttackIntent","MultiAttackIntent","DeathBlowIntent")]
                check("attack_intent_count",len(ours),len(native),id=identity,move=state,ascension=asc)
                for i,(ours_intent,native_intent) in enumerate(zip(ours,native)):
                    attack_instances+=1
                    damage=deadly_damage.get(key,{}).get(state,ours_intent["damage"]) if asc>=9 else ours_intent["damage"]
                    hits=deadly_hits.get(key,{}).get(state,ours_intent["hits"]) if asc>=9 else ours_intent["hits"]
                    check("attack.hits",hits,native_intent["hits"],id=identity,move=state,ascension=asc,intent=i);number_checks+=1
                    expected=native_intent["damage"]
                    if identity=="THE_FORGOTTEN" and state=="DREAD" and isinstance(expected,dict) and expected.get("error")=="InvalidOperationException":
                        exceptions.append({"id":identity,"move":state,"ascension":asc,"field":"damage",
                            "reason":"Native getter needs Creature/target Dexterity; raw failure retained; execution tested separately."})
                        continue
                    if identity=="WATERFALL_GIANT" and state=="PRESSURE_GUN_MOVE":
                        exceptions.append({"id":identity,"move":state,"ascension":asc,"field":"fresh_intent_damage",
                            "native":expected,"simulator_table":damage,"reason":"Fresh unattached DLL model has CurrentPressureGunDamage=0. Simulator table is base damage; runtime uses evolving aux[2]."})
                        check("fresh_pressure_damage",expected,0,id=identity,ascension=asc)
                        expected=member(row,"BasePressureGunDamage")
                    check("attack.damage",damage,expected,id=identity,move=state,ascension=asc,intent=i);number_checks+=1
    check("retained_inactive_moves",sorted(seen_retained),sorted(RETAINED_MOVES))
    return {"schema":"sts2.monster-number-audit/1","status":"pass_with_documented_dynamic_exceptions" if not differences else "fail",
            "scope":"Real DLL fresh-model base HP and every attack intent damage/hit count; no claim of complete battle execution parity",
            "dll_sha256":DLL_SHA,"fixture":str(FIXTURE),"ascensions":[0,7,8,9,10],
            "counts":{"active_native_models":len(expected_ids),"model_contexts":sum(len(c["monsters"]) for c in contexts),
                "move_contexts":move_instances,"attack_contexts":attack_instances,"numeric_comparisons":number_checks,
                "all_checks":len(checks),"unexplained_differences":len(differences)},
            "differences":differences,"exceptions":exceptions,"retained_inactive_moves":sorted(seen_retained),
            "dynamic_boundaries":["Axebot respawn HP and Strength", "TestSubject MultiClaw growth and later HP forms",
                "Waterfall Giant CurrentPressureGunDamage/SteamEruptionDamage","TheForgotten target-Dexterity damage",
                "Aeonglass growing Strength, Wither upgrades/count; buff/debuff/block/summon/status execution"],
            "checks":checks}


if __name__=="__main__":
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument("--out",type=Path);args=parser.parse_args()
    result=audit()
    if args.out:args.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({key:result[key] for key in ("status","counts","differences")},ensure_ascii=False,indent=2))
    raise SystemExit(bool(result["differences"]))
