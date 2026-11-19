"""Run the frozen sh02v17 policy on public SF2 v14 observations and legal actions."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import numpy as np
import torch

from .layout import project_public, project_combat_actions
from .vendor.sts2ai import spec
from .vendor.sts2ai.model import ModelConfig, Sts2Net

WEIGHT_SHA256 = 'd7e13c7e8a29a98e8322e48732b2d7ad355c00890791d586dbce0c318c39bcf6'
RULESET = 'native-41cef1ea-port-v14'
VOCAB = np.array([1, 129, 597, 291, 65, 9, 92, 597, 291, 65, 4, 1024, 10])
OFFSETS = np.cumsum([1, *VOCAB])

# Macro action IDs 0..31 have the same enum names. SF2 opens upgrade/removal
# selectors instead of targeting a deck card immediately. Map new menu actions
# to their closest trained choice, retaining the actual execution descriptors.
MACRO_TYPES = np.arange(40)
MACRO_TYPES[[4, 10]] = [32, 33]
MACRO_TYPES[32:] = [34, 27, 17, 19, 36, 37, 33, 39]


def load_model(path, sim):
    versions = (sim.ENGINE_RULESET_ID, sim.PUBLIC_OBS_VERSION, sim.MACRO_OBS_VERSION,
                sim.ACTION_SCHEMA_VERSION, sim.ACTION_FEAT_DIM)
    if versions != (RULESET, 18, 4, 15, 732):
        raise ValueError(f'incompatible simulator: {versions}')
    payload = Path(path).read_bytes()
    if sha256(payload).hexdigest() != WEIGHT_SHA256:
        raise ValueError('expected the evaluated sh02v17 checkpoint')
    ck = torch.load(BytesIO(payload), weights_only=True, map_location='cpu')
    # These module constants define the learned projection/embedding shapes.
    spec.F_TOK, spec.F_ACT = 80, 729
    spec.TokenType.COUNT, spec.ActionType.COUNT = 32, 64
    model = Sts2Net(ModelConfig(**ck['model_config']))
    model.load_state_dict(ck['model'], strict=True)
    return model.eval()


# Native descriptors are used only to execute or mask public choices; instance
# UIDs are never fed to the policy network.
CHOOSE, CONFIRM, HAND = 2, 3, 1
SELECT_GRID, CONFIRM_GRID = 25, 26


def combat_choices(battle):
    actions = [tuple(a) for a in battle.legal_actions()]
    op, pile, remaining, count = battle.pending_info
    if op and pile == HAND:
        selected = set(battle.pending_selected_uids)
        full = len(selected) >= min(remaining, count)
        actions = [a for a in actions if a[0] != CHOOSE or
                   (not full and a[3] not in selected)]
    return actions


def grid_choice_rows(rc, actions):
    selected = rc.card_grid_selected
    # These two enchantment previews accept a zero-card confirm as a no-op.
    # Cancel-preview remains available if already on an empty preview.
    empty_preview = rc.card_grid_kind in (18, 19) and not any(selected)
    return [i for i, (kind, index) in enumerate(actions)
            if not (kind == SELECT_GRID and selected[index])
            and not (kind == CONFIRM_GRID and empty_preview)]


def step_policy_action(rc, sim, action):
    """Complete the confirmation implied by a mandatory single pick."""
    combat = rc.screen == sim.RunScreen.COMBAT
    if combat:
        op, pile, required, _ = rc.battle.pending_info
        single = (action[0] == CHOOSE and pile == HAND and required == 1
                  and not rc.battle.pending_optional)
    else:
        grid = rc.card_grid_kind
        single = action[0] == SELECT_GRID and rc.card_grid_min == rc.card_grid_max == 1

    if not rc.step_final_boss_evaluation(action):
        return False
    if single and not rc.is_terminal:
        if combat and rc.screen == sim.RunScreen.COMBAT:
            battle = rc.battle
            if battle.pending_info[0] == op and battle.pending_selected_uids == [action[3]]:
                confirm = next(a for a in battle.legal_actions() if a[0] == CONFIRM)
                return rc.step_final_boss_evaluation(confirm)
        elif not combat and rc.card_grid_kind == grid and rc.card_grid_preview:
            # Some grid kinds already settle when the card is picked.
            return rc.step_final_boss_evaluation((CONFIRM_GRID, 0))
    return True


def observe(rc, sim):
    m = rc.macro_observation()
    kind, ids = m['kind'], m['id']
    token_cat = np.zeros((len(kind), 5), np.int64)
    token_cat[:, 0] = kind + 1
    # An appended item has no learned identity. Preserve its entity type
    # without aliasing an item in the next checkpoint vocabulary.
    token_cat[:, 1] = np.where(ids < VOCAB[kind], OFFSETS[kind] + ids, 0)
    src = m['num']
    numeric = src[:, :80].copy()
    cards = (kind == 2) | (kind == 7)
    numeric[cards, 32] = src[cards, 78]  # Guilty progress
    numeric[cards, 33:53] = src[cards, 32:52]
    numeric[cards, 53] = 0  # clone provenance
    numeric[cards, 54:79] = src[cards, 52:77]
    numeric[kind == 1, 44:] = 0  # incompatible selector / event tail
    numeric[kind == 1, 44] = src[kind == 1, 86]  # service selector

    flat = project_public(np.asarray(rc.observe_public(), dtype=np.float32))
    blocks = flat.reshape(-1, 80)
    live = np.flatnonzero(blocks.any(axis=1))
    edges = m['edges']
    extra = np.zeros((len(live) + len(edges), 5), np.int64)
    extra[:len(live), 0] = 14
    extra[:len(live), 1] = OFFSETS[-1] + live
    extra[len(live):, 0] = 15
    edge_features = np.zeros((len(edges), 80), np.float32)
    edge_features[:, :2] = edges / 128
    if rc.screen == sim.RunScreen.COMBAT:
        actions = combat_choices(rc.battle)
        if not actions:
            raise ValueError('live combat has no legal actions')
        types = np.array([a[0] for a in actions])
        features = project_combat_actions(np.asarray(
            [rc.combat_action_features(*a) for a in actions], np.float32), types)
        action_type = types + 1
        refs = np.full((len(actions), 2), -1, np.int64)
    else:
        actions = list(zip(map(int, m['cand_type']), map(int, m['cand_index'])))
        if actions != [tuple(a) for a in rc.legal_actions()] or not actions:
            raise ValueError('macro observation and legal action list disagree or are empty')
        action_type = MACRO_TYPES[m['cand_type']] + 8
        refs = np.column_stack((m['cand_target'], m['cand_target2'])).astype(np.int64)
        features = np.zeros((len(actions), 729), np.float32)
        features[:, :4] = m['cand_num'][:, :4]
    action_cat = np.zeros((len(actions), 3), np.int64)
    action_cat[:, 0] = action_type
    if rc.screen != sim.RunScreen.COMBAT and rc.card_grid_kind:
        rows = grid_choice_rows(rc, actions)
        if not rows:
            raise ValueError('grid selection adapter has no executable choice')
        actions = [actions[i] for i in rows]
        action_cat, refs, features = action_cat[rows], refs[rows], features[rows]
    obs = dict(token_cat=np.concatenate((token_cat, extra)),
               token_num=np.concatenate((numeric, blocks[live], edge_features)),
               action_cat=action_cat, action_ref=refs, action_num=features)
    return obs, actions


@torch.inference_mode()
def choose(model, obs, seed):
    inputs = {k: torch.from_numpy(v).unsqueeze(0) for k, v in obs.items()}
    logits = model(**inputs)['logits'][0]
    if not torch.isfinite(logits).all():
        raise ValueError('nonfinite legal action logits')
    rng = torch.Generator().manual_seed(seed)
    return int(torch.multinomial(logits.softmax(-1), 1, generator=rng))

