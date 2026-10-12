"""RNG parity tests for the game's seeded random wrapper."""

from sts2_env.core.rng import Rng, deterministic_hash_code
from sts2_env.events.shared import AromaOfChaos, PunchOff
from sts2_env.run.run_state import RunRngSet
from sts2_env.run.run_state import RunState


def test_rng_seeded_next_matches_csharp_random_sequence():
    rng = Rng(0)

    values = [rng.next_int(0, 2_147_483_646) for _ in range(5)]

    assert values == [
        1_559_595_546,
        1_755_192_844,
        1_649_316_166,
        1_198_642_031,
        442_452_829,
    ]
    assert rng.counter == 5


def test_named_rng_streams_match_game_seed_derivation():
    seed = deterministic_hash_code("42")

    assert RunRngSet(42).seed == seed
    assert Rng(seed, "up_front").seed == 1_840_945_279
    assert Rng(seed, "shuffle").seed == 1_089_005_703
    assert Rng(seed, "combat_card_generation").seed == 1_786_151_384
    assert Rng(seed, "combat_potion_generation").seed == 3_924_679_655
    assert Rng(seed, "combat_card_selection").seed == 3_447_564_188
    assert Rng(seed, "combat_energy_costs").seed == 1_559_354_386
    assert Rng(seed, "combat_targets").seed == 306_656_263
    assert Rng(seed, "monster_ai").seed == 484_627_639
    assert Rng(seed, "combat_orbs").seed == 28_674_157
    assert Rng(seed, "treasure_room_relics").seed == 1_181_528_096
    assert Rng(seed + 1, "rewards").seed == 2_616_644_287
    assert Rng(seed + 1, "shops").seed == 1_200_520_448
    assert Rng(seed + 1, "transformations").seed == 2_943_746_949
    assert Rng(seed, "act_1_map").seed == 575_478_435
    assert Rng(seed, "spoils_map").seed == 2_565_339_305


def test_run_rng_set_exposes_game_named_streams():
    streams = RunRngSet(42)

    assert streams.up_front.seed == 1_840_945_279
    assert streams.shuffle.seed == 1_089_005_703
    assert streams.combat_card_generation.seed == 1_786_151_384
    assert streams.combat_potion_generation.seed == 3_924_679_655
    assert streams.combat_card_selection.seed == 3_447_564_188
    assert streams.combat_energy_costs.seed == 1_559_354_386
    assert streams.combat_targets.seed == 306_656_263
    assert streams.monster_ai.seed == 484_627_639
    assert streams.combat_orbs.seed == 28_674_157
    assert streams.treasure_room.seed == 1_181_528_096
    assert streams.rewards.seed == 2_616_644_287
    assert streams.shops.seed == 1_200_520_448
    assert streams.transformations.seed == 2_943_746_949


def test_event_rng_seed_matches_game_event_derivation():
    run_state = RunState(seed=42, character_id="Ironclad")

    aroma = AromaOfChaos()
    punch = PunchOff()

    assert aroma.event_entry() == "AROMA_OF_CHAOS"
    assert aroma.create_event_rng(run_state).seed == 3_201_353_244
    assert punch.event_entry() == "PUNCH_OFF"
    assert punch.create_event_rng(run_state).seed == 1_756_925_168


def test_shuffle_uses_csharp_fisher_yates_sequence():
    values = [1, 2, 3, 4, 5]
    rng = Rng(42)

    rng.shuffle(values)

    assert values == [3, 2, 5, 1, 4]
    assert rng.counter == 4
