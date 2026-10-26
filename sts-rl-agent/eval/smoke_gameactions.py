#!/usr/bin/env python3
"""冒烟:验证新加的非战斗决策接口(pause_on_map/rest/shop/event + get_legal_game_actions + GameAction.execute)。
全程由 python 驱动一局——每个非战斗决策点随机选,战斗交 MCTS。统计每类决策触发次数,确认钩子都生效。
跑: ~/lab/physical-world-ai/.venv/bin/python smoke_gameactions.py [seed]
"""
import os, sys, random, collections
SB = os.environ.get("STS_BOT_DIR", "../sts-bot")
sys.path.insert(0, os.path.join(SB, "sim/sts_lightspeed/build312"))
import slaythespire as sts

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 777
rng = random.Random(seed)

gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
ag = sts.Agent()
ag.simulation_count_base = 800           # 低 sim,只为快速验证管道
ag.pause_on_card_reward = True
ag.pause_on_map = True
ag.pause_on_rest = True
ag.pause_on_shop = True
ag.pause_on_event = True

counts = collections.Counter()
steps = 0
while gc.outcome == sts.GameOutcome.UNDECIDED and steps < 2000:
    steps += 1
    ag.playout(gc)                       # 跑到下一个暂停点 / 处理完一场战斗 / 结局
    if gc.outcome != sts.GameOutcome.UNDECIDED:
        break
    ss = gc.screen_state
    if ss == sts.ScreenState.REWARDS:                    # 选卡走原有接口(与 Arm S 一致)
        offered = gc.get_card_reward()
        if not offered:
            gc.skip_reward_cards(); counts["reward_skip_empty"] += 1; continue
        if rng.random() < 0.5:
            gc.pick_reward_card(rng.choice(offered)); counts["card_pick"] += 1
        else:
            gc.skip_reward_cards(); counts["card_skip"] += 1
    elif ss in (sts.ScreenState.MAP_SCREEN, sts.ScreenState.REST_ROOM,
                sts.ScreenState.SHOP_ROOM, sts.ScreenState.EVENT_SCREEN):
        acts = sts.get_legal_game_actions(gc)            # 新通用接口
        if not acts:
            print(f"!! 空候选 @ {ss} —— 不该发生(C++已保证pause时≥1)"); break
        a = rng.choice(acts)
        # 顺带验证一下编码辅助没崩
        if ss == sts.ScreenState.MAP_SCREEN:
            _room = gc.map_node_room(a.idx1, gc.cur_map_node_y + 1)
        elif ss == sts.ScreenState.SHOP_ROOM:
            _ = gc.get_shop_cards(); _ev = gc.cur_event
        a.execute(gc)
        counts[str(ss).split(".")[-1]] += 1
    else:
        print(f"!! 意外停在 {ss}，没处理 —— 死循环风险"); break

print(f"seed={seed} 结局={str(gc.outcome).split('.')[-1]} 楼层={gc.floor_num} act={gc.act} hp={gc.cur_hp} steps={steps}")
print("各决策点触发次数:", dict(counts))
ok = gc.outcome != sts.GameOutcome.UNDECIDED and counts.get("MAP_SCREEN", 0) > 0
print("SMOKE_OK" if ok else "SMOKE_FAIL(没跑到结局或地图钩子没触发)")
