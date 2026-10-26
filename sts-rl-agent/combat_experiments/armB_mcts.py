#!/usr/bin/env python3
"""Arm B 引导式 PUCT 树搜索(AlphaZero 的搜索那一半):
策略网(BC)出先验 P 引导探索,价值网评叶子(替代随机rollout),多步前瞻。
比 1 步贪心深、且先验+树平均能压住价值网误差。先用现成的 BC策略 + MC价值网当引导(还没自对弈迭代)。
看引导树搜索能否破前馈的~14、逼近 MCTS 的 23。
跑: STS_SIM_COUNT=2000 N_SIMS=80 python armB_mcts.py [n_eval_seeds] [workers]
"""
import os, sys, math, statistics, time
import multiprocessing as mp
SB = os.environ.get("STS_BOT_DIR", "../sts-bot")
sys.path.insert(0, os.path.join(SB, "sim/sts_lightspeed/build312"))
sys.path.insert(0, SB)
import slaythespire as sts
import torch
import armB_train as MB
import armB_value as VV

N_SIMS = int(os.environ.get("N_SIMS", "80"))
C_PUCT = float(os.environ.get("C_PUCT", "2.0"))
POLICY_PATH = os.environ.get("POLICY", "armB_model_B256x256.pt")
VALUE_PATH = os.environ.get("VALUE", "armB_model_VAL256x256.pt")

class Node:
    __slots__ = ("bc", "cands", "P", "N", "W", "children", "expanded", "terminal", "leaf_value")
    def __init__(self, bc):
        self.bc = bc; self.cands = None; self.P = None; self.N = None; self.W = None
        self.children = None; self.expanded = False; self.terminal = False; self.leaf_value = 0.0

def expand(node, policy, value):
    bc = node.bc
    if bc.outcome != sts.Outcome.UNDECIDED:
        node.terminal = True; node.leaf_value = VV._battle_value(bc); return node.leaf_value
    cands = sts.get_legal_actions(bc)
    if not cands:
        node.terminal = True; node.leaf_value = VV._battle_value(bc); return node.leaf_value
    node.cands = cands
    state = MB.encode_battle(bc); hand = list(bc.hand)
    with torch.no_grad():
        logits = policy.score(state, [MB.cand_desc(bc, a, hand) for a in cands])
        node.P = torch.softmax(logits, dim=0).tolist()
        node.leaf_value = float(value.value(state).item())
    n = len(cands)
    node.N = [0]*n; node.W = [0.0]*n; node.children = [None]*n; node.expanded = True
    return node.leaf_value

def simulate(node, policy, value):
    if node.terminal: return node.leaf_value
    if not node.expanded: return expand(node, policy, value)
    total = sum(node.N); sq = math.sqrt(total + 1)
    best_i, best_s = 0, -1e18
    for i in range(len(node.cands)):
        q = node.W[i]/node.N[i] if node.N[i] > 0 else 0.0
        u = C_PUCT * node.P[i] * sq / (1 + node.N[i])
        if q + u > best_s: best_s = q + u; best_i = i
    if node.children[best_i] is None:
        bc2 = node.bc.clone(); node.cands[best_i].execute(bc2)
        node.children[best_i] = Node(bc2)
    v = simulate(node.children[best_i], policy, value)
    node.N[best_i] += 1; node.W[best_i] += v
    return v

def mcts_search(root_bc, policy, value, n_sims):
    root = Node(root_bc.clone())
    for _ in range(n_sims):
        simulate(root, policy, value)
    if root.cands is None: return None
    bi = max(range(len(root.cands)), key=lambda i: root.N[i])   # 选访问最多的动作
    return root.cands[bi]

def play_with_mcts(seed, policy, value, n_sims=None, sims=None, max_steps=600):
    n_sims = n_sims or N_SIMS; sims = sims or MB.SIMCOUNT
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
                a = mcts_search(bc, policy, value, n_sims)
                (a if a is not None else cands[0]).execute(bc)
            bc.exit_battle(gc)
    except Exception: pass
    return {"seed": seed, "floor": gc.floor_num, "win": gc.outcome == sts.GameOutcome.PLAYER_VICTORY}

def worker(seed):
    policy = MB.Scorer(tuple(int(x) for x in os.environ.get("ARM_B_ARCH", "256,256").split(",")))
    policy.load_state_dict(torch.load(os.path.join(SB, POLICY_PATH), weights_only=True)); policy.eval()
    value = VV.ValueNet(tuple(int(x) for x in os.environ.get("VAL_ARCH", "256,256").split(",")))
    value.load_state_dict(torch.load(os.path.join(SB, VALUE_PATH), weights_only=True)); value.eval()
    return play_with_mcts(seed, policy, value)

if __name__ == "__main__":
    NE = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    W = int(sys.argv[2]) if len(sys.argv) > 2 else max(2, mp.cpu_count() - 2)
    seeds = MB.read_seeds("eval_seeds_50.txt")[:NE]
    print(f"引导PUCT eval: {len(seeds)}seed {W}workers N_SIMS{N_SIMS} c_puct{C_PUCT} policy={POLICY_PATH} value={VALUE_PATH}", flush=True)
    t0 = time.time()
    ctx = mp.get_context("spawn")
    with ctx.Pool(W) as pool:
        res = pool.map(worker, seeds)
    fl = [r["floor"] for r in res]; wr = statistics.mean(r["win"] for r in res)
    print(f"引导树搜索 eval楼层 {statistics.mean(fl):.1f} (范围{min(fl)}-{max(fl)}) | 通关率 {wr:.2f} | {(time.time()-t0)/60:.1f}分", flush=True)
    print(f"对照: 前馈~12-14 / 价值1步~8 / MCTS-2000~23", flush=True)
