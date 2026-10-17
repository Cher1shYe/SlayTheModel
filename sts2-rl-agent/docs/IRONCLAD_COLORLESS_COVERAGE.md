# 战士与无色牌覆盖清单

范围：151 个 ID（战士 87、无色 64）。当前接通 139，待接通 12。

engine 的 registered 仅表示原生工厂及效果函数存在，不等于完整机制正确性。
接通仅限单人 Ironclad、无遗物药水、既有十个遭遇；本次未运行训练或最终留出。
batch5-v5 中：多人牌在单人无合法目标（ALLY 目标牌不可出，ALL_ALLIES 牌可出但无队友效果）；
`notes` 列写明每张牌的单人语义，不允许用“已接通”掩盖无效果。
逐层状态、升级版描述摘要与源码依赖提示见同名 JSON；依赖提示不是机制实现。

| 牌池 | ID | 批次 | 六链路状态 | 单人语义提示 | 阻塞路径／直接能力依赖 |
|---|---|---|---|---|---|
| Ironclad | AGGRESSION_CARD | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | ANGER | existing | engine 注册；其余已接通 | — | — |
| Ironclad | ARMAMENTS | existing | engine 注册；其余已接通 | — | — |
| Ironclad | ASHEN_STRIKE | existing | engine 注册；其余已接通 | — | — |
| Ironclad | BARRICADE_CARD | powers-v2 | engine 注册；其余已接通 | — | — |
| Ironclad | BASH | existing | engine 注册；其余已接通 | — | — |
| Ironclad | BATTLE_TRANCE | simple-v3 | engine 注册；其余已接通 | — | — |
| Ironclad | BLOOD_WALL | batch1-v1 | engine 注册；其余已接通 | — | — |
| Ironclad | BLOODLETTING | existing | engine 注册；其余已接通 | — | — |
| Ironclad | BLUDGEON | existing | engine 注册；其余已接通 | — | — |
| Ironclad | BODY_SLAM | existing | engine 注册；其余已接通 | — | — |
| Ironclad | BRAND | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | BREAK | batch1-v1 | engine 注册；其余已接通 | — | — |
| Ironclad | BREAKTHROUGH | batch1-v1 | engine 注册；其余已接通 | — | — |
| Ironclad | BULLY | batch1-v1 | engine 注册；其余已接通 | — | — |
| Ironclad | BURNING_PACT | existing | engine 注册；其余已接通 | — | — |
| Ironclad | CASCADE | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | CINDER | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | COLOSSUS_CARD | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | CONFLAGRATION | simple-v3 | engine 注册；其余已接通 | — | — |
| Ironclad | CORRUPTION_CARD | batch5-v5 | engine 注册；其余已接通 | — | — |
| Ironclad | CRIMSON_MANTLE | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | CRUELTY_CARD | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | DARK_EMBRACE_CARD | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | DEFEND_IRONCLAD | existing | engine 注册；其余已接通 | — | — |
| Ironclad | DEMON_FORM_CARD | powers-v2 | engine 注册；其余已接通 | — | — |
| Ironclad | DEMONIC_SHIELD | batch5-v5 | engine 注册；其余已接通 | single-player-unplayable/native ANY_ALLY effect needs another player; unplayable in single-player | — |
| Ironclad | DISMANTLE | batch1-v1 | engine 注册；其余已接通 | — | — |
| Ironclad | DOMINATE | batch1-v1 | engine 注册；其余已接通 | — | — |
| Ironclad | DRUM_OF_BATTLE_CARD | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | EVIL_EYE | simple-v3 | engine 注册；其余已接通 | — | — |
| Ironclad | EXPECT_A_FIGHT | simple-v3 | engine 注册；其余已接通 | — | — |
| Ironclad | FEED | batch5-v5 | engine 注册；其余已接通 | — | — |
| Ironclad | FEEL_NO_PAIN_CARD | powers-v2 | engine 注册；其余已接通 | — | — |
| Ironclad | FIEND_FIRE | simple-v3 | engine 注册；其余已接通 | — | — |
| Ironclad | FIGHT_ME | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | FLAME_BARRIER_CARD | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | FORGOTTEN_RITUAL | simple-v3 | engine 注册；其余已接通 | — | — |
| Ironclad | GRAPPLE | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | HAVOC | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | HEADBUTT | existing | engine 注册；其余已接通 | — | — |
| Ironclad | HELLRAISER_CARD | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | HEMOKINESIS | existing | engine 注册；其余已接通 | — | — |
| Ironclad | HOWL_FROM_BEYOND | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | IMPERVIOUS | existing | engine 注册；其余已接通 | — | — |
| Ironclad | INFERNAL_BLADE | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | INFERNO_CARD | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | INFLAME | existing | engine 注册；其余已接通 | — | — |
| Ironclad | IRON_WAVE | existing | engine 注册；其余已接通 | — | — |
| Ironclad | JUGGERNAUT_CARD | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | JUGGLING_CARD | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | MANGLE | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | MOLTEN_FIST | batch1-v1 | engine 注册；其余已接通 | — | — |
| Ironclad | OFFERING | existing | engine 注册；其余已接通 | — | — |
| Ironclad | ONE_TWO_PUNCH_CARD | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | PACTS_END | simple-v3 | engine 注册；其余已接通 | — | — |
| Ironclad | PERFECTED_STRIKE | simple-v3 | engine 注册；其余已接通 | — | — |
| Ironclad | PILLAGE | simple-v3 | engine 注册；其余已接通 | — | — |
| Ironclad | POMMEL_STRIKE | existing | engine 注册；其余已接通 | — | — |
| Ironclad | PRIMAL_FORCE | existing | engine 注册；其余已接通 | — | — |
| Ironclad | PYRE | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | RAGE_CARD | powers-v2 | engine 注册；其余已接通 | — | — |
| Ironclad | RAMPAGE | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | RUPTURE_CARD | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | SECOND_WIND | simple-v3 | engine 注册；其余已接通 | — | — |
| Ironclad | SETUP_STRIKE_CARD | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | SHRUG_IT_OFF | existing | engine 注册；其余已接通 | — | — |
| Ironclad | SPITE | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | STAMPEDE_CARD | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | STOKE | simple-v3 | engine 注册；其余已接通 | — | — |
| Ironclad | STOMP | existing | engine 注册；其余已接通 | — | — |
| Ironclad | STONE_ARMOR | simple-v3 | engine 注册；其余已接通 | — | — |
| Ironclad | STRIKE_IRONCLAD | existing | engine 注册；其余已接通 | — | — |
| Ironclad | SWORD_BOOMERANG | simple-v3 | engine 注册；其余已接通 | — | — |
| Ironclad | TANK_CARD | batch5-v5 | engine 注册；其余已接通 | — | — |
| Ironclad | TAUNT | batch1-v1 | engine 注册；其余已接通 | — | — |
| Ironclad | TEAR_ASUNDER | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | THRASH | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | THUNDERCLAP | existing | engine 注册；其余已接通 | — | — |
| Ironclad | TREMBLE | batch1-v1 | engine 注册；其余已接通 | — | — |
| Ironclad | TRUE_GRIT | existing | engine 注册；其余已接通 | — | — |
| Ironclad | TWIN_STRIKE | existing | engine 注册；其余已接通 | — | — |
| Ironclad | UNMOVABLE | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | UNRELENTING | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | UPPERCUT | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | VICIOUS_CARD | foundation-v4 | engine 注册；其余已接通 | — | — |
| Ironclad | WHIRLWIND | existing | engine 注册；其余已接通 | — | — |
| Colorless | ALCHEMIZE | pending | engine 注册；其余待审计 | — | scope_deferred/potions are outside the combat scope (in-combat potion inventory); mechanic_descriptor/cards/ALCHEMIZE; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | ANOINTED | foundation-v4 | engine 注册；其余已接通 | — | — |
| Colorless | AUTOMATION | pending | engine 注册；其余待审计 | — | scope_deferred/public per-draw counter contract not implemented yet; mechanic_descriptor/cards/AUTOMATION; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/AUTOMATION |
| Colorless | BEACON_OF_HOPE | batch5-v5 | engine 注册；其余已接通 | — | — |
| Colorless | BEAT_DOWN | foundation-v4 | engine 注册；其余已接通 | — | — |
| Colorless | BELIEVE_IN_YOU | batch5-v5 | engine 注册；其余已接通 | single-player-unplayable/native ANY_ALLY effect needs another player; unplayable in single-player | — |
| Colorless | BOLAS | batch5-v5 | engine 注册；其余已接通 | return-to-hand/returns to hand before the next hand draw | — |
| Colorless | CALAMITY_CARD | foundation-v4 | engine 注册；其余已接通 | — | — |
| Colorless | CATASTROPHE | foundation-v4 | engine 注册；其余已接通 | — | — |
| Colorless | COORDINATE_CARD | batch5-v5 | engine 注册；其余已接通 | single-player-unplayable/native ANY_ALLY effect needs another player; unplayable in single-player | — |
| Colorless | DARK_SHACKLES | foundation-v4 | engine 注册；其余已接通 | — | — |
| Colorless | DISCOVERY | foundation-v4 | engine 注册；其余已接通 | — | — |
| Colorless | DRAMATIC_ENTRANCE | simple-v3 | engine 注册；其余已接通 | — | — |
| Colorless | ENTROPY | pending | engine 注册；其余待审计 | — | scope_deferred/transforming a Colorless/event/ancient card can produce Splash; mechanic_descriptor/cards/ENTROPY; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/ENTROPY |
| Colorless | EQUILIBRIUM | existing | engine 注册；其余已接通 | — | — |
| Colorless | ETERNAL_ARMOR | powers-v2 | engine 注册；其余已接通 | — | — |
| Colorless | FASTEN | powers-v2 | engine 注册；其余已接通 | — | — |
| Colorless | FINESSE | batch1-v1 | engine 注册；其余已接通 | — | — |
| Colorless | FISTICUFFS | simple-v3 | engine 注册；其余已接通 | — | — |
| Colorless | FLASH_OF_STEEL | batch1-v1 | engine 注册；其余已接通 | — | — |
| Colorless | GANG_UP | batch5-v5 | engine 注册；其余已接通 | — | — |
| Colorless | GOLD_AXE | batch5-v5 | engine 注册；其余已接通 | — | — |
| Colorless | HAND_OF_GREED | batch5-v5 | engine 注册；其余已接通 | out-of-combat-reward/in-combat damage only; gold/potion reward is run state outside this scope | — |
| Colorless | HIDDEN_GEM | pending | engine 注册；其余待审计 | — | scope_deferred/random hidden draw-pile card identity mutation has no public face contract; mechanic_descriptor/cards/HIDDEN_GEM; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | HUDDLE_UP | batch5-v5 | engine 注册；其余已接通 | single-player-noop/native ALL_ALLIES effect targets teammates only; playable no-op in single-player | — |
| Colorless | IMPATIENCE | simple-v3 | engine 注册；其余已接通 | — | — |
| Colorless | INTERCEPT_CARD | batch5-v5 | engine 注册；其余已接通 | single-player-unplayable/native ANY_ALLY effect needs another player; unplayable in single-player | — |
| Colorless | JACK_OF_ALL_TRADES | pending | engine 注册；其余待审计 | — | scope_deferred/native Colorless pool contains Splash; mechanic_descriptor/cards/JACK_OF_ALL_TRADES; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | JACKPOT | foundation-v4 | engine 注册；其余已接通 | — | — |
| Colorless | KNOCKDOWN | batch5-v5 | engine 注册；其余已接通 | — | — |
| Colorless | LIFT | batch5-v5 | engine 注册；其余已接通 | single-player-unplayable/native ANY_ALLY effect needs another player; unplayable in single-player | — |
| Colorless | MASTER_OF_STRATEGY | batch1-v1 | engine 注册；其余已接通 | — | — |
| Colorless | MAYHEM_CARD | foundation-v4 | engine 注册；其余已接通 | — | — |
| Colorless | MIMIC | batch5-v5 | engine 注册；其余已接通 | single-player-unplayable/native ANY_ALLY effect needs another player; unplayable in single-player | — |
| Colorless | MIND_BLAST | simple-v3 | engine 注册；其余已接通 | — | — |
| Colorless | NOSTALGIA_CARD | pending | engine 注册；其余待审计 | — | scope_deferred/per-turn top-deck return contract not implemented yet; mechanic_descriptor/cards/NOSTALGIA_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/NOSTALGIA |
| Colorless | OMNISLICE | simple-v3 | engine 注册；其余已接通 | — | — |
| Colorless | PANACHE_CARD | pending | engine 注册；其余待审计 | — | scope_deferred/per-turn fifth-play counter contract not implemented yet; mechanic_descriptor/cards/PANACHE_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/PANACHE |
| Colorless | PANIC_BUTTON | foundation-v4 | engine 注册；其余已接通 | — | — |
| Colorless | PREP_TIME | foundation-v4 | engine 注册；其余已接通 | — | — |
| Colorless | PRODUCTION | batch1-v1 | engine 注册；其余已接通 | — | — |
| Colorless | PROLONG | pending | engine 注册；其余待审计 | — | scope_deferred/next-turn block power contract not implemented yet; mechanic_descriptor/cards/PROLONG; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/BLOCK_NEXT_TURN |
| Colorless | PROWESS | foundation-v4 | engine 注册；其余已接通 | — | — |
| Colorless | PURITY | existing | engine 注册；其余已接通 | — | — |
| Colorless | RALLY | batch5-v5 | engine 注册；其余已接通 | single-player-noop/native ALL_ALLIES effect targets teammates only; playable no-op in single-player | — |
| Colorless | REND | simple-v3 | engine 注册；其余已接通 | — | — |
| Colorless | RESTLESSNESS | existing | engine 注册；其余已接通 | — | — |
| Colorless | ROLLING_BOULDER | pending | engine 注册；其余待审计 | — | scope_deferred/turn-start counter power contract not implemented yet; mechanic_descriptor/cards/ROLLING_BOULDER; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/ROLLING_BOULDER |
| Colorless | SALVO | batch1-v1 | engine 注册；其余已接通 | — | — |
| Colorless | SCRAWL | batch1-v1 | engine 注册；其余已接通 | — | — |
| Colorless | SECRET_TECHNIQUE | foundation-v4 | engine 注册；其余已接通 | — | — |
| Colorless | SECRET_WEAPON | foundation-v4 | engine 注册；其余已接通 | — | — |
| Colorless | SEEKER_STRIKE | foundation-v4 | engine 注册；其余已接通 | — | — |
| Colorless | SHOCKWAVE | foundation-v4 | engine 注册；其余已接通 | — | — |
| Colorless | SPLASH | pending | engine 注册；其余待审计 | — | scope_deferred/cross-character generation outside scope; mechanic_descriptor/cards/SPLASH; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | STRATAGEM | foundation-v4 | engine 注册；其余已接通 | — | — |
| Colorless | TAG_TEAM | batch5-v5 | engine 注册；其余已接通 | — | — |
| Colorless | THE_BOMB_CARD | pending | engine 注册；其余待审计 | — | scope_deferred/delayed multi-turn damage contract not implemented yet; mechanic_descriptor/cards/THE_BOMB_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/THE_BOMB |
| Colorless | THE_GAMBIT | pending | engine 注册；其余待审计 | — | scope_deferred/combat-lethal debuff contract not implemented yet; mechanic_descriptor/cards/THE_GAMBIT; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/THE_GAMBIT |
| Colorless | THINKING_AHEAD | foundation-v4 | engine 注册；其余已接通 | — | — |
| Colorless | THRUMMING_HATCHET | batch5-v5 | engine 注册；其余已接通 | return-to-hand/returns to hand before the next hand draw | — |
| Colorless | ULTIMATE_DEFEND | batch1-v1 | engine 注册；其余已接通 | — | — |
| Colorless | ULTIMATE_STRIKE | batch1-v1 | engine 注册；其余已接通 | — | — |
| Colorless | VOLLEY | simple-v3 | engine 注册；其余已接通 | — | — |
