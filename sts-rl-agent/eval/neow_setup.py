"""Resolve the pure max-HP Neow option for a simulator seed."""


def max_hp_option(sts, agent_module, seed):
    for index in range(4):
        game = sts.GameContext(sts.CharacterClass.IRONCLAD, seed, 0)
        agent = sts.Agent(); agent.pause_on_event = True; agent.playout(game)
        _, _, executors = agent_module.build_choices(game)
        before = game.max_hp, len(game.deck), len(game.relics), game.gold
        executors[index](game)
        if (game.max_hp > before[0] and len(game.deck) == before[1]
                and len(game.relics) == before[2] and game.gold == before[3]
                and game.screen_state == sts.ScreenState.MAP_SCREEN):
            return index
    raise ValueError(f"no pure max-HP Neow option for seed {seed}")
