"""ArmG2: value-based card selection for the non-combat policy.

The frozen ArmG scorer never skips a card reward and has no explicit
candidate/deck interaction, so decks bloat and junk gets picked.  Here a
deck-value network V(obs, deck) predicts the run outcome and card rewards are
decided by a *delta* head d(obs, deck, card): the run is cloned at the reward
screen, each candidate (including skip) is played out to the terminal, and the
head is trained on the counterfactual outcome difference.  Non-card screens
keep the frozen ArmG policy.

Subcommands:
  collect   behaviour episodes with the battle agent at a fixed budget
  branch    counterfactual card-reward labels via GameContext.clone()
  train     fit the absolute (+ optional behaviour) value heads
  trainx    fit the counterfactual delta head on branch data
  eval      benchmark: learned card picker, ArmG elsewhere
"""
import argparse, json, os, pickle, random, statistics, sys, time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

sys.path.insert(0, 'deployment')
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'simulator/build312/Release'))
import selfplay_v2 as V2

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

# ---------------------------------------------------------------- card vocabulary
def build_vocab():
    try:
        sts = V2.sts
    except AttributeError:
        import slaythespire as sts
    names = sorted(n for n in dir(sts.CardId) if n.isupper())
    idx = {n: i for i, n in enumerate(names)}
    types = np.zeros(len(names), np.int64)
    rar = np.zeros(len(names), np.int64)
    strike = np.zeros(len(names), np.float32)
    defend = np.zeros(len(names), np.float32)
    wgt = np.zeros(len(names), np.float32)
    for n, i in idx.items():
        try:
            c = sts.Card(getattr(sts.CardId, n))
            types[i] = int(c.type)
            rar[i] = int(c.rarity)
            low = n.lower()
            strike[i] = 1.0 if ('strike' in low or low in ('STRIKE_RED', 'STRIKE_GREEN', 'STRIKE_BLUE', 'STRIKE_PURPLE')) else 0.0
            defend[i] = 1.0 if ('defend' in low or low in ('DEFEND_RED', 'DEFEND_GREEN', 'DEFEND_BLUE', 'DEFEND_PURPLE')) else 0.0
            try:
                wgt[i] = float(sts.card_obtain_weight(getattr(sts.CardId, n), False)) / 100.0
            except Exception:
                wgt[i] = 0.0
        except Exception:
            types[i] = 5; rar[i] = 6
    return names, idx, types, rar, strike, defend, wgt

CARD_NAMES = None
CARD_IDX = None
CARD_TYPE = None
CARD_RAR = None
CARD_STRIKE = None
CARD_DEFEND = None
CARD_WEIGHT = None
NCARDS = 0
NSLOTS = 0
SKIP_SLOT = 0
DECK_BLOCK = (14, 234)   # deck count block inside the 412-d NN observation
OBS_DIM = 412


def init_vocab():
    global CARD_NAMES, CARD_IDX, CARD_TYPE, CARD_RAR, CARD_STRIKE, CARD_DEFEND, CARD_WEIGHT
    global NCARDS, NSLOTS, SKIP_SLOT
    if CARD_NAMES is not None:
        return
    CARD_NAMES, CARD_IDX, CARD_TYPE, CARD_RAR, CARD_STRIKE, CARD_DEFEND, CARD_WEIGHT = build_vocab()
    NCARDS = len(CARD_NAMES)
    NSLOTS = 2 * NCARDS
    SKIP_SLOT = NSLOTS       # extra row: the "take nothing" candidate


def slot_of(card):
    i = CARD_IDX.get(card.id.name, CARD_IDX.get('INVALID', 0))
    return 2 * i + (1 if card.upgraded else 0)


def zero_obs(obs):
    o = np.array(obs, dtype=np.float32, copy=True)
    o[DECK_BLOCK[0]:DECK_BLOCK[1]] = 0.0
    return o


def deck_counts(deck):
    cnt = np.zeros(NSLOTS, dtype=np.float32)
    for c in deck:
        cnt[slot_of(c)] += 1.0
    return cnt


# precomputed slot masks (numpy and torch)
def slot_masks():
    t = np.zeros(NSLOTS, np.float32); r = np.zeros((NSLOTS, 7), np.float32)
    st = np.zeros(NSLOTS, np.float32); df = np.zeros(NSLOTS, np.float32)
    up = np.zeros(NSLOTS, np.float32)
    for i in range(NCARDS):
        for k in (0, 1):
            s = 2 * i + k
            t[s] = CARD_TYPE[i]
            r[s, min(int(CARD_RAR[i]), 6)] = 1.0
            st[s] = CARD_STRIKE[i]; df[s] = CARD_DEFEND[i]
            up[s] = k
    return t, r, st, df, up

TYPE_MAT = None; RAR_MAT = None; STRIKE_V = None; DEFEND_V = None; UPG_V = None
TYPE_MASKS = None; CURSE_VEC = None; STATUS_VEC = None; CAND_MAT = None
WEIGHT_V = None; WEIGHT_UPG_V = None

CAND_FEAT = 6 + 7 + 1 + 1 + 1 + 1 + 2   # type, rarity, upgraded, strike, defend, skip, expert weight, upg weight


def init_masks():
    global TYPE_MAT, RAR_MAT, STRIKE_V, DEFEND_V, UPG_V, TYPE_MASKS, CURSE_VEC, STATUS_VEC, CAND_MAT
    global WEIGHT_V, WEIGHT_UPG_V
    if TYPE_MAT is not None:
        return
    t, r, st, df, up = slot_masks()
    TYPE_MAT = torch.tensor(t, dtype=torch.float32)
    RAR_MAT = torch.tensor(r, dtype=torch.float32)
    STRIKE_V = torch.tensor(st); DEFEND_V = torch.tensor(df); UPG_V = torch.tensor(up)
    wv = torch.zeros(NSLOTS); wuv = torch.zeros(NSLOTS)
    for i in range(NCARDS):
        for k in (0, 1):
            wv[2 * i + k] = float(CARD_WEIGHT[i])
            wuv[2 * i + k] = float(CARD_WEIGHT[i]) * (1.5 if k else 1.0)
    WEIGHT_V = wv; WEIGHT_UPG_V = wuv
    TYPE_MASKS = [(TYPE_MAT == k).float() for k in range(6)]
    CURSE_VEC = torch.tensor([1.0 if 'CURSE' in n else 0.0 for n in CARD_NAMES for _ in (0, 1)])
    STATUS_VEC = torch.tensor([1.0 if 'STATUS' in n else 0.0 for n in CARD_NAMES for _ in (0, 1)])
    cm = torch.zeros(NSLOTS + 1, CAND_FEAT)
    for i in range(NCARDS):
        for k in (0, 1):
            s = 2 * i + k
            cm[s, min(int(CARD_TYPE[i]), 5)] = 1.0
            cm[s, 6 + min(int(CARD_RAR[i]), 6)] = 1.0
            cm[s, 13] = float(k)
            cm[s, 14] = float(CARD_STRIKE[i])
            cm[s, 15] = float(CARD_DEFEND[i])
            cm[s, 17] = float(CARD_WEIGHT[i])
            cm[s, 18] = float(CARD_WEIGHT[i]) * (1.5 if k else 1.0)
    cm[SKIP_SLOT, 16] = 1.0
    CAND_MAT = cm


NSTATS = 6 + 7 + 10   # type fractions, rarity fractions, misc + expert-weight summary


def deck_stats(cnt):
    """cnt: torch [B, NSLOTS] -> [B, NSTATS]"""
    total = cnt.sum(dim=1, keepdim=True).clamp(min=1.0)
    types = torch.stack([(cnt * m).sum(dim=1) / total.squeeze(1) for m in TYPE_MASKS], dim=1)
    rars = cnt @ RAR_MAT / total
    wsum = cnt @ WEIGHT_V
    misc = torch.stack([
        total.squeeze(1) / 51.0,
        (cnt * UPG_V).sum(dim=1) / total.squeeze(1),
        (cnt * STRIKE_V).sum(dim=1) / total.squeeze(1),
        (cnt * DEFEND_V).sum(dim=1) / total.squeeze(1),
        ((cnt @ CURSE_VEC) / total.squeeze(1)),
        ((cnt @ STATUS_VEC) / total.squeeze(1)),
        wsum / total.squeeze(1),
        (cnt @ WEIGHT_UPG_V) / total.squeeze(1),
        ((cnt * (WEIGHT_V >= 0.2).float()).sum(dim=1)) / total.squeeze(1),
        ((cnt * (WEIGHT_V >= 0.5).float()).sum(dim=1)) / total.squeeze(1),
    ], dim=1)
    return torch.cat([types, rars, misc], dim=1)


# ---------------------------------------------------------------- value network
D_EMB = 32
JUNK = {'Clash', 'Wild Strike', 'Anger', 'Reckless Charge', 'Combust', 'Fire Breathing',
        'Havoc', 'Warcry', 'Sever Soul', 'Dropkick'}


def card_name(c):
    s = str(c)
    import re
    m = re.search(r'Card (.+?)>', s)
    return m.group(1) if m else s


def expert_w(c):
    i = CARD_IDX.get(c.id.name, 0)
    return float(CARD_WEIGHT[i]) * (1.5 if c.upgraded else 1.0)


class DeckValue(nn.Module):
    """Absolute run value V(obs, deck) plus a candidate delta head.

    ``encode`` builds a deck context h from the observation and the deck
    *before* the decision; ``delta`` scores a single candidate card as a
    bilinear candidate/deck interaction plus an MLP over [h, emb, feats].
    The skip candidate uses its own embedding row (SKIP_SLOT).
    """

    def __init__(self):
        super().__init__()
        init_masks()
        self.obs_enc = nn.Sequential(nn.Linear(OBS_DIM, 256), nn.ReLU(), nn.Linear(256, 128), nn.ReLU())
        self.emb = nn.Parameter(torch.randn(NSLOTS + 1, D_EMB) * 0.05)
        self.deck_proj = nn.Sequential(nn.Linear(D_EMB + NSTATS, 64), nn.ReLU())
        self.cnt_proj = nn.Sequential(nn.Linear(NSLOTS, 64), nn.ReLU())
        self.trunk = nn.Sequential(nn.Linear(128 + 64 + 64, 128), nn.ReLU(),
                                   nn.Linear(128, 64), nn.ReLU())
        self.win = nn.Linear(64, 1)
        self.floor = nn.Linear(64, 1)
        self.act = nn.Linear(64, 3)
        self.hp = nn.Linear(64, 1)
        self.sc = nn.Linear(64, 1)
        self.cq = nn.Linear(D_EMB + CAND_FEAT, 64)
        self.ck = nn.Linear(64, 64)
        self.dmlp = nn.Sequential(nn.Linear(64 + D_EMB + CAND_FEAT, 128), nn.ReLU(),
                                  nn.Linear(128, 64), nn.ReLU(), nn.Linear(64, 1))

    def encode(self, obs, cnt):
        total = cnt.sum(dim=1, keepdim=True).clamp(min=1.0)
        de = (cnt @ self.emb[:NSLOTS]) / total
        st = deck_stats(cnt)
        deck = self.deck_proj(torch.cat([de, st], dim=1))
        return self.trunk(torch.cat([self.obs_enc(obs), deck, self.cnt_proj(cnt)], dim=1))

    def heads(self, h):
        return (self.win(h).squeeze(1), self.floor(h).squeeze(1), self.act(h),
                torch.sigmoid(self.hp(h)).squeeze(1))

    def forward(self, obs, cnt):
        return self.heads(self.encode(obs, cnt))

    def delta(self, h, slots):
        """h [B,64] (or [1,64]); slots [B] long -> delta [B]."""
        if h.dim() == 2 and h.shape[0] == 1 and slots.numel() > 1:
            h = h.expand(slots.numel(), -1)
        cf = CAND_MAT[slots].to(h.device)
        ce = self.emb[slots]
        q = self.cq(torch.cat([ce, cf], dim=1))
        k = self.ck(h)
        bil = (q * k).sum(dim=1) / 8.0
        return self.dmlp(torch.cat([h, ce, cf], dim=1)).squeeze(1) + bil


def value_score(win_logit, floor_logit):
    return torch.sigmoid(win_logit) + 0.5 * torch.sigmoid(floor_logit)


_CARD_NETS = {}


def load_card_net(path):
    """Load a fine-tuned non-combat scorer with the ArmG architecture."""
    key = str(path)
    if key in _CARD_NETS:
        return _CARD_NETS[key]
    import torch as _t
    net = V2.AG.Scorer((128, 128))
    net.load_state_dict(_t.load(key, map_location='cpu', weights_only=True))
    net.eval()
    _CARD_NETS[key] = net
    return net


def load_deck_value(path):
    """Load a checkpoint, skipping layers whose shape changed between versions."""
    model = DeckValue()
    sd = torch.load(path, weights_only=True)
    md = model.state_dict()
    sd = {k: v for k, v in sd.items() if k in md and md[k].shape == v.shape}
    model.load_state_dict(sd, strict=False)
    model.eval()
    return model


# ---------------------------------------------------------------- episode machinery
def _acts(gc, sts):
    return sts.get_legal_game_actions(gc)


_WEIGHT_OVERRIDE = None

_BOSS_ENCOUNTERS = {'SLIME_BOSS', 'HEXAGHOST', 'THE_GUARDIAN', 'CHAMP', 'COLLECTOR',
                    'AUTOMATON', 'DONU_AND_DECA', 'TIME_EATER', 'AWAKENED_ONE', 'THE_HEART'}


def _is_boss_encounter(bc):
    return str(bc.encounter).split('.')[-1] in _BOSS_ENCOUNTERS

# Deck-needs tags (uppercase CardId names) used by scorer='need'.
_NEED_SCALING = {'DEMON_FORM', 'INFLAME', 'SPOT_WEAKNESS', 'LIMIT_BREAK', 'CORRUPTION',
                 'FEEL_NO_PAIN', 'BARRICADE', 'JUGGERNAUT', 'RUPTURE', 'BERSERK',
                 'FIRE_BREATHING', 'DARK_EMBRACE', 'BRUTALITY'}
_NEED_BLOCK = {'SHRUG_IT_OFF', 'TRUE_GRIT', 'IMPERVIOUS', 'FLAME_BARRIER', 'POWER_THROUGH',
               'GHOSTLY_ARMOR', 'METALLICIZE', 'FEEL_NO_PAIN', 'SECOND_WIND', 'BARRICADE',
               'ENTRENCH', 'ARMAMENTS', 'RAGE', 'PANIC_BUTTON', 'SENTINEL'}
_NEED_STR = {'INFLAME', 'SPOT_WEAKNESS', 'DEMON_FORM', 'LIMIT_BREAK', 'FLEX', 'JAX',
             'RUPTURE', 'HEAVY_BLADE'}
_NEED_DRAW = {'BATTLE_TRANCE', 'POMMEL_STRIKE', 'OFFERING', 'BURNING_PACT', 'DARK_EMBRACE',
              'EVOLVE', 'SKIM', 'WARCRY', 'SHRUG_IT_OFF'}
_NEED_AOE = {'CLEAVE', 'WHIRLWIND', 'IMMOLATE', 'THUNDERCLAP', 'REAPER', 'FIEND_FIRE',
             'COMBUST', 'SEARING_BLOW'}
# Energy generation: the boss-relic experiment showed this agent is energy
# starved (demoting energy relics costs 5.7 points of win rate).
_NEED_ENERGY = {'SEEING_RED', 'BLOODLETTING', 'OFFERING', 'BERSERK', 'CORRUPTION',
                'SENTINEL', 'DUAL_WIELD'}


# Tunable need weights (scaling, block, strength, draw, aoe, premium, overall scale).
_NEED_DEFAULT = dict(scaling=0.8, block=0.6, strength=0.4, draw=0.4, aoe=0.4,
                     premium=0.0, scale=1.0, sustain=0.0, balance=0.0, block_act3=1.0)
_NEED_SUSTAIN = {'REAPER', 'FEED'}
_NEED_W = dict(_NEED_DEFAULT)


def set_need_weights(d):
    _NEED_W.clear()
    _NEED_W.update(_NEED_DEFAULT)
    _NEED_W.update({k: float(v) for k, v in (d or {}).items()})


def _count_names(cnt, names):
    total = 0
    for n in names:
        i = CARD_IDX.get(n)
        if i is not None:
            total += cnt[2 * i] + cnt[2 * i + 1]
    return total


def _count_attacks(cnt):
    tot = 0
    for i in range(len(CARD_TYPE)):
        if int(CARD_TYPE[i]) == 0:
            tot += cnt[2 * i] + cnt[2 * i + 1]
    return tot


def need_bonus(c, cnt, act=0):
    nm = c.id.name
    deck_n = float(cnt.sum())
    w = _NEED_W
    b = 0.0
    if nm in _NEED_SCALING and _count_names(cnt, _NEED_SCALING) == 0:
        b += w['scaling']
    if nm in _NEED_BLOCK and _count_names(cnt, _NEED_BLOCK) < max(4.0, 0.2 * deck_n):
        b += w['block'] * (w['block_act3'] if act >= 3 else 1.0)
    if w['sustain'] > 0 and nm in _NEED_SUSTAIN and _count_names(cnt, _NEED_SUSTAIN) == 0:
        b += w['sustain']
    if w['balance'] > 0 and deck_n > 0:
        atk = _count_attacks(cnt)
        if c.type == 0 and atk > 0.55 * deck_n:
            b -= w['balance']
        elif c.type == 1 and atk > 0.55 * deck_n:
            b += 0.6 * w['balance']
    if nm in _NEED_STR and _count_names(cnt, _NEED_STR) < 2:
        b += w['strength']
    if nm in _NEED_DRAW and _count_names(cnt, _NEED_DRAW) < 2:
        b += w['draw']
    if nm in _NEED_AOE and _count_names(cnt, _NEED_AOE) == 0:
        b += w['aoe']
    if w.get('energy', 0.0) > 0 and nm in _NEED_ENERGY \
            and _count_names(cnt, _NEED_ENERGY) < 2:
        b += w['energy']
    if w['premium'] > 0 and CARD_WEIGHT[CARD_IDX.get(nm, 0)] >= 0.8:
        mx = 0.0
        for i in range(len(CARD_WEIGHT)):
            if (cnt[2 * i] + cnt[2 * i + 1]) > 0:
                mx = max(mx, float(CARD_WEIGHT[i]))
        if mx < 0.8:
            b += w['premium']
    return b * w['scale']



# ---------------------------------------------------------------- card tiering
# Hand-authored Ironclad A0 ranking.  The ArmG scorer imitates the native
# expert (a mediocre player), so its z-score is only used as a contextual
# prior; the tier of the card decides whether it is worth a deck slot.
_TIER = {
    # S: build-around / premium
    'CORRUPTION': 2.0, 'FEEL_NO_PAIN': 2.0, 'DARK_EMBRACE': 1.8, 'BARRICADE': 2.0,
    'DEMON_FORM': 2.0, 'IMPERVIOUS': 1.8, 'OFFERING': 1.8, 'WHIRLWIND': 1.5,
    'REAPER': 1.8, 'FEED': 1.6, 'LIMIT_BREAK': 1.6, 'BLUDGEON': 1.5,
    'IMMOLATE': 1.4, 'FIEND_FIRE': 1.6, 'JUGGERNAUT': 1.3, 'APOTHEOSIS': 2.0,
    'MASTER_OF_STRATEGY': 1.6, 'HAND_OF_GREED': 1.2, 'RITUAL_DAGGER': 1.0,
    # A: strong, usually take
    'INFLAME': 1.0, 'SHRUG_IT_OFF': 1.0, 'UPPERCUT': 1.0, 'POMMEL_STRIKE': 0.9,
    'BATTLE_TRANCE': 0.9, 'ARMAMENTS': 0.9, 'TRUE_GRIT': 0.8, 'METALLICIZE': 0.8,
    'FLAME_BARRIER': 0.9, 'POWER_THROUGH': 0.9, 'SECOND_WIND': 0.8,
    'BURNING_PACT': 0.7, 'SHOCKWAVE': 0.8, 'DISARM': 0.9, 'GHOSTLY_ARMOR': 0.6,
    'SENTINEL': 0.6, 'SEEING_RED': 0.7, 'BLOODLETTING': 0.8, 'EVOLVE': 0.8,
    'SPOT_WEAKNESS': 1.0, 'THUNDERCLAP': 0.7, 'CLEAVE': 0.6, 'CARNAGE': 0.8,
    'HEAVY_BLADE': 0.8, 'RAGE': 0.5, 'RUPTURE': 0.8, 'ENTRENCH': 0.8,
    'BODY_SLAM': 0.9, 'HEADBUTT': 0.6, 'BLOOD_FOR_BLOOD': 0.5,
    'PANIC_BUTTON': 0.5, 'RAMPAGE': 0.5, 'DARK_SHACKLES': 0.7, 'DUAL_WIELD': 0.5,
    'INTIMIDATE': 0.6, 'SWORD_BOOMERANG': 0.6, 'TWIN_STRIKE': 0.5,
    'SEARING_BLOW': 0.6, 'MAYHEM': 0.6, 'SADISTIC_NATURE': 0.6,
    'THE_BOMB': 0.4, 'FINESSE': 0.4, 'PANACEA': 0.5, 'TRIP': 0.4,
    'MADNESS': 0.4, 'DEEP_BREATH': 0.3,
    # B: filler
    'CLOTHESLINE': 0.3, 'IRON_WAVE': 0.3, 'PERFECTED_STRIKE': 0.25, 'PUMMEL': 0.3,
    'HEMOKINESIS': 0.3, 'FIRE_BREATHING': 0.3, 'COMBUST': 0.3, 'BERSERK': 0.2,
    'BRUTALITY': 0.3, 'INFERNAL_BLADE': 0.2, 'JAX': 0.2, 'FLEX': 0.1,
    'STACK': 0.1, 'BODY_SLAM': 0.9, 'SEVER_SOUL': 0.2,
    # C: avoid
    'CLASH': -1.0, 'WILD_STRIKE': -0.8, 'RECKLESS_CHARGE': -0.8, 'DROPKICK': -0.8,
    'HAVOC': -0.6, 'WARCRY': -0.5, 'ANGER': -0.6, 'SWIFT_STRIKE': 0.0,
}
_PAIRS = {
    'FEEL_NO_PAIN': ('CORRUPTION', 'DARK_EMBRACE', 'SECOND_WIND'),
    'DARK_EMBRACE': ('CORRUPTION', 'FEEL_NO_PAIN'),
    'CORRUPTION': ('FEEL_NO_PAIN', 'DARK_EMBRACE', 'SENTINEL', 'SECOND_WIND'),
    'BODY_SLAM': ('BARRICADE', 'ENTRENCH', 'JUGGERNAUT', 'METALLICIZE'),
    'ENTRENCH': ('BARRICADE', 'BODY_SLAM'),
    'LIMIT_BREAK': ('DEMON_FORM', 'INFLAME', 'SPOT_WEAKNESS'),
    'HEAVY_BLADE': ('DEMON_FORM', 'INFLAME', 'LIMIT_BREAK'),
    'WHIRLWIND': ('DEMON_FORM', 'INFLAME', 'LIMIT_BREAK'),
    'JUGGERNAUT': ('BARRICADE', 'METALLICIZE', 'FEEL_NO_PAIN'),
    'RUPTURE': ('BLOODLETTING', 'BRUTALITY', 'OFFERING'),
    'EVOLVE': ('FIRE_BREATHING', 'WILD_STRIKE'),
    'IMPERVIOUS': (),
}
def _copies(cnt, nm):
    i = CARD_IDX.get(nm)
    if i is None:
        return 0
    return int(cnt[2 * i] + cnt[2 * i + 1])


def tier_score(c, cnt, syn_w=0.0):
    nm = c.id.name
    b = _TIER.get(nm, 0.0)
    if syn_w > 0:
        for mate in _PAIRS.get(nm, ()):
            if _copies(cnt, mate) > 0:
                b += syn_w
                break
    # diminishing returns on duplicates of the same card
    n = _copies(cnt, nm)
    if n >= 2:
        b -= 0.5 * n
    return b



# ---------------------------------------------------------------- event choices
_CURSE_NAMES = {'INJURY', 'DECAY', 'PARASITE', 'WRITHE', 'PAIN', 'REGRET', 'SHAME', 'DOUBT',
                'NORMALITY', 'CLUMSY', 'CURSE_OF_THE_BELL', 'NECRONOMICURSE', 'ASCENDERS_BANE'}


def _relic_ids(gc):
    out = []
    for r in gc.relics:
        try:
            out.append(str(r.id).split('.')[-1].split(':')[0])
        except Exception:
            out.append('?')
    return out


def _deck_curse_count(gc):
    n = 0
    for c in gc.deck:
        try:
            if c.id.name in _CURSE_NAMES:
                n += 1
        except Exception:
            pass
    return n


def event_option_score(gc, ctx):
    """Heuristic value of one event option, judged by its immediate effects."""
    s = 0.0
    try:
        s += 4.0 * (ctx.max_hp - gc.max_hp)
        s += 0.10 * (ctx.gold - gc.gold)
        s += 0.40 * (ctx.cur_hp - gc.cur_hp)
        s += 8.0 * (len(ctx.relics) - len(gc.relics))
        s += 1.5 * (len(ctx.deck) - len(gc.deck))
        s -= 6.0 * (_deck_curse_count(ctx) - _deck_curse_count(gc))
        before = _relic_ids(gc)
        after = _relic_ids(ctx)
        if 'BURNING_BLOOD' in before and 'BURNING_BLOOD' not in after:
            s -= 1000.0
        if 'BURNING_BLOOD' not in before and 'BURNING_BLOOD' in after:
            s += 1000.0
        # leaving a boss-relic swap is right even if another boss relic is good
        new_boss = set(after) - set(before)
        for nm in ('VELVET_CHOKER', 'PHILOSOPHERS_STONE', 'ECTOPLASM', 'SOZU', 'BUSTED_CROWN',
                   'MARK_OF_PAIN', 'FUSION_HAMMER', 'RUNIC_DOME', 'CURSED_KEY'):
            if nm in new_boss:
                s -= 6.0
    except Exception:
        return -1e9
    return s


def choose_event(gc, actions, mode='neow'):
    """Pick an event option by cloning the run and scoring each outcome."""
    if not mode:
        return None
    if mode == 'neow' and not (gc.act == 1 and gc.floor_num <= 1):
        return None
    if len(actions) < 2:
        return None
    best, best_s = None, None
    for i, a in enumerate(actions):
        try:
            ctx = gc.clone()
            a(ctx)
            sc = event_option_score(gc, ctx)
        except Exception:
            sc = -1e9
        if best_s is None or sc > best_s:
            best, best_s = i, sc
    if best_s is not None and best_s <= -1e8:
        return None
    return best



# ---------------------------------------------------------------- routing
def _room_type(gc, a):
    try:
        return str(gc.map_node_room(a.idx1, gc.cur_map_node_y + 1)).split('.')[-1]
    except Exception:
        return '?'


def choose_map(gc, actions, mode='heur'):
    """One-step routing heuristic; returns None to fall back to ArmG."""
    hp = gc.cur_hp / max(1, gc.max_hp)
    gold = gc.gold
    act = gc.act
    best_i, best_s = None, None
    for i, a in enumerate(actions):
        room = _room_type(gc, a)
        s = {'TREASURE': 2.5, 'REST': 1.2, 'SHOP': 0.6, 'EVENT': 0.5, 'MONSTER': 0.0,
             'ELITE': 0.4}.get(room, 0.0)
        if room == 'REST':
            s += 1.3 if hp < 0.65 else -0.3
        elif room == 'ELITE':
            s += 1.6 if hp >= 0.85 else -1.8
            if act >= 3:
                s -= 0.4
        elif room == 'SHOP':
            s += 0.9 if gold >= 150 else -0.4
        elif room == 'MONSTER':
            s -= 0.8 if hp < 0.5 else 0.0
        if best_s is None or s > best_s:
            best_i, best_s = i, s
    return best_i


def set_weight_override(d):
    global _WEIGHT_OVERRIDE
    _WEIGHT_OVERRIDE = d


def card_weight(c):
    base = CARD_WEIGHT[CARD_IDX.get(c.id.name, 0)]
    if _WEIGHT_OVERRIDE and c.id.name in _WEIGHT_OVERRIDE:
        base = float(_WEIGHT_OVERRIDE[c.id.name])
    return base * (1.5 if c.upgraded else 1.0)



# ---------------------------------------------------------------- boss / hp aware pick
_AOE = {'CLEAVE', 'WHIRLWIND', 'IMMOLATE', 'REAPER', 'THUNDERCLAP', 'DIE_DIE_DIE',
        'SWORD_BOOMERANG', 'CARNAGE'}
_SCALE = {'DEMON_FORM', 'LIMIT_BREAK', 'INFLAME', 'SPOT_WEAKNESS', 'RUPTURE',
          'JUGGERNAUT', 'BARRICADE', 'ENTRENCH', 'FEED', 'RAMPAGE', 'HEAVY_BLADE'}
_DEFENSIVE = {'METALLICIZE', 'SHRUG_IT_OFF', 'TRUE_GRIT', 'IMPERVIOUS', 'FEEL_NO_PAIN',
              'POWER_THROUGH', 'FLAME_BARRIER', 'GHOSTLY_ARMOR', 'SECOND_WIND',
              'BLOODLETTING', 'BURNING_PACT', 'OFFERING', 'BATTLE_TRANCE', 'SEEING_RED',
              'ARMAMENTS', 'RECKLESS_CHARGE', 'RUPTURE', 'REAPER', 'FEED'}


_POWERS = {'INFLAME', 'METALLICIZE', 'DEMON_FORM', 'FEEL_NO_PAIN', 'DARK_EMBRACE',
           'CORRUPTION', 'BARRICADE', 'JUGGERNAUT', 'RUPTURE', 'EVOLVE', 'FIRE_BREATHING',
           'BERSERK', 'BRUTALITY', 'COMBUST', 'THORNS', 'MAYHEM', 'SELF_FORM', 'MAGNETISM'}
_CHEAP = {'FLEX', 'ANGER', 'WARCRY', 'HAVOC', 'SWORD_BOOMERANG', 'CLASH',
          'TWIN_STRIKE', 'HEADBUTT', 'SHOCKWAVE', 'BLOODLETTING', 'SEEING_RED',
          'PANIC_BUTTON', 'DISARM', 'RAGE', 'BATTLE_TRANCE', 'POMMEL_STRIKE',
          'TRUE_GRIT', 'INTIMIDATE', 'SPOT_WEAKNESS', 'BODY_SLAM'}
_EXPENSIVE = {'BLUDGEON', 'IMPERVIOUS', 'DEMON_FORM', 'BARRICADE', 'LIMIT_BREAK',
              'WHIRLWIND', 'REAPER', 'CARNAGE', 'ENTRENCH', 'HEAVY_BLADE', 'JUGGERNAUT',
              'FIEND_FIRE', 'OFFERING', 'DARK_EMBRACE', 'CORRUPTION', 'FEEL_NO_PAIN',
              'IMPERVIOUS', 'BLOOD_FOR_BLOOD', 'POWER_THROUGH', 'BATTLE_TRANCE'}


def boss_bonus(c, boss):
    """Draft adjustment for the boss of the current act."""
    nm = c.id.name
    b = 0.0
    if boss == 'AWAKENED_ONE':
        if nm in _POWERS:          # gains strength for every power played
            b -= 0.7
    elif boss == 'TIME_EATER':     # punishes many cheap cards
        if nm in _EXPENSIVE:
            b += 0.45
        elif nm in _CHEAP:
            b -= 0.35
    elif boss == 'DONU_AND_DECA':  # two 250hp bodies, long fight
        if nm in _AOE:
            b += 0.55
        if nm in _SCALE:
            b += 0.35
    elif boss in ('CHAMP', 'COLLECTOR', 'AUTOMATON'):
        if nm in _SCALE:
            b += 0.2
    return b


def hp_bonus(c, hp_frac):
    """When health is low, prefer cards that save or restore it."""
    nm = c.id.name
    b = 0.0
    if hp_frac < 0.55:
        if nm in _DEFENSIVE:
            b += 0.35
        if nm not in _SCALE and nm not in _DEFENSIVE and nm not in _AOE:
            b -= 0.15
    elif hp_frac > 0.85:
        if nm in _SCALE:
            b += 0.15
    return b


_NC_Z = {}


def choose_noncombat(gc, agnet, kind, descs, actions, rng, eps=0.0, model=None, obs=None, cnt=None,
                     junk=True, rest_smith=0.6, shop_remove=0, map_elite=0.0, card_margin=0.0,
                     pick='delta', shop_mode='armg', shop_w=0.0, skip_mode='model',
                     scorer='armg', remove_min=3, boss_rest=0.0, boss_win=2, boss_act=2,
                     tier_w=0.0, syn_w=0.0, skip_deck=0, skip_tier=0.0,
                     deck_pen=None,
                     elite_hp=None, rest_hp=0.0, event_pick=None, map_pick=None,
                     boss_aware=False, hp_aware=False, shop_remove_first=0,
                     shop_potion=0, net_w=1.0, card_random=0):
    """Return the chosen index.  Card rewards use the delta head when a model is given."""
    sts = V2.sts
    if kind == 'shop' and shop_mode != 'armg':
        acts = sts.get_legal_game_actions(gc)
        types = [str(a.rewards_action_type) for a in acts]
        ri = next((i for i, t in enumerate(types) if 'RELIC' in t), None)
        _deck = list(gc.deck)
        _basics = sum(1 for c in _deck
                      if CARD_STRIKE[CARD_IDX.get(c.id.name, 0)] or CARD_DEFEND[CARD_IDX.get(c.id.name, 0)])
        xi = None
        if _basics >= remove_min:
            xi = next((i for i, t in enumerate(types) if 'CARD_REMOVE' in t), None)
        if shop_remove_first and xi is not None and _basics >= remove_min \
                and len(_deck) >= shop_remove_first:
            return xi
        if shop_mode in ('remove_relic', 'remove_relic_w') and xi is not None:
            return xi
        if ri is not None and shop_mode in ('junk_relic', 'junk_relic_w', 'relic_remove',
                                            'relic_remove_w', 'remove_relic', 'remove_relic_w'):
            return ri
        if shop_potion and int(gc.act) >= int(shop_potion) and \
                int(gc.potion_count) < int(gc.potion_capacity):
            # Fill free potion slots: potions are worth far more in the act-3
            # boss fight than the gold they cost.
            pi = next((i for i, t in enumerate(types) if 'POTION' in t), None)
            if pi is not None:
                return pi
        if shop_mode in ('relic_remove', 'relic_remove_w') and xi is not None:
            return xi
        sc = list(gc.get_shop_cards())
        cand = []
        for i, a in enumerate(acts):
            t = types[i]
            if 'CARD' in t and 'REMOVE' not in t and 0 <= a.idx1 < len(sc):
                c = sc[a.idx1][0]
                if card_name(c) in JUNK:
                    continue
                if shop_w > 0 and expert_w(c) < shop_w:
                    continue
            cand.append(i)
        with torch.inference_mode():
            scores = agnet.score(torch.tensor(V2.AG.obs_vec(gc)), descs)
        return max(cand, key=lambda i: float(scores[i]))
    if kind == 'shop' and shop_remove:
        price = 75 + 25 * int(gc.shop_remove_count)
        deck = list(gc.deck)
        sd = sum(1 for c in deck if CARD_STRIKE[CARD_IDX.get(c.id.name, 0)] or CARD_DEFEND[CARD_IDX.get(c.id.name, 0)])
        if gc.gold >= price and len(deck) >= 15 and sd >= 3:
            acts = sts.get_legal_game_actions(gc)
            ri = next((i for i, a in enumerate(acts)
                       if 'CARD_REMOVE' in str(a.rewards_action_type)), None)
            if ri is not None:
                return ri
    _elite_thr = 0.0
    if isinstance(map_elite, dict):
        _elite_thr = float(map_elite.get(str(gc.act), map_elite.get(gc.act, 0.0)) or 0.0)
    elif map_elite:
        _elite_thr = float(map_elite)
    if kind == 'map' and elite_hp:
        _hp_frac = gc.cur_hp / max(1, gc.max_hp)
        _avoid = 0.0
        if isinstance(elite_hp, dict):
            _avoid = float(elite_hp.get(str(gc.act), elite_hp.get(gc.act, 0.0)) or 0.0)
        else:
            _avoid = float(elite_hp)
        if _avoid > 0 and _hp_frac < _avoid:
            acts_m = sts.get_legal_game_actions(gc)
            keep = []
            for i, a in enumerate(acts_m):
                try:
                    room = gc.map_node_room(a.idx1, gc.cur_map_node_y + 1)
                    if 'ELITE' in str(room):
                        continue
                except Exception:
                    pass
                keep.append(i)
            if keep and len(keep) < len(acts_m):
                with torch.inference_mode():
                    _ms = agnet.score(torch.tensor(V2.AG.obs_vec(gc)), descs)
                return max(keep, key=lambda i: float(_ms[i]))
    if kind == 'rest' and rest_hp > 0 and gc.cur_hp / max(1, gc.max_hp) < rest_hp:
        acts_r = sts.get_legal_game_actions(gc)
        ri = next((i for i, a in enumerate(acts_r) if a.idx1 == 0), None)
        if ri is not None:
            return ri
    if kind == 'map' and _elite_thr > 0 and gc.cur_hp / max(1, gc.max_hp) >= _elite_thr:
        acts = sts.get_legal_game_actions(gc)
        ei = None
        for i, a in enumerate(acts):
            try:
                room = gc.map_node_room(a.idx1, gc.cur_map_node_y + 1)
                if 'ELITE' in str(room):
                    ei = i
                    break
            except Exception:
                pass
        if ei is not None:
            return ei
    if kind == 'rest' and boss_rest > 0 and gc.act >= boss_act and             gc.cur_hp / max(1, gc.max_hp) < boss_rest:
        _boss_floor = {1: 16, 2: 33, 3: 50}.get(gc.act, 50)
        if gc.floor_num >= _boss_floor - boss_win:
            acts = sts.get_legal_game_actions(gc)
            ri = next((i for i, a in enumerate(acts) if a.idx1 == 0), None)
            if ri is not None:
                return ri
    if kind == 'rest' and rest_smith > 0 and gc.cur_hp / max(1, gc.max_hp) >= rest_smith:
        acts = sts.get_legal_game_actions(gc)
        si = next((i for i, a in enumerate(acts) if a.idx1 == 1), None)
        if si is not None:
            return si
    if kind == 'card' and model is not None:
        offered = list(gc.get_card_reward())
        skip_i = len(actions) - 1
        if not offered:
            return skip_i
        slots = [slot_of(c) for c in offered] + [SKIP_SLOT]
        o = torch.from_numpy(obs).unsqueeze(0)
        c0 = torch.from_numpy(cnt).unsqueeze(0)
        with torch.inference_mode():
            h = model.encode(o, c0)
            if pick == 'abs':
                s0 = model.sc(h)
                ds = []
                for c in offered:
                    c2 = np.array(cnt, dtype=np.float32, copy=True)
                    c2[slot_of(c)] += 1.0
                    h2 = model.encode(o, torch.from_numpy(c2).unsqueeze(0))
                    ds.append(float((model.sc(h2) - s0)[0]))
                di = ds + [0.0]
            else:
                di = model.delta(h, torch.tensor(slots)).tolist()
                if pick == 'hybrid' and len(descs) == len(di):
                    ag = [float(x) for x in agnet.score(torch.tensor(V2.AG.obs_vec(gc)), descs)]

                    def _rank(v):
                        order = sorted(range(len(v)), key=lambda i: v[i])
                        r = [0.0] * len(v)
                        for k, i in enumerate(order):
                            r[i] = k / max(1, len(v) - 1)
                        return r
                    ra, rm = _rank(ag), _rank(di)
                    di = [ra[i] + 0.5 * rm[i] for i in range(len(di))]
        if junk:
            for i, c in enumerate(offered):
                if card_name(c) in JUNK:
                    di[i] = -1e9
        if skip_mode == 'never' and any(di[i] > -1e8 for i in range(len(offered))):
            return max(range(len(offered)), key=lambda i: di[i])
        best = max(range(len(di)), key=lambda i: di[i])
        if best == len(offered) or di[best] - di[len(offered)] <= card_margin:
            return skip_i
        return best
    if kind == 'map' and map_pick:
        _mi = choose_map(gc, actions, str(map_pick))
        if _mi is not None:
            return _mi
    if kind == 'event' and event_pick:
        _ei = choose_event(gc, actions, str(event_pick))
        if _ei is not None:
            return _ei
    cand = list(range(len(actions)))
    offered = None
    if kind == 'card' and junk:
        offered = list(gc.get_card_reward())
        skip_i = len(actions) - 1
        cand = [i for i, c in enumerate(offered) if card_name(c) not in JUNK] + [skip_i]
    with torch.inference_mode():
        scores = agnet.score(torch.tensor(V2.AG.obs_vec(gc)), descs)
    if kind == 'card' and scorer == 'tier':
        if offered is None:
            offered = list(gc.get_card_reward())
        ag = [float(x) for x in scores]
        mu = sum(ag) / max(1, len(ag))
        sd = (sum((x - mu) ** 2 for x in ag) / max(1, len(ag))) ** 0.5 or 1.0
        z = [(x - mu) / sd for x in ag]
        if net_w != 1.0:
            # weight of the learned card net in the composite score; 0 keeps
            # only the hand-written need bonuses
            z = [net_w * x for x in z]
        nb = [need_bonus(c, cnt, gc.act) for c in offered] + [0.0]
        tb = [tier_score(c, cnt, syn_w) for c in offered] + [0.0]
        scores = torch.tensor([z[i] + nb[i] + tier_w * tb[i] for i in range(len(z))],
                              dtype=torch.float32)
        if skip_deck and len(gc.deck) >= skip_deck:
            skip_i = len(actions) - 1
            best = max(range(len(offered)), key=lambda i: float(scores[i]))
            if tb[best] < skip_tier:
                return skip_i
    if kind == 'card' and scorer in ('need', 'needw'):
        if offered is None:
            offered = list(gc.get_card_reward())
        ag = [float(x) for x in scores]
        mu = sum(ag) / max(1, len(ag))
        sd = (sum((x - mu) ** 2 for x in ag) / max(1, len(ag))) ** 0.5 or 1.0
        z = [(x - mu) / sd for x in ag]
        nb = [need_bonus(c, cnt, gc.act) for c in offered] + [0.0]
        if boss_aware:
            _bn = str(gc.boss).split('.')[-1]
            for _i, _c in enumerate(offered):
                nb[_i] += boss_bonus(_c, _bn)
        if hp_aware:
            _hf = gc.cur_hp / max(1.0, float(gc.max_hp))
            for _i, _c in enumerate(offered):
                nb[_i] += hp_bonus(_c, _hf)
        if scorer == 'needw':
            ws = [card_weight(c) for c in offered] + [0.0]
            wmu = sum(ws) / max(1, len(ws))
            wsd = (sum((x - wmu) ** 2 for x in ws) / max(1, len(ws))) ** 0.5 or 1.0
            wz = [(x - wmu) / wsd for x in ws]
            z = [0.5 * z[i] + 0.5 * wz[i] for i in range(len(z))]
        pen = 0.0
        if deck_pen and len(gc.deck) >= int(deck_pen[0]):
            pen = -float(deck_pen[1]) * (len(gc.deck) - int(deck_pen[0]) + 1)
        scores = torch.tensor([z[i] + nb[i] + (pen if i < len(offered) else 0.0)
                               for i in range(len(z))], dtype=torch.float32)
        _NC_Z.update(raw=[float(x) for x in ag], mu=mu, sd=sd)
    if kind == 'card' and scorer in ('w', 'warm'):
        if offered is None:
            offered = list(gc.get_card_reward())
        ws = [card_weight(c) for c in offered]
        ws = ws + [0.0]
        if scorer == 'w':
            scores = torch.tensor(ws, dtype=torch.float32)
        else:
            ag = [float(x) for x in scores]

            def _rank(v):
                order = sorted(range(len(v)), key=lambda i: v[i])
                r = [0.0] * len(v)
                for k, i in enumerate(order):
                    r[i] = k / max(1, len(v) - 1)
                return r
            ra, rw = _rank(ag), _rank(ws)
            scores = torch.tensor([ra[i] + rw[i] for i in range(len(ra))], dtype=torch.float32)
    if card_random and kind == 'card':
        # uniform pick among the non-junk candidates (plus skip): a floor for how
        # much the card-ranking policy is worth at all
        return rng.choice(cand)
    if _SAMPLE_TAU > 0.0:
        global _SAMPLE_OUT
        _idx = [int(i) for i in cand]
        _raw = _NC_Z.get('raw')
        _mu = float(_NC_Z.get('mu', 0.0))
        _sd = float(_NC_Z.get('sd', 1.0)) or 1.0
        _sv = [float(scores[i]) for i in range(len(scores))]
        if _raw is not None and len(_raw) == len(_sv):
            _off = [_sv[i] - (_raw[i] - _mu) / _sd for i in range(len(_sv))]
        else:
            _off = list(_sv)
        _t = torch.tensor([_sv[i] for i in _idx])
        _k = int(torch.multinomial(torch.softmax(_t / _SAMPLE_TAU, dim=0), 1).item())
        _SAMPLE_OUT = dict(cand=_idx, offsets=_off, mu=_mu, sd=_sd, kind=kind)
        return _idx[_k]
    # Deck-quality gate: once the deck is long enough, skip rewards whose best
    # option is a genuinely weak card.  Applies to every scorer.
    if kind == 'card' and skip_deck and len(gc.deck) >= skip_deck:
        if offered is None:
            offered = list(gc.get_card_reward())
        skip_i = len(actions) - 1
        best = max(cand, key=lambda i: float(scores[i])) if cand else skip_i
        if best < len(offered):
            _c = cnt if cnt is not None else deck_counts(gc.deck)
            if tier_score(offered[best], _c, syn_w) < skip_tier:
                return skip_i
    if eps > 0 and rng.random() < eps:
        return rng.choice(cand)
    return max(cand, key=lambda i: float(scores[i]))



# ---------------------------------------------------------------- upgrade priority
# Value of spending a smith on this card.  Falls back to the pick tier.
_UPG = {
    'BASH': 3.0, 'CORRUPTION': 3.0, 'BODY_SLAM': 2.5, 'FEEL_NO_PAIN': 2.5,
    'DARK_EMBRACE': 2.5, 'DEMON_FORM': 2.5, 'LIMIT_BREAK': 2.5, 'SHRUG_IT_OFF': 2.2,
    'TRUE_GRIT': 2.2, 'POMMEL_STRIKE': 2.2, 'UPPERCUT': 2.2, 'BARRICADE': 2.0,
    'ENTRENCH': 2.0, 'IMPERVIOUS': 2.0, 'BLUDGEON': 2.0, 'WHIRLWIND': 2.0,
    'REAPER': 2.0, 'ARMAMENTS': 1.8, 'BATTLE_TRANCE': 1.8, 'IMPERVIOUS': 2.0,
    'INFLAME': 1.6, 'METALLICIZE': 1.6, 'POWER_THROUGH': 1.6, 'SECOND_WIND': 1.6,
    'FLAME_BARRIER': 1.6, 'SEEING_RED': 1.6, 'BLOODLETTING': 1.6, 'EVOLVE': 1.6,
    'SPOT_WEAKNESS': 1.6, 'HEAVY_BLADE': 1.6, 'JUGGERNAUT': 1.6, 'FIEND_FIRE': 1.6,
    'OFFERING': 1.6, 'BURNING_PACT': 1.4, 'DISARM': 1.4, 'SHOCKWAVE': 1.4,
    'GHOSTLY_ARMOR': 1.2, 'SENTINEL': 1.2, 'HEADBUTT': 1.2, 'CARNAGE': 1.4,
    'THUNDERCLAP': 1.2, 'CLEAVE': 1.0, 'RAGE': 1.0, 'RUPTURE': 1.4,
    'RAMPAGE': 1.0, 'SEARING_BLOW': 1.2, 'DARK_SHACKLES': 1.0, 'INTIMIDATE': 1.0,
}


_UPG_EXTRA = {}

# Training-time sampling hook: when _SAMPLE_TAU > 0 choose_noncombat samples from
# softmax(composite scores / tau) instead of taking the argmax, and exposes the
# candidate list, the z-transform parameters and the per-candidate offsets
# (everything in the final score that is not the net's own z-scored output) so a
# driver can recompute the same distribution with gradients.
_SAMPLE_TAU = 0.0
_SAMPLE_OUT = None


def set_sampling(tau):
    global _SAMPLE_TAU, _SAMPLE_OUT
    _SAMPLE_TAU = float(tau)
    _SAMPLE_OUT = None


def sample_out():
    return _SAMPLE_OUT


def upgrade_priority(card):
    nm = card.id.name
    if nm in _UPG:
        return _UPG[nm]
    if _UPG_EXTRA and nm in _UPG_EXTRA:
        return _UPG_EXTRA[nm]
    return _TIER.get(nm, 0.2)


def _new_agent(sts):
    ag = sts.Agent(); ag.simulation_count_base = 2000
    V2.SP._set_all_pauses(ag)
    try:
        ag.pause_on_card_select = True
    except Exception:
        pass
    return ag


T_UPGRADE = 3   # CardSelectScreenType::UPGRADE


def _handle_card_select(gc, target='low'):
    """Pick a card on an upgrade/remove/transform screen.  Returns False if none."""
    sts = V2.sts
    cards = list(gc.select_screen_cards)
    acts = sts.get_legal_game_actions(gc)
    if not cards or not acts:
        return False
    ws = []
    for c in cards:
        i = CARD_IDX.get(c.id.name, 0)
        ws.append(float(CARD_WEIGHT[i]) * (1.5 if c.upgraded else 1.0))
    if gc.select_screen_type == T_UPGRADE and target == 'tier':
        idx = max(range(len(cards)), key=lambda i: upgrade_priority(cards[i]))
    elif gc.select_screen_type == T_UPGRADE and target == 'high':
        idx = max(range(len(ws)), key=lambda i: ws[i])
    else:
        idx = min(range(len(ws)), key=lambda i: ws[i])
    acts[idx].execute(gc)
    return True


def _play_out(ctx, agnet, policy, value, cfg, rng, mode='puct_greedy_timed', max_screens=900,
              smith_target='low'):
    """Advance a cloned GameContext to a terminal state with the base policy."""
    sts = V2.sts
    ag = _new_agent(sts)
    for _ in range(max_screens):
        if ctx.outcome != sts.GameOutcome.UNDECIDED:
            break
        ag.playout(ctx)
        if ctx.outcome != sts.GameOutcome.UNDECIDED:
            break
        if ctx.screen_state == sts.ScreenState.CARD_SELECT and _handle_card_select(ctx, smith_target):
            continue
        if ctx.screen_state == sts.ScreenState.BATTLE:
            bc = sts.BattleContext(); bc.init(ctx)
            V2.run_battle_eval(bc, policy, value, cfg, rng, mode)
            if bc.outcome == sts.Outcome.UNDECIDED:
                bc.exit_battle(ctx)
                raise RuntimeError('battle truncated')
            bc.exit_battle(ctx)
            continue
        kind, descs, actions = V2.AG.build_choices(ctx)
        if not descs:
            if ctx.screen_state == sts.ScreenState.REWARDS:
                ctx.skip_reward_cards(); continue
            raise RuntimeError('no noncombat actions: ' + kind)
        idx = choose_noncombat(ctx, agnet, kind, descs, actions, rng, eps=0.0, model=None,
                               junk=True, rest_smith=0.6)
        actions[idx](ctx)
    if ctx.outcome == sts.GameOutcome.UNDECIDED:
        raise RuntimeError('run truncated')
    return dict(win=ctx.outcome == sts.GameOutcome.PLAYER_VICTORY, floor=ctx.floor_num,
                act=ctx.act, hp_frac=ctx.cur_hp / max(1, ctx.max_hp))


def run_episode(job):
    seed, wp, wv, cfg, eps, mode, model_path, opts = job
    init_vocab()
    _sts0 = V2.sts
    try:
        _sts0.set_playout_target(int(opts.get('playout_target', 0)))
        _sts0.set_playout_order(int(opts.get('playout_order', 0)))
        _sts0.set_save_potions(bool(opts.get('save_potions', 0)))
        _sts0.set_win_hp_weight(float(opts.get('win_hp_weight', 1.0)))
        if hasattr(_sts0, 'set_boss_relic_mode'):
            _sts0.set_boss_relic_mode(int(opts.get('boss_relic_mode', 0) or 0))
        global _UPG_EXTRA
        _UPG_EXTRA = opts.get('upg_extra') or {}
    except AttributeError:
        pass
    if opts.get('wfile'):
        set_weight_override(json.loads(Path(opts['wfile']).read_text()))
    set_need_weights(opts.get('need_w') or {})
    sts = V2.sts
    policy, value = V2.load_nets(wp, wv)
    if opts.get('ens'):
        # Average the policy heads of several self-play rounds.
        import os.path as _op
        _dir = _op.dirname(str(wp))
        _nets = []
        for _n in opts['ens']:
            _pp, _vv = V2.load_nets(_op.join(_dir, 'round%d_policy.pt' % int(_n)),
                                    _op.join(_dir, 'round%d_value.pt' % int(_n)))
            _nets.append(_pp)
        policy = V2.EnsemblePolicy(_nets)
    agnet = load_card_net(opts.get('card_model')) if opts.get('card_model') else V2.load_armg()
    model = None
    if model_path:
        model = load_deck_value(model_path)
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = _new_agent(sts)
    rng = random.Random(seed * 7919 + 13)
    records = []; battles = []
    for _ in range(600):
        if gc.outcome != sts.GameOutcome.UNDECIDED:
            break
        ag.playout(gc)
        if gc.outcome != sts.GameOutcome.UNDECIDED:
            break
        if gc.screen_state == sts.ScreenState.CARD_SELECT and \
                _handle_card_select(gc, opts.get('smith_target', 'low')):
            continue
        if gc.screen_state == sts.ScreenState.BATTLE:
            bc = sts.BattleContext(); bc.init(gc)
            _fpw = opts.get('final_pot_w')
            _pw = opts.get('pot_w')
            if _fpw is not None or _pw is not None:
                # Value of an unused potion in the search's battle evaluation.
                # Unused potions are worth nothing once the run ends (floor 50),
                # and possibly less than 4 elsewhere if the agent hoards them.
                _pval = float(_pw) if _pw is not None else 4.0
                if _fpw is not None and int(gc.floor_num) >= 50:
                    _pval = float(_fpw)
                try:
                    sts.set_win_potion_weight(_pval)
                except AttributeError:
                    pass
            cfg_b = cfg
            if opts.get('boss_ms'):
                _ms = float(opts['boss_ms']) if _is_boss_encounter(bc) else float(opts.get('hall_ms', 40.0))
                cfg_b = base_cfg(_ms)
            stats, vals = V2.run_battle_eval(bc, policy, value, cfg_b, rng, 'puct_greedy_timed')
            stats['floor'] = int(gc.floor_num)
            battles.append(stats)
            if bc.outcome == sts.Outcome.UNDECIDED:
                raise RuntimeError('Battle truncated before terminal')
            bc.exit_battle(gc)
            continue
        kind, descs, actions = V2.AG.build_choices(gc)
        if not descs:
            if gc.screen_state == sts.ScreenState.REWARDS:
                gc.skip_reward_cards(); continue
            raise RuntimeError('No noncombat actions: ' + kind)
        obs = zero_obs(V2.AG.obs_vec(gc))
        cnt = deck_counts(gc.deck)
        offered_slots = None
        if kind == 'card':
            offered_slots = [slot_of(c) for c in gc.get_card_reward()]
        idx = choose_noncombat(gc, agnet, kind, descs, actions, rng, eps=eps,
                               model=model, obs=obs, cnt=cnt,
                               junk=opts.get('junk', 1), rest_smith=opts.get('rest_smith', 0.6),
                               shop_remove=opts.get('shop_remove', 0), map_elite=opts.get('map_elite', 0.0),
                               card_margin=opts.get('card_margin', 0.0), pick=opts.get('pick', 'delta'),
                               shop_mode=opts.get('shop_mode', 'armg'),
                               shop_w=opts.get('shop_w', 0.0),
                               skip_mode=opts.get('skip_mode', 'model'),
                               scorer=opts.get('scorer', 'armg'),
                               remove_min=opts.get('remove_min', 3),
                               boss_rest=opts.get('boss_rest', 0.0),
                               boss_win=opts.get('boss_win', 2),
                               boss_act=opts.get('boss_act', 2),
                               tier_w=opts.get('tier_w', 0.0),
                               syn_w=opts.get('syn_w', 0.0),
                               skip_deck=opts.get('skip_deck', 0),
                               skip_tier=opts.get('skip_tier', 0.0),
                               deck_pen=opts.get('deck_pen'),
                               elite_hp=opts.get('elite_hp'),
                               rest_hp=opts.get('rest_hp', 0.0),
                               event_pick=opts.get('event_pick'),
                               boss_aware=opts.get('boss_aware', 0),
                               hp_aware=opts.get('hp_aware', 0),
                               shop_remove_first=opts.get('shop_remove_first', 0),
                               shop_potion=opts.get('shop_potion', 0),
                               net_w=opts.get('net_w', 1.0),
                               card_random=opts.get('card_random', 0),
                               map_pick=opts.get('map_pick'))
        if len(actions) > 1:
            records.append(dict(obs=obs, cnt=cnt, kind=kind, n=len(actions), chosen=idx,
                                offered=offered_slots, act=gc.act, floor=gc.floor_num,
                                hp=gc.cur_hp / max(1, gc.max_hp), gold=gc.gold))
        actions[idx](gc)
    if gc.outcome == sts.GameOutcome.UNDECIDED:
        raise RuntimeError('Run truncated before terminal')
    result = dict(seed=seed, floor=gc.floor_num, win=gc.outcome == sts.GameOutcome.PLAYER_VICTORY,
                  act=gc.act, hp_frac=gc.cur_hp / max(1, gc.max_hp), deck=len(gc.deck),
                  records=records, battles=battles)
    if mode == 'eval':
        result['records'] = []
    return result


def run_branch_episode(job):
    """Play one episode and branch every card reward into per-candidate outcomes."""
    seed, wp, wv, cfg, cont_ms, opts = job
    init_vocab()
    sts = V2.sts
    try:
        sts.set_save_potions(bool(opts.get('save_potions', 0)))
    except AttributeError:
        pass
    policy, value = V2.load_nets(wp, wv)
    agnet = V2.load_armg()
    cont_cfg = dict(cfg); cont_cfg['eval_timed_ms'] = float(cont_ms)
    gc = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
    ag = _new_agent(sts)
    rng = random.Random(seed * 7919 + 13)
    decisions = []; battles = []
    max_dec = int(opts.get('max_decisions', 18))
    for _ in range(600):
        if gc.outcome != sts.GameOutcome.UNDECIDED:
            break
        ag.playout(gc)
        if gc.outcome != sts.GameOutcome.UNDECIDED:
            break
        if gc.screen_state == sts.ScreenState.BATTLE:
            bc = sts.BattleContext(); bc.init(gc)
            stats, vals = V2.run_battle_eval(bc, policy, value, cfg, rng, 'puct_greedy_timed')
            battles.append(stats)
            if bc.outcome == sts.Outcome.UNDECIDED:
                raise RuntimeError('Battle truncated before terminal')
            bc.exit_battle(gc)
            continue
        kind, descs, actions = V2.AG.build_choices(gc)
        if not descs:
            if gc.screen_state == sts.ScreenState.REWARDS:
                gc.skip_reward_cards(); continue
            raise RuntimeError('No noncombat actions: ' + kind)
        obs = zero_obs(V2.AG.obs_vec(gc))
        cnt = deck_counts(gc.deck)
        if kind == 'card' and len(actions) >= 2 and len(decisions) < max_dec:
            offered = list(gc.get_card_reward())
            cands = []
            for c in offered:
                ctx = gc.clone()
                ctx.pick_reward_card(c)
                try:
                    o = _play_out(ctx, agnet, policy, value, cont_cfg, random.Random(seed),
                                  'puct_greedy_timed', smith_target=opts.get('smith_target', 'low'))
                    o.update(slot=slot_of(c), ok=True)
                except Exception as e:
                    o = dict(slot=slot_of(c), ok=False, err=str(e)[:100])
                cands.append(o)
            ctx = gc.clone(); ctx.skip_reward_cards()
            try:
                o = _play_out(ctx, agnet, policy, value, cont_cfg, random.Random(seed),
                              'puct_greedy_timed', smith_target=opts.get('smith_target', 'low'))
                o.update(slot=-1, ok=True)
            except Exception as e:
                o = dict(slot=-1, ok=False, err=str(e)[:100])
            cands.append(o)
            decisions.append(dict(obs=obs, cnt=cnt, act=gc.act, floor=gc.floor_num,
                                  hp=gc.cur_hp / max(1, gc.max_hp), gold=gc.gold,
                                  offered=[slot_of(c) for c in offered], cands=cands))
        idx = choose_noncombat(gc, agnet, kind, descs, actions, rng, eps=0.0, model=None,
                               junk=opts.get('junk', 1), rest_smith=opts.get('rest_smith', 0.6))
        actions[idx](gc)
    if gc.outcome == sts.GameOutcome.UNDECIDED:
        raise RuntimeError('Run truncated before terminal')
    return dict(seed=seed, floor=gc.floor_num, win=gc.outcome == sts.GameOutcome.PLAYER_VICTORY,
                act=gc.act, hp_frac=gc.cur_hp / max(1, gc.max_hp), deck=len(gc.deck),
                decisions=decisions, battles=[])


# ---------------------------------------------------------------- commands
def eval_seeds(n, extra=0):
    base = [int(x) for x in (V2.ROOT / 'sts-rl-agent/eval/eval_seeds_50.txt').read_text().splitlines()
            if x.strip() and not x.startswith('#')]
    seeds = list(dict.fromkeys(base))
    rng = random.Random(424242)
    while len(seeds) < len(base) + extra:
        s = rng.randint(1, 10 ** 9)
        if s not in seeds:
            seeds.append(s)
    return seeds[:n]


def train_seeds(n, exclude, offset=0):
    rng = random.Random(20261050 + int(offset))
    out = []
    while len(out) < n:
        s = rng.randint(1, 10 ** 9)
        if s not in exclude and s not in out:
            out.append(s)
    return out


def base_cfg(timed_ms, cpuct=3.0, playout_eps=0.0):
    return dict(eval_sims=512, eval_timed_ms=timed_ms, n_full=1, n_fast=1, p_full=0.0,
                archive_every=0, native_frac=0.0, native_sims=0, root_min_visits=1,
                cpuct_native=cpuct, prior_temp=1.0, puct_prior_mode=0, puct_anneal=0.0,
                uniform_priors=0, restarts=2, value_prior_temp=0.05, play_horizon=2,
                playout_mode=1, playout_eps=playout_eps)


def cmd_collect(a):
    seeds = train_seeds(a.episodes, set(eval_seeds(150)), a.seed_offset)
    wp = str(Path(a.run) / ('round%d_policy.pt' % a.round))
    wv = str(Path(a.run) / ('round%d_value.pt' % a.round))
    cfg = base_cfg(a.timed_ms)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / 'meta.json').write_text(json.dumps(dict(seeds=seeds, timed_ms=a.timed_ms,
                                                   eps=a.eps, run=a.run, round=a.round)))
    jobs = [(s, wp, wv, cfg, a.eps, 'collect', None, dict(junk=a.junk, rest_smith=a.rest_smith,
                            shop_remove=a.shop_remove, map_elite=a.map_elite)) for s in seeds]
    t0 = time.time(); done = 0; shard = []; shard_i = 0
    with ProcessPoolExecutor(max_workers=a.workers, initializer=V2.init_worker,
                             initargs=(a.source,)) as pool:
        for r in pool.map(run_episode, jobs, chunksize=1):
            shard.append(r); done += 1
            if done % a.shard == 0:
                with open(out / ('shard_%03d.pkl' % shard_i), 'wb') as f:
                    pickle.dump(shard, f)
                print('shard', shard_i, 'episodes', done, 'wall %.0fs' % (time.time() - t0), flush=True)
                shard = []; shard_i += 1
    if shard:
        with open(out / ('shard_%03d.pkl' % shard_i), 'wb') as f:
            pickle.dump(shard, f)
    print('collected', done, 'episodes in %.0fs' % (time.time() - t0), flush=True)


def cmd_branch(a):
    seeds = train_seeds(a.episodes, set(eval_seeds(150)), a.seed_offset)
    wp = str(Path(a.run) / ('round%d_policy.pt' % a.round))
    wv = str(Path(a.run) / ('round%d_value.pt' % a.round))
    cfg = base_cfg(a.timed_ms)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    (out / 'meta.json').write_text(json.dumps(dict(seeds=seeds, timed_ms=a.timed_ms,
                                                   cont_ms=a.cont_ms, run=a.run, round=a.round)))
    opts = dict(junk=a.junk, rest_smith=a.rest_smith, max_decisions=a.max_decisions,
                smith_target=a.smith_target)
    jobs = [(s, wp, wv, cfg, a.cont_ms, opts) for s in seeds]
    t0 = time.time(); done = 0; shard = []; shard_i = 0
    with ProcessPoolExecutor(max_workers=a.workers, initializer=V2.init_worker,
                             initargs=(a.source,)) as pool:
        for r in pool.map(run_branch_episode, jobs, chunksize=1):
            shard.append(r); done += 1
            if done % a.shard == 0:
                with open(out / ('shard_%03d.pkl' % shard_i), 'wb') as f:
                    pickle.dump(shard, f)
                print('shard', shard_i, 'episodes', done, 'wall %.0fs' % (time.time() - t0), flush=True)
                shard = []; shard_i += 1
    if shard:
        with open(out / ('shard_%03d.pkl' % shard_i), 'wb') as f:
            pickle.dump(shard, f)
    print('branched', done, 'episodes in %.0fs' % (time.time() - t0), flush=True)


def load_shards(path):
    rows = []
    for part in str(path).split(','):
        for f in sorted(Path(part).glob('shard_*.pkl')):
            with open(f, 'rb') as fh:
                rows.extend(pickle.load(fh))
    return rows


def _abs_loss(model, obs, cnt, sl, win, floor, act, hp):
    h = model.encode(obs, cnt)
    w, f, ac, hh = model.heads(h)
    t = win + 0.5 * floor
    return (F.binary_cross_entropy_with_logits(w, win)
            + 0.5 * F.mse_loss(torch.sigmoid(f), floor)
            + 0.2 * F.cross_entropy(ac, act)
            + 0.2 * F.mse_loss(hh, hp)
            + 0.5 * F.mse_loss(model.sc(h).squeeze(1), t))


def _behavior_arrays(rows, max_rows=20000, seed=7):
    rng = random.Random(seed)
    recs = []
    for r in rows:
        for rec in r.get('records', []):
            if rec.get('kind') != 'card':
                continue
            recs.append((rec, r))
    if len(recs) > max_rows:
        recs = rng.sample(recs, max_rows)
    obs = np.stack([z[0]['obs'] for z in recs])
    cnt = []
    for rec, _ in recs:
        c = np.array(rec['cnt'], dtype=np.float32, copy=True)
        offs = rec.get('offered') or []
        if offs and rec['chosen'] < len(offs):
            c[offs[rec['chosen']]] += 1.0
        cnt.append(c)
    cnt = np.stack(cnt)
    ywin = np.array([1.0 if z[1]['win'] else 0.0 for z in recs], np.float32)
    yfloor = np.array([z[1]['floor'] / 51.0 for z in recs], np.float32)
    yact = np.array([min(2, max(0, z[1]['act'] - 1)) for z in recs], np.int64)
    yhp = np.array([z[1]['hp_frac'] for z in recs], np.float32)
    return (torch.tensor(obs), torch.tensor(cnt), torch.tensor(ywin), torch.tensor(yfloor),
            torch.tensor(yact), torch.tensor(yhp))


def cmd_train(a):
    """Absolute value training on behaviour episodes (old-style targets)."""
    init_vocab()
    rows = load_shards(a.data)
    obs = []; cnt = []; ywin = []; yfloor = []; yact = []; yhp = []; grp = []
    for gi, r in enumerate(rows):
        for rec in r['records']:
            grp.append(gi)
            obs.append(rec['obs']); cnt.append(rec['cnt'])
            ywin.append(1.0 if r['win'] else 0.0)
            yfloor.append(r['floor'] / 51.0)
            yact.append(min(2, max(0, r['act'] - 1)))
            yhp.append(r['hp_frac'])
    print('samples', len(obs), 'episodes', len(rows), flush=True)
    obs = torch.tensor(np.stack(obs)); cnt = torch.tensor(np.stack(cnt))
    ywin = torch.tensor(ywin); yfloor = torch.tensor(yfloor)
    yact = torch.tensor(yact, dtype=torch.long); yhp = torch.tensor(yhp)
    grp = np.asarray(grp)
    rng = np.random.RandomState(1)
    val_groups = set(rng.permutation(len(rows))[:max(1, len(rows) // 10)].tolist())
    is_val = np.array([g in val_groups for g in grp])
    val = torch.tensor(np.where(is_val)[0]); tr = torch.tensor(np.where(~is_val)[0])
    model = DeckValue(); opt = torch.optim.Adam(model.parameters(), lr=a.lr, weight_decay=1e-4)
    best = 1e9
    for ep in range(a.epochs):
        model.train(); perm = tr[torch.randperm(len(tr))]
        tot = 0.0; nb = 0
        for i in range(0, len(perm), a.batch):
            b = perm[i:i + a.batch]
            loss = _abs_loss(model, obs[b], cnt[b], None, ywin[b], yfloor[b], yact[b], yhp[b])
            opt.zero_grad(); loss.backward(); nn.utils.clip_grad_norm_(model.parameters(), 5.0); opt.step()
            tot += float(loss.detach()); nb += 1
        model.eval()
        with torch.inference_mode():
            w, f, ac, hp = model(obs[val], cnt[val])
            p = torch.sigmoid(w)
            mse = F.mse_loss(torch.sigmoid(f), yfloor[val])
            bce = F.binary_cross_entropy_with_logits(w, ywin[val])
            acc = ((p > 0.5).float() == ywin[val]).float().mean()
            sc_mse = F.mse_loss(model.sc(model.encode(obs[val], cnt[val])).squeeze(1),
                                ywin[val] + 0.5 * yfloor[val])
        print('epoch %d loss %.4f | val floor_mse %.4f win_bce %.4f acc %.3f sc_mse %.4f' % (
            ep, tot / max(1, nb), float(mse), float(bce), float(acc), float(sc_mse)), flush=True)
        if float(mse) < best:
            best = float(mse)
            Path(a.out).parent.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), a.out)
    if not Path(a.out).exists():
        torch.save(model.state_dict(), a.out)
    print('saved', a.out, 'best floor_mse %.4f' % best, flush=True)


def _branch_groups(rows):
    groups = []
    for gi, ep in enumerate(rows):
        for dec in ep.get('decisions', []):
            cands = [c for c in dec['cands'] if c.get('ok', False)]
            if len(cands) < 2:
                continue
            if not any(c['slot'] == -1 for c in cands):
                continue
            groups.append((gi, dec, cands))
    return groups


def _branch_arrays(groups):
    G = len(groups)
    K = max(len(c) for _, _, c in groups)
    obs = np.zeros((G, OBS_DIM), np.float32); cnt = np.zeros((G, NSLOTS), np.float32)
    slots = np.full((G, K), SKIP_SLOT, np.int64); mask = np.zeros((G, K), bool)
    win = np.zeros((G, K), np.float32); floor = np.zeros((G, K), np.float32)
    act = np.zeros((G, K), np.int64); hp = np.zeros((G, K), np.float32)
    tgt = np.zeros((G, K), np.float32)
    for gi, (_ep, dec, cands) in enumerate(groups):
        obs[gi] = dec['obs']; cnt[gi] = dec['cnt']
        for k, c in enumerate(cands):
            slots[gi, k] = SKIP_SLOT if c['slot'] == -1 else c['slot']
            mask[gi, k] = True
            win[gi, k] = 1.0 if c['win'] else 0.0
            floor[gi, k] = c['floor'] / 51.0
            act[gi, k] = min(2, max(0, c['act'] - 1))
            hp[gi, k] = c['hp_frac']
            tgt[gi, k] = win[gi, k] + 0.5 * floor[gi, k]
    return dict(obs=torch.tensor(obs), cnt=torch.tensor(cnt), slots=torch.tensor(slots),
                mask=torch.tensor(mask), win=torch.tensor(win), floor=torch.tensor(floor),
                act=torch.tensor(act), hp=torch.tensor(hp), tgt=torch.tensor(tgt))


def cmd_trainx(a):
    init_vocab()
    rows = load_shards(a.data)
    groups = _branch_groups(rows)
    d = _branch_arrays(groups)
    G = len(groups); K = d['slots'].shape[1]
    print('decisions', G, 'candidates/decision', K, 'episodes', len(rows), flush=True)
    if G < a.batch:
        raise SystemExit('not enough branch decisions')
    z = np.arange(G)
    ep_ids = np.array([g[0] for g in groups])
    rng = np.random.RandomState(1)
    n_ep = len(rows)
    val_eps = set(rng.permutation(n_ep)[:max(1, n_ep // 10)].tolist())
    is_val = np.array([e in val_eps for e in ep_ids])
    val = torch.tensor(z[is_val]); tr = torch.tensor(z[~is_val])
    beh = None
    if a.behavior:
        beh = _behavior_arrays(load_shards(a.behavior))
        print('behaviour card rows', len(beh[0]), flush=True)
    model = DeckValue(); opt = torch.optim.Adam(model.parameters(), lr=a.lr, weight_decay=1e-4)
    tau = a.tau
    best = -1.0
    for ep in range(a.epochs):
        model.train(); perm = tr[torch.randperm(len(tr))]
        tot = 0.0; nb = 0
        for i in range(0, len(perm), a.batch):
            b = perm[i:i + a.batch]
            ob, cn, sl, mk = d['obs'][b], d['cnt'][b], d['slots'][b], d['mask'][b]
            B = len(b)
            h = model.encode(ob, cn)
            Hs = h.unsqueeze(1).expand(-1, K, -1).reshape(-1, h.shape[1])
            ds = model.delta(Hs, sl.reshape(-1)).reshape(B, K)
            w, f, ac, hh = model.heads(Hs)
            m = mk.reshape(-1)
            loss_abs = (F.binary_cross_entropy_with_logits(w, d['win'][b].reshape(-1), reduction='none') * m).sum() / m.sum()
            loss_abs += 0.5 * (F.mse_loss(torch.sigmoid(f), d['floor'][b].reshape(-1), reduction='none') * m).sum() / m.sum()
            loss_abs += 0.2 * (F.cross_entropy(ac, d['act'][b].reshape(-1), reduction='none') * m).sum() / m.sum()
            loss_abs += 0.2 * (F.mse_loss(hh, d['hp'][b].reshape(-1), reduction='none') * m).sum() / m.sum()
            loss_abs += 0.5 * (F.mse_loss(model.sc(Hs).squeeze(1), d['tgt'][b].reshape(-1),
                                          reduction='none') * m).sum() / m.sum()
            # delta regression against the skip reference
            t = d['tgt'][b]
            skip_idx = (sl == SKIP_SLOT).float().argmax(dim=1)
            t_skip = t[torch.arange(B), skip_idx]
            dt = t - t_skip.unsqueeze(1)
            loss_d = (F.huber_loss(ds, dt, reduction='none', delta=0.25) * mk.float()).sum() / mk.float().sum()
            # pairwise ranking loss
            loss_p = torch.zeros((), device=ds.device)
            npair = 0
            for i in range(K):
                for j in range(i + 1, K):
                    v = mk[:, i] & mk[:, j]
                    if not bool(v.any()):
                        continue
                    diff = t[:, i] - t[:, j]
                    v = v & (diff.abs() > 0.002)
                    if not bool(v.any()):
                        continue
                    wgt = (diff[v].abs() / 0.05).clamp(max=1.0)
                    lg = (ds[v, i] - ds[v, j]) / tau
                    loss_p = loss_p + (F.binary_cross_entropy_with_logits(
                        lg, (diff[v] > 0).float(), reduction='none') * wgt).mean()
                    npair += 1
            loss_p = loss_p / max(1, npair)
            loss = loss_abs + a.delta_w * loss_d + a.pair_w * loss_p
            if beh is not None:
                idx = torch.randint(0, len(beh[0]), (min(512, len(beh[0])),))
                loss = loss + a.beh_w * _abs_loss(model, beh[0][idx], beh[1][idx], None,
                                                  beh[2][idx], beh[3][idx], beh[4][idx], beh[5][idx])
            opt.zero_grad(); loss.backward(); nn.utils.clip_grad_norm_(model.parameters(), 5.0); opt.step()
            tot += float(loss); nb += 1
        model.eval()
        with torch.inference_mode():
            ob, cn, sl, mk = d['obs'][val], d['cnt'][val], d['slots'][val], d['mask'][val]
            B = len(val)
            h = model.encode(ob, cn)
            Hs = h.unsqueeze(1).expand(-1, K, -1).reshape(-1, h.shape[1])
            ds = model.delta(Hs, sl.reshape(-1)).reshape(B, K)
            t = d['tgt'][val]
            # rank accuracy: is the chosen candidate within one floor of the best?
            ds = ds.masked_fill(~mk, -1e9)
            best_idx = ds.argmax(dim=1)
            t_best = t.max(dim=1).values
            picked = t[torch.arange(B), best_idx]
            acc = ((t_best - picked) < 0.02).float().mean()
            # pairwise accuracy
            ok = tot_p = 0.0
            pairs = 0
            for i in range(K):
                for j in range(i + 1, K):
                    v = mk[:, i] & mk[:, j] & ((t[:, i] - t[:, j]).abs() > 0.002)
                    if not bool(v.any()):
                        continue
                    pred = ds[v, i] > ds[v, j]
                    ok += float((pred == (t[v, i] > t[v, j])).float().sum()); pairs += int(v.sum())
            pacc = ok / max(1, pairs)
        print('epoch %d loss %.4f | val pick_acc %.3f pair_acc %.3f' % (
            ep, tot / max(1, nb), float(acc), pacc), flush=True)
        score = float(acc) + pacc
        if score > best:
            best = score
            Path(a.out).parent.mkdir(parents=True, exist_ok=True)
            torch.save(model.state_dict(), a.out)
    if not Path(a.out).exists():
        torch.save(model.state_dict(), a.out)
    print('saved', a.out, 'best', best, flush=True)


def cmd_eval(a):
    cfg = base_cfg(a.timed_ms)
    wp = str(Path(a.run) / ('round%d_policy.pt' % a.round))
    wv = str(Path(a.run) / ('round%d_value.pt' % a.round))
    seeds = eval_seeds(a.seeds)
    jobs = [(s, wp, wv, cfg, 0.0, 'eval', a.model, dict(junk=a.junk, rest_smith=a.rest_smith,
                            shop_remove=a.shop_remove, map_elite=a.map_elite,
                            card_margin=a.card_margin, pick=a.pick,
                            smith_target=a.smith_target, shop_mode=a.shop_mode,
                            shop_w=a.shop_w, skip_mode=a.skip_mode)) for s in seeds]
    with ProcessPoolExecutor(max_workers=a.workers, initializer=V2.init_worker,
                             initargs=(a.source,)) as pool:
        rows = list(pool.map(run_episode, jobs, chunksize=1))
    wins = sum(r['win'] for r in rows)
    out = dict(seeds=len(seeds), timed_ms=a.timed_ms, model=a.model, card_margin=a.card_margin,
               mean_floor=statistics.mean(r['floor'] for r in rows), wins=wins,
               win_rate=wins / len(seeds), floors=[r['floor'] for r in rows],
               mean_deck=statistics.mean(r['deck'] for r in rows))
    print('V-card policy: floor %.2f win %d/%d (%.1f%%) deck %.1f' % (
        out['mean_floor'], wins, len(seeds), 100 * out['win_rate'], out['mean_deck']), flush=True)
    Path(a.out).write_text(json.dumps(out, indent=2), encoding='utf-8')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='cmd', required=True)

    def common(p):
        p.add_argument('--run', default='deployment/runs_v2/armD')
        p.add_argument('--round', type=int, default=4)
        p.add_argument('--source', default='deployment/runs_v2/lcb_src')

    c = sub.add_parser('collect'); common(c)
    c.add_argument('--episodes', type=int, default=500)
    c.add_argument('--workers', type=int, default=32)
    c.add_argument('--timed-ms', type=float, default=40.0)
    c.add_argument('--eps', type=float, default=0.1)
    c.add_argument('--shard', type=int, default=100)
    c.add_argument('--seed-offset', type=int, default=0)
    c.add_argument('--junk', type=int, default=1)
    c.add_argument('--rest-smith', type=float, default=0.6)
    c.add_argument('--shop-remove', type=int, default=0)
    c.add_argument('--map-elite', type=float, default=0.0)
    c.add_argument('--out', default='deployment/runs_v2/armg2_data')
    c.set_defaults(func=cmd_collect)

    br = sub.add_parser('branch'); common(br)
    br.add_argument('--episodes', type=int, default=200)
    br.add_argument('--workers', type=int, default=32)
    br.add_argument('--timed-ms', type=float, default=40.0)
    br.add_argument('--cont-ms', type=float, default=10.0)
    br.add_argument('--shard', type=int, default=50)
    br.add_argument('--seed-offset', type=int, default=0)
    br.add_argument('--max-decisions', type=int, default=18)
    br.add_argument('--junk', type=int, default=1)
    br.add_argument('--rest-smith', type=float, default=0.6)
    br.add_argument('--smith-target', default='low', choices=['low', 'high'])
    br.add_argument('--out', default='deployment/runs_v2/armg2_branch')
    br.set_defaults(func=cmd_branch)

    t = sub.add_parser('train')
    t.add_argument('--data', default='deployment/runs_v2/armg2_data')
    t.add_argument('--out', default='deployment/runs_v2/armg2_value.pt')
    t.add_argument('--epochs', type=int, default=8)
    t.add_argument('--batch', type=int, default=256)
    t.add_argument('--lr', type=float, default=1e-3)
    t.set_defaults(func=cmd_train)

    tx = sub.add_parser('trainx')
    tx.add_argument('--data', default='deployment/runs_v2/armg2_branch')
    tx.add_argument('--behavior', default='')
    tx.add_argument('--out', default='deployment/runs_v2/armg2_branch_value.pt')
    tx.add_argument('--epochs', type=int, default=40)
    tx.add_argument('--batch', type=int, default=64)
    tx.add_argument('--lr', type=float, default=1e-3)
    tx.add_argument('--tau', type=float, default=0.1)
    tx.add_argument('--delta-w', type=float, default=1.0)
    tx.add_argument('--pair-w', type=float, default=1.0)
    tx.add_argument('--beh-w', type=float, default=0.2)
    tx.set_defaults(func=cmd_trainx)

    e = sub.add_parser('eval'); common(e)
    e.add_argument('--model', default='deployment/runs_v2/armg2_branch_value.pt')
    e.add_argument('--seeds', type=int, default=50)
    e.add_argument('--workers', type=int, default=24)
    e.add_argument('--timed-ms', type=float, default=40.0)
    e.add_argument('--out', default='deployment/runs_v2/armg2_eval.json')
    e.add_argument('--junk', type=int, default=0)
    e.add_argument('--rest-smith', type=float, default=0.6)
    e.add_argument('--shop-remove', type=int, default=0)
    e.add_argument('--map-elite', type=float, default=0.0)
    e.add_argument('--card-margin', type=float, default=0.0)
    e.add_argument('--pick', default='delta', choices=['delta', 'abs', 'hybrid'])
    e.add_argument('--smith-target', default='low', choices=['low', 'high'])
    e.add_argument('--shop-mode', default='armg', choices=['armg', 'junk', 'junk_relic', 'junk_relic_w'])
    e.add_argument('--shop-w', type=float, default=0.0)
    e.add_argument('--skip-mode', default='model', choices=['model', 'never'])
    e.set_defaults(func=cmd_eval)

    a = ap.parse_args()
    a.func(a)
