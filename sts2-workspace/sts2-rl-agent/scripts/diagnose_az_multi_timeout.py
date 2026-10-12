"""Reproduce a frozen final-test timeout without changing training or test scores."""
import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sts2_env.az.adapter import ObservableCombatAdapter
from sts2_env.az.config import derive_seed, atomic_json
from sts2_env.az.deck_observation import prototype
from sts2_env.az.network import load_checkpoint
from sts2_env.az.observable_puct import plan_observable
from sts2_env.az.rewards import V4
from sts2_env.az.content import MULTI_CONTENT
from sts2_env.az.scenarios import load_manifest
from sts2_env.az.self_play import initialize_worker
from sts2_env.gym_env.action_space import action_to_card_and_target


def run():
    initialize_worker()
    root = Path("output/az_g2_multi_v1_quick")
    read = lambda p: json.loads(p.read_text(encoding="utf8"))
    records = read(root / "test-43-search.json")["final"]
    cases = [(i, r) for i, r in enumerate(records) if r["termination_reason"] == "time_limit"]
    assert len(cases) == 1
    index, expected = cases[0]
    recipe = next(r for r in load_manifest(root / "manifest.json") if r.scenario_id == expected["scenario_id"])
    checkpoint = read(root / "frozen_final_models.json")["43"]["final"]
    model, metadata = load_checkpoint(checkpoint, "observable", V4, MULTI_CONTENT)
    env = ObservableCombatAdapter(recipe, reward_version=V4, error_dir=root / "diagnostic_errors")
    steps = []
    while not env.outcome().done:
        info = env.information
        search = plan_observable(info, model, model_version=metadata["model_version"], budget=8,
                                 search_seed=derive_seed(123, 0, index, f"eval-{len(steps)}"))
        action = search.action
        played = "END_TURN"
        selected = []
        if info.choice:
            played = "CHOICE:" + info.pending_card.token
            if info.pending_card.token.removesuffix("+") == "PURITY":
                selected = [o.card.token for j, o in enumerate(info.choice.options) if action & (1 << j)]
            elif action:
                selected = [info.choice.options[action-1].card.token]
        elif action:
            hand, _ = action_to_card_and_target(action)
            played = info.hand[hand]
        row = dict(decision=len(steps), turn=info.turn, action=int(action), played=played, selected=selected,
                   hp=info.player_hp, enemy_hp=info.enemies[0].hp,
                   active_attacks=sum(prototype(t).is_attack for t in info.hand + info.draw_composition + info.discard),
                   hand=list(info.hand))
        env.step(action)
        row["choice_after"] = env.information.choice is not None
        if played.startswith("CHOICE:PURITY"):
            assert not row["choice_after"]
        steps.append(row)
    outcome = asdict(env.outcome())
    for field in ("termination_reason", "turns", "decisions", "reward", "final_hp", "enemy_final_hp", "enemy_initial_hp"):
        assert outcome[field] == expected[field], field
    active = env.information.hand + env.information.draw_composition + env.information.discard
    summary = dict(reproduced=True, scenario=recipe.to_dict(), outcome=outcome,
                   plays=dict(Counter(s["played"] for s in steps)),
                   purity_selections=[s for s in steps if s["played"].startswith("CHOICE:PURITY")],
                   first_no_active_attacks=next((s["decision"] for s in steps if s["active_attacks"] == 0), None),
                   final_active_cards=dict(Counter(active)), final_exhaust=dict(Counter(env.information.exhaust)),
                   actions=steps,
                   scope="Read-only reproduction of one already-viewed frozen test case; no scores or models changed")
    atomic_json("docs/az_multi_timeout_diagnostic.json", summary)
    print(json.dumps({k: v for k, v in summary.items() if k not in ("actions", "scenario")}, indent=2))


if __name__ == "__main__":
    run()
