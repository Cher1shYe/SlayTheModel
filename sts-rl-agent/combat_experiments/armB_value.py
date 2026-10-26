#!/usr/bin/env python3
"""Arm B AlphaZero 式(精简核):价值网络 + 浅前瞻。
价值网 V(战斗局面)→ 这局面有多好(预测最终 赢+留血)。
打法=对每个候选动作:克隆战斗、走一步、用 V 评估走完的局面,挑最高(1步前瞻)。
检验"哪怕 1 步 lookahead + 学出的价值",能否破前馈的 ~12-14 战斗墙。
"""
import os, sys
SB = os.environ.get("STS_BOT_DIR", "../sts-bot")
sys.path.insert(0, os.path.join(SB, "sim/sts_lightspeed/build312"))
sys.path.insert(0, SB)
import slaythespire as sts
import torch, torch.nn as nn
import armB_train as MB        # 复用 encode_battle / STATE_DIM / SIMCOUNT / read_seeds

STATE_DIM = MB.STATE_DIM

class ValueNet(nn.Module):
    def __init__(self, arch=(256, 256)):
        super().__init__()
        layers, prev = [], STATE_DIM
        for h in arch:
            layers += [nn.Linear(prev, h), nn.ReLU()]; prev = h
        layers += [nn.Linear(prev, 1)]
        self.net = nn.Sequential(*layers)
    def value(self, state):                       # state: list[float] -> scalar
        return self.net(torch.tensor(state, dtype=torch.float32)).squeeze(-1)

def _battle_value(bc):                            # 终局价值:赢+留血(0~2)
    win = 1.0 if bc.outcome == sts.Outcome.PLAYER_VICTORY else 0.0
    return win + bc.player.cur_hp / max(1, bc.player.max_hp)

# ---------- 价值数据:MCTS 驱动战斗,记每个局面;战斗结束把终局价值回贴给本场所有局面(MC)----------
def gen_value_data(seed, sims=None, max_steps=600):
    sims = sims or MB.SIMCOUNT
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = sts.Agent(); ag.simulation_count_base = sims; ag.pause_on_battle = True
    data = []; steps = 0
    try:
        while gc.outcome == sts.GameOutcome.UNDECIDED and steps < max_steps:
            steps += 1; ag.playout(gc)
            if gc.outcome != sts.GameOutcome.UNDECIDED or gc.screen_state != sts.ScreenState.BATTLE: break
            bc = sts.BattleContext(); bc.init(gc); bs = 0; states = []
            while bc.outcome == sts.Outcome.UNDECIDED and bs < 800:
                bs += 1
                cands = sts.get_legal_actions(bc)
                if not cands: break
                states.append(MB.encode_battle(bc))           # 决策前的局面
                rec = sts.mcts_recommend(bc, sims)
                gi = next((i for i, a in enumerate(cands) if a.bits == rec.bits), 0)
                cands[gi].execute(bc)
            V = _battle_value(bc)                              # 本场终局价值,回贴给所有局面
            data += [(s, V) for s in states]
            bc.exit_battle(gc)
    except Exception: pass
    return {"seed": seed, "floor": gc.floor_num, "data": data}

# ---------- 打法:1 步前瞻(克隆+走一步+价值网评估,挑最高)----------
def play_with_value(seed, vnet, sims=None, depth=1, max_steps=600):
    sims = sims or MB.SIMCOUNT
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = sts.Agent(); ag.simulation_count_base = sims; ag.pause_on_battle = True
    steps = 0
    try:
        while gc.outcome == sts.GameOutcome.UNDECIDED and steps < max_steps:
            steps += 1; ag.playout(gc)
            if gc.outcome != sts.GameOutcome.UNDECIDED or gc.screen_state != sts.ScreenState.BATTLE: break
            bc = sts.BattleContext(); bc.init(gc); bs = 0
            while bc.outcome == sts.Outcome.UNDECIDED and bs < 800:
                bs += 1
                cands = sts.get_legal_actions(bc)
                if not cands: break
                if len(cands) == 1: cands[0].execute(bc); continue
                best_a, best_v = cands[0], -1e9
                with torch.no_grad():
                    for a in cands:
                        bc2 = bc.clone(); a.execute(bc2)        # 克隆走一步
                        if bc2.outcome != sts.Outcome.UNDECIDED:
                            v = _battle_value(bc2)              # 走完直接分出胜负→真终局价值
                        else:
                            v = float(vnet.value(MB.encode_battle(bc2)).item())
                        if v > best_v: best_v, best_a = v, a
                best_a.execute(bc)
            bc.exit_battle(gc)
    except Exception: pass
    return {"seed": seed, "floor": gc.floor_num, "win": gc.outcome == sts.GameOutcome.PLAYER_VICTORY}

if __name__ == "__main__":
    print(f"STATE_DIM={STATE_DIM}", flush=True)
