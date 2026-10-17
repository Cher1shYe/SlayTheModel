# 战士与无色牌覆盖清单

范围：151 个 ID（战士 87、无色 64）。当前接通 70，待接通 81。

engine 的 registered 仅表示原生工厂及效果函数存在，不等于完整机制正确性。
接通仅限单人 Ironclad、无遗物药水、既有十个遭遇；本次未运行训练或最终留出。
逐层状态、升级版描述摘要与源码依赖提示见同名 JSON；依赖提示不是机制实现。

| 牌池 | ID | 批次 | 六链路状态 | 阻塞路径／直接能力依赖 |
|---|---|---|---|---|
| Ironclad | AGGRESSION_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/AGGRESSION_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/AGGRESSION |
| Ironclad | ANGER | existing | engine 注册；其余已接通 | — |
| Ironclad | ARMAMENTS | existing | engine 注册；其余已接通 | — |
| Ironclad | ASHEN_STRIKE | existing | engine 注册；其余已接通 | — |
| Ironclad | BARRICADE_CARD | powers-v2 | engine 注册；其余已接通 | — |
| Ironclad | BASH | existing | engine 注册；其余已接通 | — |
| Ironclad | BATTLE_TRANCE | simple-v3 | engine 注册；其余已接通 | — |
| Ironclad | BLOOD_WALL | batch1-v1 | engine 注册；其余已接通 | — |
| Ironclad | BLOODLETTING | existing | engine 注册；其余已接通 | — |
| Ironclad | BLUDGEON | existing | engine 注册；其余已接通 | — |
| Ironclad | BODY_SLAM | existing | engine 注册；其余已接通 | — |
| Ironclad | BRAND | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/BRAND; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/STRENGTH |
| Ironclad | BREAK | batch1-v1 | engine 注册；其余已接通 | — |
| Ironclad | BREAKTHROUGH | batch1-v1 | engine 注册；其余已接通 | — |
| Ironclad | BULLY | batch1-v1 | engine 注册；其余已接通 | — |
| Ironclad | BURNING_PACT | existing | engine 注册；其余已接通 | — |
| Ironclad | CASCADE | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/CASCADE; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Ironclad | CINDER | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/CINDER; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Ironclad | COLOSSUS_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/COLOSSUS_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/COLOSSUS |
| Ironclad | CONFLAGRATION | simple-v3 | engine 注册；其余已接通 | — |
| Ironclad | CORRUPTION_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/CORRUPTION_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/CORRUPTION |
| Ironclad | CRIMSON_MANTLE | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/CRIMSON_MANTLE; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/CRIMSON_MANTLE |
| Ironclad | CRUELTY_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/CRUELTY_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/CRUELTY |
| Ironclad | DARK_EMBRACE_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/DARK_EMBRACE_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/DARK_EMBRACE |
| Ironclad | DEFEND_IRONCLAD | existing | engine 注册；其余已接通 | — |
| Ironclad | DEMON_FORM_CARD | powers-v2 | engine 注册；其余已接通 | — |
| Ironclad | DEMONIC_SHIELD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/DEMONIC_SHIELD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; multiplayer_target_contract |
| Ironclad | DISMANTLE | batch1-v1 | engine 注册；其余已接通 | — |
| Ironclad | DOMINATE | batch1-v1 | engine 注册；其余已接通 | — |
| Ironclad | DRUM_OF_BATTLE_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/DRUM_OF_BATTLE_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/DRUM_OF_BATTLE |
| Ironclad | EVIL_EYE | simple-v3 | engine 注册；其余已接通 | — |
| Ironclad | EXPECT_A_FIGHT | simple-v3 | engine 注册；其余已接通 | — |
| Ironclad | FEED | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/FEED; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Ironclad | FEEL_NO_PAIN_CARD | powers-v2 | engine 注册；其余已接通 | — |
| Ironclad | FIEND_FIRE | simple-v3 | engine 注册；其余已接通 | — |
| Ironclad | FIGHT_ME | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/FIGHT_ME; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/STRENGTH |
| Ironclad | FLAME_BARRIER_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/FLAME_BARRIER_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/FLAME_BARRIER |
| Ironclad | FORGOTTEN_RITUAL | simple-v3 | engine 注册；其余已接通 | — |
| Ironclad | GRAPPLE | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/GRAPPLE; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/GRAPPLE |
| Ironclad | HAVOC | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/HAVOC; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Ironclad | HEADBUTT | existing | engine 注册；其余已接通 | — |
| Ironclad | HELLRAISER_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/HELLRAISER_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/HELLRAISER |
| Ironclad | HEMOKINESIS | existing | engine 注册；其余已接通 | — |
| Ironclad | HOWL_FROM_BEYOND | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/HOWL_FROM_BEYOND; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; registered_hooks/_CARD_BEFORE_HAND_DRAW_HOOKS |
| Ironclad | IMPERVIOUS | existing | engine 注册；其余已接通 | — |
| Ironclad | INFERNAL_BLADE | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/INFERNAL_BLADE; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Ironclad | INFERNO_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/INFERNO_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/INFERNO |
| Ironclad | INFLAME | existing | engine 注册；其余已接通 | — |
| Ironclad | IRON_WAVE | existing | engine 注册；其余已接通 | — |
| Ironclad | JUGGERNAUT_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/JUGGERNAUT_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/JUGGERNAUT |
| Ironclad | JUGGLING_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/JUGGLING_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/JUGGLING |
| Ironclad | MANGLE | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/MANGLE; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/MANGLE |
| Ironclad | MOLTEN_FIST | batch1-v1 | engine 注册；其余已接通 | — |
| Ironclad | OFFERING | existing | engine 注册；其余已接通 | — |
| Ironclad | ONE_TWO_PUNCH_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/ONE_TWO_PUNCH_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/ONE_TWO_PUNCH |
| Ironclad | PACTS_END | simple-v3 | engine 注册；其余已接通 | — |
| Ironclad | PERFECTED_STRIKE | simple-v3 | engine 注册；其余已接通 | — |
| Ironclad | PILLAGE | simple-v3 | engine 注册；其余已接通 | — |
| Ironclad | POMMEL_STRIKE | existing | engine 注册；其余已接通 | — |
| Ironclad | PRIMAL_FORCE | existing | engine 注册；其余已接通 | — |
| Ironclad | PYRE | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/PYRE; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/PYRE |
| Ironclad | RAGE_CARD | powers-v2 | engine 注册；其余已接通 | — |
| Ironclad | RAMPAGE | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/RAMPAGE; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Ironclad | RUPTURE_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/RUPTURE_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/RUPTURE |
| Ironclad | SECOND_WIND | simple-v3 | engine 注册；其余已接通 | — |
| Ironclad | SETUP_STRIKE_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/SETUP_STRIKE_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/SETUP_STRIKE |
| Ironclad | SHRUG_IT_OFF | existing | engine 注册；其余已接通 | — |
| Ironclad | SPITE | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/SPITE; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Ironclad | STAMPEDE_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/STAMPEDE_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/STAMPEDE |
| Ironclad | STOKE | simple-v3 | engine 注册；其余已接通 | — |
| Ironclad | STOMP | existing | engine 注册；其余已接通 | — |
| Ironclad | STONE_ARMOR | simple-v3 | engine 注册；其余已接通 | — |
| Ironclad | STRIKE_IRONCLAD | existing | engine 注册；其余已接通 | — |
| Ironclad | SWORD_BOOMERANG | simple-v3 | engine 注册；其余已接通 | — |
| Ironclad | TANK_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/TANK_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/TANK |
| Ironclad | TAUNT | batch1-v1 | engine 注册；其余已接通 | — |
| Ironclad | TEAR_ASUNDER | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/TEAR_ASUNDER; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Ironclad | THRASH | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/THRASH; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Ironclad | THUNDERCLAP | existing | engine 注册；其余已接通 | — |
| Ironclad | TREMBLE | batch1-v1 | engine 注册；其余已接通 | — |
| Ironclad | TRUE_GRIT | existing | engine 注册；其余已接通 | — |
| Ironclad | TWIN_STRIKE | existing | engine 注册；其余已接通 | — |
| Ironclad | UNMOVABLE | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/UNMOVABLE; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/UNMOVABLE |
| Ironclad | UNRELENTING | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/UNRELENTING; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/FREE_ATTACK |
| Ironclad | UPPERCUT | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/UPPERCUT; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/VULNERABLE,WEAK |
| Ironclad | VICIOUS_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/VICIOUS_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/VICIOUS |
| Ironclad | WHIRLWIND | existing | engine 注册；其余已接通 | — |
| Colorless | ALCHEMIZE | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/ALCHEMIZE; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | ANOINTED | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/ANOINTED; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | AUTOMATION | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/AUTOMATION; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/AUTOMATION |
| Colorless | BEACON_OF_HOPE | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/BEACON_OF_HOPE; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/BEACON_OF_HOPE |
| Colorless | BEAT_DOWN | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/BEAT_DOWN; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | BELIEVE_IN_YOU | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/BELIEVE_IN_YOU; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; multiplayer_target_contract |
| Colorless | BOLAS | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/BOLAS; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | CALAMITY_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/CALAMITY_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/CALAMITY |
| Colorless | CATASTROPHE | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/CATASTROPHE; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | COORDINATE_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/COORDINATE_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/COORDINATE; multiplayer_target_contract |
| Colorless | DARK_SHACKLES | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/DARK_SHACKLES; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/DARK_SHACKLES |
| Colorless | DISCOVERY | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/DISCOVERY; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | DRAMATIC_ENTRANCE | simple-v3 | engine 注册；其余已接通 | — |
| Colorless | ENTROPY | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/ENTROPY; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/ENTROPY |
| Colorless | EQUILIBRIUM | existing | engine 注册；其余已接通 | — |
| Colorless | ETERNAL_ARMOR | powers-v2 | engine 注册；其余已接通 | — |
| Colorless | FASTEN | powers-v2 | engine 注册；其余已接通 | — |
| Colorless | FINESSE | batch1-v1 | engine 注册；其余已接通 | — |
| Colorless | FISTICUFFS | simple-v3 | engine 注册；其余已接通 | — |
| Colorless | FLASH_OF_STEEL | batch1-v1 | engine 注册；其余已接通 | — |
| Colorless | GANG_UP | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/GANG_UP; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | GOLD_AXE | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/GOLD_AXE; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | HAND_OF_GREED | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/HAND_OF_GREED; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | HIDDEN_GEM | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/HIDDEN_GEM; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | HUDDLE_UP | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/HUDDLE_UP; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; multiplayer_target_contract |
| Colorless | IMPATIENCE | simple-v3 | engine 注册；其余已接通 | — |
| Colorless | INTERCEPT_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/INTERCEPT_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/COVERED; multiplayer_target_contract |
| Colorless | JACK_OF_ALL_TRADES | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/JACK_OF_ALL_TRADES; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | JACKPOT | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/JACKPOT; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | KNOCKDOWN | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/KNOCKDOWN; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/KNOCKDOWN |
| Colorless | LIFT | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/LIFT; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; multiplayer_target_contract |
| Colorless | MASTER_OF_STRATEGY | batch1-v1 | engine 注册；其余已接通 | — |
| Colorless | MAYHEM_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/MAYHEM_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/MAYHEM |
| Colorless | MIMIC | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/MIMIC; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; multiplayer_target_contract |
| Colorless | MIND_BLAST | simple-v3 | engine 注册；其余已接通 | — |
| Colorless | NOSTALGIA_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/NOSTALGIA_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/NOSTALGIA |
| Colorless | OMNISLICE | simple-v3 | engine 注册；其余已接通 | — |
| Colorless | PANACHE_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/PANACHE_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/PANACHE |
| Colorless | PANIC_BUTTON | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/PANIC_BUTTON; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/NO_BLOCK |
| Colorless | PREP_TIME | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/PREP_TIME; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/PREP_TIME |
| Colorless | PRODUCTION | batch1-v1 | engine 注册；其余已接通 | — |
| Colorless | PROLONG | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/PROLONG; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/BLOCK_NEXT_TURN |
| Colorless | PROWESS | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/PROWESS; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/DEXTERITY,STRENGTH |
| Colorless | PURITY | existing | engine 注册；其余已接通 | — |
| Colorless | RALLY | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/RALLY; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; multiplayer_target_contract |
| Colorless | REND | simple-v3 | engine 注册；其余已接通 | — |
| Colorless | RESTLESSNESS | existing | engine 注册；其余已接通 | — |
| Colorless | ROLLING_BOULDER | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/ROLLING_BOULDER; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/ROLLING_BOULDER |
| Colorless | SALVO | batch1-v1 | engine 注册；其余已接通 | — |
| Colorless | SCRAWL | batch1-v1 | engine 注册；其余已接通 | — |
| Colorless | SECRET_TECHNIQUE | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/SECRET_TECHNIQUE; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | SECRET_WEAPON | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/SECRET_WEAPON; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | SEEKER_STRIKE | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/SEEKER_STRIKE; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | SHOCKWAVE | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/SHOCKWAVE; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/VULNERABLE,WEAK |
| Colorless | SPLASH | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/SPLASH; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | STRATAGEM | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/STRATAGEM; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/STRATAGEM |
| Colorless | TAG_TEAM | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/TAG_TEAM; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/TAG_TEAM |
| Colorless | THE_BOMB_CARD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/THE_BOMB_CARD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/THE_BOMB |
| Colorless | THE_GAMBIT | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/THE_GAMBIT; public_state_and_action_admission; particle_reconstruction_and_interaction_parity; power_dependencies/THE_GAMBIT |
| Colorless | THINKING_AHEAD | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/THINKING_AHEAD; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | THRUMMING_HATCHET | pending | engine 注册；其余待审计 | mechanic_descriptor/cards/THRUMMING_HATCHET; public_state_and_action_admission; particle_reconstruction_and_interaction_parity |
| Colorless | ULTIMATE_DEFEND | batch1-v1 | engine 注册；其余已接通 | — |
| Colorless | ULTIMATE_STRIKE | batch1-v1 | engine 注册；其余已接通 | — |
| Colorless | VOLLEY | simple-v3 | engine 注册；其余已接通 | — |
