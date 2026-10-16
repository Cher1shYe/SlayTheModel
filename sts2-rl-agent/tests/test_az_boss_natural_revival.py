"""Natural card damage must re-enter death processing after each revival."""
from dataclasses import replace
import numpy as np
import pytest
from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.generation import generate_recipe
from sts2_env.az.content import BOSS_CONTENT
from sts2_env.az.scenarios import DeckEntry
from sts2_env.az.rewards import V6


def natural_boss_env(seed=0, variant=(3,2,1)):
    shrugs, slams, purity = variant
    counts = dict(BODY_SLAM=slams, IRON_WAVE=1, IMPERVIOUS=1, ARMAMENTS=1,
                  EQUILIBRIUM=1, SHRUG_IT_OFF=shrugs, PURITY=purity)
    recipe = replace(generate_recipe(44, 0, seed, content_version=BOSS_CONTENT),
                     family_id="ironclad-block", encounter_id="setup_test_subject_boss", player_hp=80,
                     deck=tuple(DeckEntry(n, True, c) for n,c in sorted(counts.items())))
    return ObservableCombatAdapter(recipe, reward_version=V6)


def test_second_knockout_from_card_damage_keeps_respawn_intent():
    env = natural_boss_env()
    # Full legal play from an ordinary first-form start, no forced kill or HP edit.
    for action in [4,4,11,16,0,3,6,36,21,26,0,3,4,26,26,0,2,3,3,26,26,0,2,6,31,21]:
        env.step(action)
    assert env.information.boss.phase.cursor[:2] == (1, "reviving")
    assert env.information.intent == ("HEAL", 0, 1)
    env.step(0)
    assert env.information.boss.phase.cursor[:2] == (2, "alive")
    assert not env.world.enemies[0]._death_processed


def test_armaments_after_naturally_generated_burn_is_not_an_upgrade():
    env = natural_boss_env()
    for action in [4,4,11,16,0,3,6,36,21,26,0,3,4,26,26,0,2,3,3,26,26,0,2,6,31,21,
                   0,2,4,26,16,16,0,2,4,5,31,31,0,4,6,21,21,21,0,1,4,1,3,4,11,0,4,21]:
        env.step(action)
    assert "BURN" in env.information.hand
    assert env.information.hand[0] == "ARMAMENTS+"
    before = env.information.history.upgraded
    env.step(1)
    assert env.information.history.upgraded == before
    assert "BURN" in env.information.hand


def test_burn_resolves_before_hand_retention_and_new_draw():
    env = natural_boss_env(7)
    for action in [1,5,26,0,3,4,5,16,26,0,4,5,36,16,16,0,2,2,6,21,21,0,1,1,3,3,2,11,11,
                   0,2,5,11,11,0,3,5,4,21,21,0,3,4,16,26,0,3,3,3,11,16,0,11,1]:
        env.step(action)
    assert env.information.hand == ("WOUND", "BURN", "BURN")
    assert env.information.retain_hand == 1
    env.step(0)
    assert env.information.hand[0] == "WOUND"
    assert env.information.hand.count("BURN") == 1  # redrawn, not retained


@pytest.mark.parametrize("variant", [(3,2,1),(5,3,1),(2,3,1)])
@pytest.mark.parametrize("seed", range(8))
def test_natural_later_phases_particle_parity_and_terminal(variant, seed):
    from sts2_env.az.information import BeliefSampler
    from sts2_env.az.boss_curriculum import block_rule_action
    from sts2_env.search.mcts import clone_state
    env = natural_boss_env(seed, variant)
    rng = np.random.default_rng(seed)
    phases = set()
    while not env.outcome().done:
        info = env.information
        phases.add(info.boss.phase.cursor[0])
        particle = BeliefSampler().sample(info, rng)
        # Test-only alignment of hidden draws; the public planner never gets it.
        for attr in ("draw_pile", "discard_pile"):
            available, ordered = list(getattr(particle.world, attr)), []
            for card in getattr(env.world, attr):
                twin = next(c for c in available if (c.card_id,c.upgraded)==(card.card_id,card.upgraded))
                available.remove(twin)
                ordered.append(twin)
            setattr(particle.world, attr, ordered)
        particle.world.rng = clone_state(env.world.rng)
        action = block_rule_action(info)
        predicted = particle.step(action)
        env.step(action)
        assert predicted == env.information
    assert 1 in phases
    assert env.information.terminal_value() == env.outcome().reward
    if variant == (5,3,1) and seed == 3:
        assert phases == {0,1,2}
        assert env.outcome().termination_reason == "win"
