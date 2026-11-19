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
