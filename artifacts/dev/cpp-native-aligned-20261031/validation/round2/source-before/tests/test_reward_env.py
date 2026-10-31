"""RunEnv keeps combat rewards selectable and card offers private until opened."""

from agent.common import RACT, SCREEN, reward_action
from agent.heuristics import run_policy
from agent.run_env import RunEnv


def _first_reward(seed=1):
    env = RunEnv(seed)
    for step in range(1500):
        if (env.screen == SCREEN.REWARDS and env.rc.reward_gold > 0
                and env.rc.reward_card_pending):
            return env
        assert not env.is_terminal(), "run ended before the first combat reward"
        action = (env.battle.greedy_action(0.0, seed + step)
                  if env.screen == SCREEN.COMBAT else run_policy(env))
        assert env.step(action)
    raise AssertionError("reward screen not reached")


def test_reward_overview_and_card_overlay_preserve_other_rewards():
    env = _first_reward()
    gold = env.rc.reward_gold
    assert gold > 0
    assert env.rc.reward_card_pending and env.rc.offered == []
    assert reward_action(env.rc) == (int(RACT.TAKE_GOLD_REWARD), 0)

    assert env.step((int(RACT.OPEN_CARD_REWARD), 0))
    assert env.screen == SCREEN.CARD_REWARD and env.rc.offered
    assert env.step((int(RACT.SKIP_CARD), 0))
    assert env.screen == SCREEN.REWARDS
    assert not env.rc.reward_card_pending and env.rc.reward_gold == gold

    before = env.rc.gold
    assert env.step((int(RACT.TAKE_GOLD_REWARD), 0))
    assert env.rc.gold >= before + gold
    assert env.rc.reward_gold == 0
    assert env.step((int(RACT.LEAVE_REWARDS), 0))
    assert env.screen == SCREEN.MAP
