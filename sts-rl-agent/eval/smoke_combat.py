#!/usr/bin/env python3
"""冒烟:验证 pause_on_battle + Python 驱动战斗(BattleContext + get_legal_actions + SearchAction.execute)
+ 牌堆/状态读取。先随机出牌(必然打得稀烂、早死),只看管道通不通。
跑: ~/lab/physical-world-ai/.venv/bin/python smoke_combat.py [seed]
"""
import os, sys, random
SB = os.environ.get("STS_BOT_DIR", "../sts-bot")
sys.path.insert(0, os.path.join(SB, "sim/sts_lightspeed/build312"))
import slaythespire as sts

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 42
rng = random.Random(seed)
gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
ag = sts.Agent(); ag.simulation_count_base = 500
ag.pause_on_battle = True          # 只接管战斗,非战斗交内置启发式

def drive_battle(gc, first):
    bc = sts.BattleContext(); bc.init(gc)
    steps = 0
    if first:                       # 第一场战斗:打印一帧状态,确认读取正常
        print(f"  [战斗状态] turn={bc.turn} player hp={bc.player.cur_hp} block={bc.player.block} energy={bc.player.energy}")
        print(f"    手牌={[c.name for c in bc.hand]}")
        print(f"    抽牌堆 {len(bc.draw_pile)} 张 / 弃牌堆 {len(bc.discard_pile)} / 消耗堆 {len(bc.exhaust_pile)}")
        for m in bc.monsters:
            di = m.intent_damage(bc)
            print(f"    怪 {m.name} hp={m.cur_hp}/{m.max_hp} intent={m.intent} dmg={di.damage}x{di.attack_count} vuln={m.vulnerable} weak={m.weak}")
    while bc.outcome == sts.Outcome.UNDECIDED and steps < 1000:
        steps += 1
        acts = sts.get_legal_actions(bc)
        if not acts: break
        acts[rng.randrange(len(acts))].execute(bc)
    bc.exit_battle(gc)
    return bc.outcome

battles = 0; steps = 0
while gc.outcome == sts.GameOutcome.UNDECIDED and steps < 600:
    steps += 1
    ag.playout(gc)
    if gc.outcome != sts.GameOutcome.UNDECIDED: break
    if gc.screen_state == sts.ScreenState.BATTLE:
        drive_battle(gc, first=(battles == 0)); battles += 1
    else:
        break   # pause_on_battle 只该停在战斗;其它不该停(非战斗交内置)
print(f"seed={seed} 结局={str(gc.outcome).split('.')[-1]} 楼层={gc.floor_num} 打了{battles}场战斗(python随机驱动)")
print("SMOKE_OK" if battles > 0 and gc.outcome != sts.GameOutcome.UNDECIDED else "SMOKE_FAIL")
