"""Shared actor contract: actual simulator states, public metadata and NoSL.

Synthetic transport rewrites below test encoding/routing, not native game parity.
Native execution parity is checked by parity.compare against recorded host frames.
"""
from copy import deepcopy
import json

import numpy as np
import pytest
import torch

from spire_rl.sim import sim
from spire_rl import public_obs as p
from spire_rl.net import UnifiedNet, UnifiedNetConfig, collate, save, load
from parity.semantic import project_simulator


def initial():
    rc=sim.RunContext();rc.init_seed("PARITY0001",10)
    return rc


def combat():
    rc=initial()
    for _ in range(12):
        if rc.screen==sim.RunScreen.COMBAT:return rc
        state=p.from_simulator(rc)
        preferred=next((i for i,a in enumerate(state.actions) if a.key.kind=="neow_relic" and a.key.args[0]=="GOLDEN_PEARL"),0)
        assert p.step_simulator(rc,state,preferred)
    raise AssertionError("deterministic opening did not enter combat")


def equal_encoding(a,b):
    assert a.in_combat==b.in_combat and a.n_ctx==b.n_ctx
    for field in ("kind","id","num","edges","global_row","player_row","cand_type","cand_index","cand_t1","cand_t2","cand_num"):
        np.testing.assert_array_equal(getattr(a,field),getattr(b,field),err_msg=field)


def test_actual_simulator_public_state_encodes_all_decisions_to_first_combat():
    rc=combat();state=p.from_simulator(rc);obs=p.encode(state)
    assert obs.schema_id==p.SCHEMA_ID and obs.in_combat
    assert len(state.actions)==len(obs.cand_type)>1
    assert any(c["pile"]=="hand" for c in state.facts["cards"])
    assert state.facts["enemies"]
    assert p.differences(state,p.from_simulator(rc.clone()))==[]


def test_actual_hidden_rng_and_draw_resampling_preserve_actor_input():
    rc=combat();before=p.from_simulator(rc);encoded=p.encode(before)
    original_draw=list(rc.battle.draw);different=False
    for seed in range(1,8):
        copy=rc.clone();copy.battle.resample_hidden(seed)
        different|=list(copy.battle.draw)!=original_draw
        state=p.from_simulator(copy)
        assert p.differences(before,state)==[]
        equal_encoding(encoded,p.encode(state))
    assert different,"test must really change the hidden draw order"


def test_transport_ids_unknown_payload_and_unordered_piles_are_not_features():
    rc=combat();projection=project_simulator(rc,sim);raw=sim.public_model_state(rc)
    before=p._common(raw,projection,"simulator")
    altered=deepcopy(raw);altered["seed"]="hidden";altered["rng"]=[999];altered["hiddenDrawOrder"]=[4,3,2,1]
    altered["run"]["futureActs"]=["UNKNOWN"]
    for card in altered["cards"]:card["transportId"]="renamed-"+card["transportId"]
    for card in altered["knownTop"]:card["transportId"]="renamed-"+card["transportId"]
    altered["cards"].reverse()
    after=p._common(altered,projection,"simulator")
    assert p.differences(before,after)==[]
    equal_encoding(p.encode(before),p.encode(after))


def test_missing_fields_fail_with_path_instead_of_zero():
    rc=initial();raw=sim.public_model_state(rc);del raw["cards"][0]["bonusDamage"]
    raw["eventPage"]=sim.event_page_key(rc)
    with pytest.raises(p.ObservationCoverageError,match=r"simulator.cards\[0\].bonusDamage"):
        p._common(raw,project_simulator(rc,sim),"simulator")


def test_visible_dynamic_vars_temporary_keywords_and_slot_change_features():
    rc=combat();state=p.from_simulator(rc);original=p.encode(state)
    for field in ("retainThisTurn","slyThisTurn","dampened"):
        modified=deepcopy(state);card=next(c for c in modified.facts["cards"] if c["pile"]=="hand")
        card[field]=not card[field]
        assert not np.array_equal(original.num,p.encode(modified).num),field
    modified=deepcopy(state);card=next(c for c in modified.facts["cards"] if c["dynamicVars"])
    name,value=card["dynamicVars"][0];card["dynamicVars"]=((name,value+1),)+card["dynamicVars"][1:]
    assert not np.array_equal(original.num,p.encode(modified).num)
    modified=deepcopy(state);modified.facts["enemies"][0]["slotName"]="different-visible-slot"
    assert not np.array_equal(original.num,p.encode(modified).num)


def test_same_public_network_batch_and_checkpoint(tmp_path):
    torch.set_num_threads(1)
    state=p.from_simulator(combat());native=deepcopy(state);native.source="native"
    a,b=p.encode(state),p.encode(native);equal_encoding(a,b)
    cfg=UnifiedNetConfig(dim=32,ctx_layers=1,combat_layers=1,heads=4,observation_schema=p.SCHEMA_ID)
    net=UnifiedNet(cfg).eval();batch=collate([a,b])
    with torch.no_grad():output=net(batch)
    torch.testing.assert_close(output["logp"][0],output["logp"][1],rtol=0,atol=0)
    assert torch.isfinite(output["logp"]).all()
    with pytest.raises(ValueError,match="live visible"):
        net(batch,ctx=net.encode_context(batch))
    path=tmp_path/"public.pt";save(path,net);restored=load(path)
    with torch.no_grad():torch.testing.assert_close(output["logp"],restored(batch)["logp"])


def test_full_differences_are_json_serializable_and_candidate_indices_are_checked():
    state=p.from_simulator(initial());other=deepcopy(state);other.facts["player"]["gold"]+=1
    assert "public.player.gold" in json.dumps(p.differences(state,other))
    other.actions=other.actions[:-1]
    json.dumps(p.differences(state,other))
    with pytest.raises(IndexError):p.candidate_handle(state,-1)


def test_old_native_subset_cannot_be_claimed_as_full_observation():
    with pytest.raises(p.ObservationCoverageError,match="publicObservation"):
        p.from_native({},projection=project_simulator(initial(),sim))


def test_observation_caches_match_uncached_results_and_keep_types_exact():
    """Speed caches (2026-11-18) must not change facts or tensors and must hand out copies."""
    from parity.semantic import SimulatorCatalog, _REPO_ROOT
    rc=combat();raw=sim.public_model_state(rc);raw["eventPage"]=None
    projection=project_simulator(rc,sim)
    p._CARD_CACHE.clear();p._ROW_CACHE.clear()
    cold_state=p._common(deepcopy(raw),projection,"simulator");cold=p.encode(cold_state)
    warm_state=p._common(deepcopy(raw),projection,"simulator");warm=p.encode(warm_state)
    assert p._CARD_CACHE and p._ROW_CACHE,"second pass must actually use the caches"
    assert p.differences(cold_state,warm_state)==[] and repr(cold_state.facts)==repr(warm_state.facts)
    equal_encoding(cold,warm)
    for i,card in enumerate(raw["cards"]):
        assert p._card_cached(card,"simulator","x")[0]==p._card(card,"simulator","x")
    # Returned cards are copies: mutating one (as _common does for knownTop/choices) cannot leak.
    first=p._card_cached(raw["cards"][0],"simulator","x")[0];first["knownTopPosition"]=7
    assert p._card_cached(raw["cards"][0],"simulator","x")[0]["knownTopPosition"]==-1
    # bool and int are equal in Python but encode differently (x/1 vs x/10): keys must differ.
    as_bool=dict(raw["cards"][0],retain=True);as_int=dict(raw["cards"][0],retain=1)
    card_bool=p._card_cached(as_bool,"simulator","x")[0];card_int=p._card_cached(as_int,"simulator","x")[0]
    assert type(card_bool["retain"]) is bool and type(card_int["retain"]) is int
    row_bool=np.zeros(p.NUM,np.float32);row_int=np.zeros(p.NUM,np.float32)
    p._card_row(card_bool,row_bool);p._card_row(card_int,row_int)
    reference=np.zeros(p.NUM,np.float32);p._fill_card_row(card_int,reference)
    np.testing.assert_array_equal(row_int,reference)
    assert not np.array_equal(row_bool,row_int)
    # The parsed simulator card catalog is reused but identical to a fresh parse.
    assert SimulatorCatalog.from_repo() is SimulatorCatalog.from_repo()
    assert SimulatorCatalog.from_repo().cards==SimulatorCatalog._parse(_REPO_ROOT).cards


def test_v16_ancient_enchantments_are_public_and_use_appended_feature_slots():
    """Nutritious Soup / Pael's Claw enchantments: visible cost, keywords and one-hot slots 238+."""
    import json
    from pathlib import Path
    lock = json.loads((Path(__file__).resolve().parents[2] / "sim/content/registry_identity_lock.json").read_text())
    relic = {e["key"]: e["id"] for e in lock["categories"]["RELIC"]}
    rc = initial()
    assert rc.add_relic(relic["NUTRITIOUS_SOUP"]) and rc.add_relic(relic["PAELS_CLAW"])
    state = p.from_simulator(rc)
    deck = [c for c in state.facts["cards"] if c["pile"] == "deck"]
    strikes = [c for c in deck if c["modelId"] == "CARD.STRIKE_IRONCLAD"]
    defends = [c for c in deck if c["modelId"] == "CARD.DEFEND_IRONCLAD"]
    assert strikes and defends
    for c in strikes:
        assert c["enchantment"][0] == "ENCHANTMENT.TEZCATARAS_EMBER"
        assert c["cost"] == 0 and c["baseCost"] == 0 and "Eternal" in c["keywords"]
    for c in defends:
        assert c["enchantment"][:2] == ("ENCHANTMENT.GOOPY", 1) and "Exhaust" in c["keywords"]
    obs = p.encode(state)
    rows = [obs.num[i] for i in range(len(obs.kind)) if int(obs.kind[i]) == 2]  # deck cards
    ember = p.ENCHANTMENTS.index("TEZCATARAS_EMBER")
    goopy = p.ENCHANTMENTS.index("GOOPY")
    assert p._enchantment_offset(ember) == 240 and p._enchantment_offset(goopy) == 238
    assert p._enchantment_offset(p.ENCHANTMENTS.index("ROYALLY_APPROVED")) == 74  # old slots unchanged
    assert sum(int(r[240]) for r in rows) == len(strikes) and sum(int(r[238]) for r in rows) == len(defends)
    assert all(r[56:75].sum() == 0 for r in rows)  # no collision with the original one-hot block


def test_v18_fur_coat_marks_are_public_map_quests_in_appended_slot():
    """Fur Coat's 8 marked Monster/Elite points: MapPoint.Quests -> map row slot 17 (16 = Spoils Map)."""
    import json
    from pathlib import Path
    lock = json.loads((Path(__file__).resolve().parents[2] / "sim/content/registry_identity_lock.json").read_text())
    relic = {e["key"]: e["id"] for e in lock["categories"]["RELIC"]}
    rc = initial()
    before = p.encode(p.from_simulator(rc))
    assert rc.add_relic(relic["FUR_COAT"])
    state = p.from_simulator(rc)
    marked = [pt for pt in state.facts["map"] if "RELIC.FUR_COAT" in pt["quests"]]
    assert len(marked) == 8 and all(pt["type"] in ("Monster", "Elite") for pt in marked)
    obs = p.encode(state)
    rows = [obs.num[i] for i in range(len(obs.kind)) if int(obs.kind[i]) == 5]
    assert sum(int(r[17]) for r in rows) == 8 and all(int(r[16]) == 0 for r in rows)
    old = [before.num[i] for i in range(len(before.kind)) if int(before.kind[i]) == 5]
    assert all(int(r[17]) == 0 for r in old)
