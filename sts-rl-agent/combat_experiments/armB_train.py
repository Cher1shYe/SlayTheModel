#!/usr/bin/env python3
"""Arm B — 把战斗"蒸馏进权重"第一步:行为克隆(BC)。
让 MCTS 当老师(mcts_recommend),在真实战斗局面里记 (局面, MCTS选的动作),
监督训练一个打分器去模仿 MCTS 的出牌。目标:先追平 MCTS,后续再 RL 微调超越。
战斗局面编码=尽量无损地向量化 BattleContext(player全状态/每怪全状态+意图/手牌/抽弃消耗堆词袋)。
"""
import os, sys, json, re
SB = os.environ.get("STS_BOT_DIR", "../sts-bot")
sys.path.insert(0, os.path.join(SB, "sim/sts_lightspeed/build312"))
sys.path.insert(0, SB)
import slaythespire as sts
import torch, torch.nn as nn

# ---------- 卡词表(沿用,冻结)----------
VOCAB_PATH = os.path.join(SB, "armS_card_vocab.json")
VOCAB_CAP = 256
_vocab = json.load(open(VOCAB_PATH)) if os.path.exists(VOCAB_PATH) else {}
def card_idx(name):
    return _vocab.get(name, VOCAB_CAP - 1)

# ---------- 状态种类(对到绑定的 enum;每种留一格,值=层数)----------
PLAYER_STATUSES = [sts.PlayerStatus.VULNERABLE, sts.PlayerStatus.WEAK, sts.PlayerStatus.FRAIL,
    sts.PlayerStatus.STRENGTH, sts.PlayerStatus.DEXTERITY, sts.PlayerStatus.FOCUS, sts.PlayerStatus.ARTIFACT,
    sts.PlayerStatus.METALLICIZE, sts.PlayerStatus.REGEN, sts.PlayerStatus.PLATED_ARMOR, sts.PlayerStatus.DEMON_FORM,
    sts.PlayerStatus.RITUAL, sts.PlayerStatus.THORNS, sts.PlayerStatus.BARRICADE, sts.PlayerStatus.INTANGIBLE,
    sts.PlayerStatus.NO_BLOCK, sts.PlayerStatus.ENTANGLED]
MONSTER_STATUSES = [sts.MonsterStatus.VULNERABLE, sts.MonsterStatus.WEAK, sts.MonsterStatus.POISON,
    sts.MonsterStatus.STRENGTH, sts.MonsterStatus.ARTIFACT, sts.MonsterStatus.METALLICIZE, sts.MonsterStatus.REGEN,
    sts.MonsterStatus.PLATED_ARMOR, sts.MonsterStatus.BLOCK_RETURN, sts.MonsterStatus.MARK, sts.MonsterStatus.LOCK_ON,
    sts.MonsterStatus.SHACKLED, sts.MonsterStatus.INTANGIBLE, sts.MonsterStatus.CHOKED]
MAX_MON = 5

# ---------- 战斗局面编码器:尽量无损向量化 BattleContext ----------
def _counts(cards):
    v = [0.0] * VOCAB_CAP
    for c in cards:
        v[card_idx(c.name)] += 1.0
    return v

def encode_battle(bc):
    o = []
    p = bc.player
    o += [p.cur_hp / 80.0, p.max_hp / 80.0, p.block / 50.0, p.energy / 10.0,
          p.strength / 10.0, p.dexterity / 10.0, p.focus / 10.0]
    o += [p.get_status(s) / 10.0 for s in PLAYER_STATUSES]          # 玩家状态格
    mons = list(bc.monsters)
    for i in range(MAX_MON):                                        # 定长5个怪槽,不足补0
        if i < len(mons):
            m = mons[i]; di = m.intent_damage(bc)
            o += [1.0, m.cur_hp / 100.0, m.block / 50.0, 1.0 if m.is_attacking else 0.0,
                  di.damage / 50.0, di.attack_count / 5.0]
            o += [m.get_status(s) / 10.0 for s in MONSTER_STATUSES]
        else:
            o += [0.0] * (6 + len(MONSTER_STATUSES))
    o += _counts(bc.hand) + _counts(bc.draw_pile) + _counts(bc.discard_pile)   # 三堆词袋
    o += [bc.turn / 20.0]
    return o

STATE_DIM = 7 + len(PLAYER_STATUSES) + MAX_MON * (6 + len(MONSTER_STATUSES)) + 3 * VOCAB_CAP + 1

# ---------- 候选动作描述符 ----------
ATYPES = [sts.SearchActionType.CARD, sts.SearchActionType.POTION, sts.SearchActionType.SINGLE_CARD_SELECT,
          sts.SearchActionType.MULTI_CARD_SELECT, sts.SearchActionType.END_TURN]
ATYPE_IDX = {t: i for i, t in enumerate(ATYPES)}
CAND_DIM = len(ATYPES) + VOCAB_CAP + MAX_MON + 1     # 类型 + 出哪张牌 + 打哪只怪 + 费用

def cand_desc(bc, a, hand):
    d = [0.0] * CAND_DIM
    t = a.action_type
    if t in ATYPE_IDX: d[ATYPE_IDX[t]] = 1.0
    off = len(ATYPES)
    if t == sts.SearchActionType.CARD and 0 <= a.source_idx < len(hand):
        c = hand[a.source_idx]
        d[off + card_idx(c.name)] = 1.0
        d[off + VOCAB_CAP + MAX_MON] = c.cost / 3.0
    if 0 <= a.target_idx < MAX_MON:
        d[off + VOCAB_CAP + a.target_idx] = 1.0
    return d

INPUT_DIM = STATE_DIM + CAND_DIM

class Scorer(nn.Module):
    def __init__(self, arch=(256, 256)):
        super().__init__()
        layers, prev = [], INPUT_DIM
        for h in arch:
            layers += [nn.Linear(prev, h), nn.ReLU()]; prev = h
        layers += [nn.Linear(prev, 1)]
        self.net = nn.Sequential(*layers)
    def score(self, state, cands):
        rows = torch.stack([torch.tensor(state + c, dtype=torch.float32) for c in cands])
        return self.net(rows).squeeze(-1)

# ---------- 用 MCTS 神谕产 BC 数据:驱动整局,战斗每步记 (局面,候选,MCTS选的idx) ----------
SIMCOUNT = int(os.environ.get("STS_SIM_COUNT", "2000"))
def gen_demos(seed, sims=None, max_steps=600):
    sims = sims or SIMCOUNT
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = sts.Agent(); ag.simulation_count_base = sims; ag.pause_on_battle = True
    demos = []; steps = 0
    try:
        while gc.outcome == sts.GameOutcome.UNDECIDED and steps < max_steps:
            steps += 1; ag.playout(gc)
            if gc.outcome != sts.GameOutcome.UNDECIDED: break
            if gc.screen_state != sts.ScreenState.BATTLE: break
            bc = sts.BattleContext(); bc.init(gc); bsteps = 0
            while bc.outcome == sts.Outcome.UNDECIDED and bsteps < 800:
                bsteps += 1
                cands = sts.get_legal_actions(bc)
                if not cands: break
                rec = sts.mcts_recommend(bc, sims)                  # 老师:MCTS 推荐
                idx = next((i for i, a in enumerate(cands) if a.bits == rec.bits), None)
                if idx is None: idx = 0; rec = cands[0]
                if len(cands) > 1:                                  # 单候选无监督价值
                    hand = list(bc.hand)
                    demos.append((encode_battle(bc), [cand_desc(bc, a, hand) for a in cands], idx))
                rec.execute(bc)
            bc.exit_battle(gc)
    except Exception:
        pass    # sim 偶发异常:保留已收集的 demos,本局到此为止
    return {"seed": seed, "floor": gc.floor_num, "win": gc.outcome == sts.GameOutcome.PLAYER_VICTORY, "demos": demos}

# ---------- 用模型打战斗(eval):非战斗交内置启发式,战斗由 net 贪心选 ----------
def play_with_model(seed, net, sims=None, max_steps=600):
    sims = sims or SIMCOUNT
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = sts.Agent(); ag.simulation_count_base = sims; ag.pause_on_battle = True
    steps = 0
    try:
        while gc.outcome == sts.GameOutcome.UNDECIDED and steps < max_steps:
            steps += 1; ag.playout(gc)
            if gc.outcome != sts.GameOutcome.UNDECIDED: break
            if gc.screen_state != sts.ScreenState.BATTLE: break
            bc = sts.BattleContext(); bc.init(gc); bsteps = 0
            while bc.outcome == sts.Outcome.UNDECIDED and bsteps < 800:
                bsteps += 1
                cands = sts.get_legal_actions(bc)
                if not cands: break
                if len(cands) == 1:
                    cands[0].execute(bc); continue
                state = encode_battle(bc); hand = list(bc.hand)
                with torch.no_grad():
                    scores = net.score(state, [cand_desc(bc, a, hand) for a in cands])
                    a = int(torch.argmax(scores).item())
                cands[a].execute(bc)
            bc.exit_battle(gc)
    except Exception:
        pass    # sim 偶发异常(如 map::at):本局就此终止,按当前楼层计
    return {"seed": seed, "floor": gc.floor_num, "act": gc.act,
            "win": gc.outcome == sts.GameOutcome.PLAYER_VICTORY}

# ---------- DAgger 产数据:模型驾驶,MCTS 在它踩到的局面上给答案(标签),执行模型自己的动作 ----------
def gen_dagger_demos(seed, net, sims=None, max_steps=600):
    sims = sims or SIMCOUNT
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = sts.Agent(); ag.simulation_count_base = sims; ag.pause_on_battle = True
    demos = []; steps = 0
    try:
        while gc.outcome == sts.GameOutcome.UNDECIDED and steps < max_steps:
            steps += 1; ag.playout(gc)
            if gc.outcome != sts.GameOutcome.UNDECIDED: break
            if gc.screen_state != sts.ScreenState.BATTLE: break
            bc = sts.BattleContext(); bc.init(gc); bsteps = 0
            while bc.outcome == sts.Outcome.UNDECIDED and bsteps < 800:
                bsteps += 1
                cands = sts.get_legal_actions(bc)
                if not cands: break
                if len(cands) == 1:
                    cands[0].execute(bc); continue
                state = encode_battle(bc); hand = list(bc.hand)
                descs = [cand_desc(bc, a, hand) for a in cands]
                rec = sts.mcts_recommend(bc, sims)                  # 老师:在模型踩到的局面给答案
                midx = next((i for i, a in enumerate(cands) if a.bits == rec.bits), 0)
                demos.append((state, descs, midx))                 # 标签=MCTS;但接下来执行模型自己的动作
                with torch.no_grad():
                    a = int(torch.argmax(net.score(state, descs)).item())
                cands[a].execute(bc)                               # 模型驾驶,好继续漂进自己的烂局面
            bc.exit_battle(gc)
    except Exception:
        pass
    return {"seed": seed, "floor": gc.floor_num, "win": gc.outcome == sts.GameOutcome.PLAYER_VICTORY, "demos": demos}

# ---------- RL rollout:模型采样出牌,记每场战斗的轨迹 + per-battle 回报(赢+留血)----------
def gen_rl_rollout(seed, net, sims=None, max_steps=600):
    sims = sims or SIMCOUNT
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = sts.Agent(); ag.simulation_count_base = sims; ag.pause_on_battle = True
    battles = []; steps = 0
    try:
        while gc.outcome == sts.GameOutcome.UNDECIDED and steps < max_steps:
            steps += 1; ag.playout(gc)
            if gc.outcome != sts.GameOutcome.UNDECIDED: break
            if gc.screen_state != sts.ScreenState.BATTLE: break
            bc = sts.BattleContext(); bc.init(gc); bsteps = 0; traj = []
            while bc.outcome == sts.Outcome.UNDECIDED and bsteps < 800:
                bsteps += 1
                cands = sts.get_legal_actions(bc)
                if not cands: break
                if len(cands) == 1:
                    cands[0].execute(bc); continue
                state = encode_battle(bc); hand = list(bc.hand)
                descs = [cand_desc(bc, a, hand) for a in cands]
                with torch.no_grad():
                    probs = torch.softmax(net.score(state, descs), dim=0)
                    a = int(torch.multinomial(probs, 1).item())          # 采样=探索
                traj.append((state, descs, a))
                cands[a].execute(bc)
            win = bc.outcome == sts.Outcome.PLAYER_VICTORY
            hpfrac = bc.player.cur_hp / max(1, bc.player.max_hp)
            R = (1.0 if win else 0.0) + hpfrac                            # per-battle 回报:赢+留血
            if traj: battles.append((traj, R))
            bc.exit_battle(gc)
    except Exception:
        pass
    return {"seed": seed, "floor": gc.floor_num, "win": gc.outcome == sts.GameOutcome.PLAYER_VICTORY, "battles": battles}

def read_seeds(fn):
    return [int(x) for x in open(os.path.join(SB, fn)) if x.strip() and not x.startswith("#")]

if __name__ == "__main__":
    print(f"STATE_DIM={STATE_DIM} CAND_DIM={CAND_DIM} INPUT_DIM={INPUT_DIM}", flush=True)
