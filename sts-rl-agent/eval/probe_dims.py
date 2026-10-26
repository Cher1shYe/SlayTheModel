#!/usr/bin/env python3
"""量一下各编码件的维度,定下训练器输入大小。"""
import os, sys
SB = os.environ.get("STS_BOT_DIR", "../sts-bot")
sys.path.insert(0, os.path.join(SB, "sim/sts_lightspeed/build312"))
import slaythespire as sts

gc = sts.GameContext(sts.CharacterClass.IRONCLAD, 777, 0)
ag = sts.Agent(); ag.simulation_count_base = 400
ag.pause_on_card_reward = ag.pause_on_map = ag.pause_on_rest = ag.pause_on_shop = ag.pause_on_event = True

obs = sts.getNNInterface().getObservation(gc)
print("obs (getObservation) 维度 =", len(obs))

seen = set(); steps = 0
while gc.outcome == sts.GameOutcome.UNDECIDED and steps < 400 and len(seen) < 5:
    steps += 1; ag.playout(gc)
    if gc.outcome != sts.GameOutcome.UNDECIDED: break
    ss = gc.screen_state
    if ss == sts.ScreenState.REWARDS:
        off = gc.get_card_reward()
        if off and str(ss) not in seen:
            seen.add(str(ss)); print(f"[{ss}] 候选(卡)数={len(off)} 例:{[str(c) for c in off]}")
        if off: gc.pick_reward_card(off[0])
        else: gc.skip_reward_cards()
    elif ss in (sts.ScreenState.MAP_SCREEN, sts.ScreenState.REST_ROOM, sts.ScreenState.SHOP_ROOM, sts.ScreenState.EVENT_SCREEN):
        acts = sts.get_legal_game_actions(gc)
        if str(ss) not in seen:
            seen.add(str(ss))
            print(f"[{ss}] 候选数={len(acts)} idx1s={[a.idx1 for a in acts]}")
            if ss == sts.ScreenState.MAP_SCREEN:
                mnn = gc.get_map_nn()
                print(f"    get_map_nn 维度 = {len(mnn)} ; cur_pos=({gc.cur_map_node_x},{gc.cur_map_node_y})")
                print(f"    候选目标房间 = {[str(gc.map_node_room(a.idx1, gc.cur_map_node_y+1)).split('.')[-1] for a in acts]}")
            if ss == sts.ScreenState.SHOP_ROOM:
                print(f"    rewards_action_type = {[str(a.rewards_action_type).split('.')[-1] for a in acts]}")
            if ss == sts.ScreenState.EVENT_SCREEN:
                print(f"    cur_event id = {gc.cur_event}")
        acts[0].execute(gc)
print("done. seen:", seen)
