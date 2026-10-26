#!/usr/bin/env python3
"""Arm B 注意力版战斗打分器:把战斗拆成 token(玩家/每只怪/每张手牌),
过自注意力让 token 互相"看见"(建模 牌-怪、牌-牌 关系),再据此给每个候选动作打分。
对照 MLP 版(逐动作独立打分、无关系):看注意力能否突破 ~12 的战斗墙。
"""
import os, sys, json
SB = os.environ.get("STS_BOT_DIR", "../sts-bot")
sys.path.insert(0, os.path.join(SB, "sim/sts_lightspeed/build312"))
sys.path.insert(0, SB)
import slaythespire as sts
import torch, torch.nn as nn
import armB_train as MB    # 复用 card_idx / 状态表 / read_seeds / SIMCOUNT

VOCAB_CAP = MB.VOCAB_CAP
PLAYER_STATUSES, MONSTER_STATUSES = MB.PLAYER_STATUSES, MB.MONSTER_STATUSES
CARD_TYPES = [sts.CardType.ATTACK, sts.CardType.SKILL, sts.CardType.POWER, sts.CardType.CURSE, sts.CardType.STATUS]
CTYPE_IDX = {t: i for i, t in enumerate(CARD_TYPES)}
ATYPES = MB.ATYPES; ATYPE_IDX = MB.ATYPE_IDX
PLAYER_FEAT = 7 + len(PLAYER_STATUSES)            # 24
MON_FEAT = 5 + len(MONSTER_STATUSES)              # 19
CARD_EXTRA = 1 + len(CARD_TYPES) + 1              # 费用 + 类型one-hot + 是否需要目标 = 7

# ---------- 结构化提取:把 BattleContext 拆成 token 特征(不拍平成一条向量)----------
def player_feat(p):
    return [p.cur_hp/80.0, p.max_hp/80.0, p.block/50.0, p.energy/10.0,
            p.strength/10.0, p.dexterity/10.0, p.focus/10.0] + [p.get_status(s)/10.0 for s in PLAYER_STATUSES]

def monster_feat(m, bc):
    di = m.intent_damage(bc)
    return [m.cur_hp/100.0, m.block/50.0, 1.0 if m.is_attacking else 0.0, di.damage/50.0, di.attack_count/5.0] \
           + [m.get_status(s)/10.0 for s in MONSTER_STATUSES]

def card_token(c):
    extra = [c.cost/3.0] + [0.0]*len(CARD_TYPES) + [1.0 if c.requires_target else 0.0]
    ti = CTYPE_IDX.get(c.type)
    if ti is not None: extra[1+ti] = 1.0
    return (MB.card_idx(c.name), extra)

def extract(bc):
    return (player_feat(bc.player),
            [monster_feat(m, bc) for m in bc.monsters],
            [card_token(c) for c in bc.hand])

def cand_tuple(a):                                # 候选=(动作类型idx, 手牌槽idx, 目标怪idx)
    return (ATYPE_IDX.get(a.action_type, 0), a.source_idx, a.target_idx)

# ---------- 注意力打分网络 ----------
class AttnScorer(nn.Module):
    def __init__(self, d=64, heads=4, layers=2, ff=128):
        super().__init__()
        self.d = d
        self.player_proj = nn.Linear(PLAYER_FEAT, d)
        self.mon_proj = nn.Linear(MON_FEAT, d)
        self.card_emb = nn.Embedding(VOCAB_CAP, d)
        self.hand_proj = nn.Linear(CARD_EXTRA, d)
        self.type_emb = nn.Embedding(3, d)        # 0=玩家 1=怪 2=手牌
        self.atype_emb = nn.Embedding(len(ATYPES), d)  # 非出牌动作(结束/药水/选牌)的查询
        self.no_tgt = nn.Parameter(torch.zeros(d))
        enc = nn.TransformerEncoderLayer(d_model=d, nhead=heads, dim_feedforward=ff, batch_first=False)
        self.transformer = nn.TransformerEncoder(enc, num_layers=layers)
        self.head = nn.Sequential(nn.Linear(3*d, d), nn.ReLU(), nn.Linear(d, 1))

    def score(self, tokens, cands):
        pf, mfs, hfs = tokens
        toks = [self.player_proj(torch.tensor(pf, dtype=torch.float32)) + self.type_emb.weight[0]]
        for mf in mfs:
            toks.append(self.mon_proj(torch.tensor(mf, dtype=torch.float32)) + self.type_emb.weight[1])
        for cidx, extra in hfs:
            toks.append(self.card_emb.weight[cidx] + self.hand_proj(torch.tensor(extra, dtype=torch.float32)) + self.type_emb.weight[2])
        X = torch.stack(toks).unsqueeze(1)         # [T,1,d]
        H = self.transformer(X).squeeze(1)         # [T,d] 上下文化后的 token
        player_tok = H[0]; M = len(mfs)
        mon_toks = H[1:1+M]; hand_toks = H[1+M:1+M+len(hfs)]
        out = []
        for atype, src, tgt in cands:
            if atype == 0 and 0 <= src < len(hfs):          # 出牌:用这张牌的上下文token
                card_part = hand_toks[src]
            else:                                            # 结束/药水/选牌:用动作类型查询
                card_part = self.atype_emb.weight[atype]
            tgt_part = mon_toks[tgt] if (0 <= tgt < M) else self.no_tgt
            out.append(self.head(torch.cat([card_part, tgt_part, player_tok])))
        return torch.cat(out).squeeze(-1)

# ---------- 产数据(MCTS神谕)/ eval(模型打战斗),结构化版 ----------
def gen_attn_demos(seed, sims=None, max_steps=600):
    sims = sims or MB.SIMCOUNT
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = sts.Agent(); ag.simulation_count_base = sims; ag.pause_on_battle = True
    demos = []; steps = 0
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
                rec = sts.mcts_recommend(bc, sims)
                gi = next((i for i, a in enumerate(cands) if a.bits == rec.bits), 0)
                demos.append((extract(bc), [cand_tuple(a) for a in cands], gi))
                cands[gi].execute(bc)
            bc.exit_battle(gc)
    except Exception: pass
    return {"seed": seed, "floor": gc.floor_num, "demos": demos}

def play_with_attn(seed, net, sims=None, max_steps=600):
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
                with torch.no_grad():
                    a = int(torch.argmax(net.score(extract(bc), [cand_tuple(x) for x in cands])).item())
                cands[a].execute(bc)
            bc.exit_battle(gc)
    except Exception: pass
    return {"seed": seed, "floor": gc.floor_num, "win": gc.outcome == sts.GameOutcome.PLAYER_VICTORY}

if __name__ == "__main__":
    print(f"PLAYER_FEAT={PLAYER_FEAT} MON_FEAT={MON_FEAT} CARD_EXTRA={CARD_EXTRA}", flush=True)
