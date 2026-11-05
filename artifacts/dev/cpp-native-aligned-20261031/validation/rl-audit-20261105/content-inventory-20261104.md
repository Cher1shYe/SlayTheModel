# Content inventory (generated 2026-11-04)

Ruleset `native-41cef1ea-port-v10`; source = current tree. Reference game build on this machine: local DLL sha256 `0861bfa1...` (target `9cb4f1ad...` unavailable). Evidence is port self-test coverage, not native differential.

## cards: 596 entries
- no source-effect reference: 0
- no automated test reference: 368

## potions: 66 entries
- no source-effect reference: 1
- no automated test reference: 0

## relics: 300 entries
- no source-effect reference: 2
- no automated test reference: 0

### IRONCLAD cards (91)
| id | name | type | rarity | flags | effect files | tests |
|---|---|---|---|---|---|---|
| AGGRESSION_CARD | Aggression | POWER | RARE | - | cards_ironclad.cpp | rules_regression.cpp |
| ANGER | Anger | ATTACK | COMMON | - | cards_ironclad.cpp | monster_audit_regression.cpp,native_card_alignment.cpp,native_event_oracle_alignment.cpp,native_event_round3_alignment.cpp,native_relic_round2_alignment.cpp,native_relic_round3_alignment.cpp,native_run_alignment.cpp,rules_regression.cpp,test_armg_need.py,test_content.py |
| ARMAMENTS | Armaments | SKILL | COMMON | - | cards_ironclad.cpp | native_card_round3_alignment.cpp,rules_regression.cpp |
| ASHEN_STRIKE | Ashen Strike | ATTACK | UNCOMMON | - | battle.cpp,cards_ironclad.cpp | monster_audit_regression.cpp,native_card_alignment.cpp |
| BARRICADE_CARD | Barricade | POWER | RARE | - | cards_ironclad.cpp | native_step1_downgrade.cpp,rules_regression.cpp |
| BASH | Bash | ATTACK | BASIC | - | cards_ironclad.cpp,events.cpp,relics.cpp,run.cpp | hidden_resampling.cpp,mcts_regression.cpp,native_card_alignment.cpp,native_card_round3_alignment.cpp,native_event_oracle_alignment.cpp,native_event_round3_alignment.cpp,native_relic_round2_alignment.cpp,native_relic_round3_alignment.cpp,native_run_alignment.cpp,native_step2_persistent.cpp,native_step2_relic_lifecycle.cpp,native_underdocks_events.cpp,relic_coverage_round7.cpp,rules_regression.cpp,snapshot_validation.cpp,test_armg_need.py,test_content.py,test_effects.py,test_run_reward.py |
| BATTLE_TRANCE | Battle Trance | SKILL | UNCOMMON | - | cards_ironclad.cpp | monster_audit_regression.cpp |
| BLOOD_WALL | Blood Wall | SKILL | COMMON | - | cards_ironclad.cpp | native_relic_round2_alignment.cpp,native_relic_round3_alignment.cpp,native_run_alignment.cpp |
| BLOODLETTING | Bloodletting | SKILL | UNCOMMON | - | cards_ironclad.cpp | rules_regression.cpp |
| BLUDGEON | Bludgeon | ATTACK | UNCOMMON | - | cards_ironclad.cpp | test_effects.py,test_rules.py |
| BODY_SLAM | Body Slam | ATTACK | COMMON | - | battle.cpp,cards_ironclad.cpp | native_card_alignment.cpp |
| BRAND | Brand | SKILL | RARE | - | battle.cpp,cards_ironclad.cpp | - |
| BREAK | Break | ATTACK | ANCIENT | - | cards_ironclad.cpp,relic_card_rewards.cpp,relics.cpp | relic_coverage_round7.cpp,test_content.py,test_run_reward.py |
| BREAKTHROUGH | Breakthrough | ATTACK | COMMON | - | cards_ironclad.cpp | - |
| BULLY | Bully | ATTACK | UNCOMMON | - | battle.cpp,cards_ironclad.cpp | native_card_alignment.cpp |
| BURNING_PACT | Burning Pact | SKILL | UNCOMMON | - | battle.cpp,cards_ironclad.cpp | enchantment_contract.cpp |
| CASCADE | Cascade | SKILL | RARE | - | cards_ironclad.cpp | native_card_round3_alignment.cpp |
| CINDER | Cinder | ATTACK | COMMON | - | cards_ironclad.cpp | native_card_alignment.cpp |
| COLOSSUS_CARD | Colossus | SKILL | UNCOMMON | - | cards_ironclad.cpp | rules_regression.cpp |
| CONFLAGRATION | Conflagration | ATTACK | RARE | - | cards_ironclad.cpp | native_card_round3_alignment.cpp |
| CORRUPTION_CARD | Corruption | POWER | ANCIENT | - | cards_ironclad.cpp | native_step1_downgrade.cpp,rules_regression.cpp,test_run_reward.py |
| CRIMSON_MANTLE | Crimson Mantle | POWER | RARE | - | cards_ironclad.cpp | native_step1_self_damage.cpp,test_native_step1_state.py |
| CRUELTY_CARD | Cruelty | POWER | UNCOMMON | - | cards_ironclad.cpp | rules_regression.cpp |
| DARK_EMBRACE_CARD | Dark Embrace | POWER | RARE | - | cards_ironclad.cpp | native_step1_downgrade.cpp,rules_regression.cpp |
| DEFEND_IRONCLAD | Defend | SKILL | BASIC | - | cards_ironclad.cpp,relic_lifecycle.cpp,run.cpp | audit_rl_regressions.cpp,enchantment_contract.cpp,hidden_resampling.cpp,map_event_audit_regression.cpp,mcts_regression.cpp,monster_audit_regression.cpp,native_card_alignment.cpp,native_card_round3_alignment.cpp,native_event_oracle_alignment.cpp,native_event_round3_alignment.cpp,native_relic_round2_alignment.cpp,native_relic_round3_alignment.cpp,native_run_alignment.cpp,native_step1_self_damage.cpp,native_step2_persistent.cpp,native_step2_relic_lifecycle.cpp,native_step2_silent.cpp,native_underdocks_events.cpp,observation_contract.cpp,regent_mechanics.cpp,relic_coverage_round7.cpp,relic_shared_round5.cpp,rules_regression.cpp,test_armg_need.py,test_audit_rl_fixes.py,test_content.py,test_effects.py,test_mcts_hidden_depth.py,test_mcts_value_leaf.py,test_rules.py,test_run_reward.py,test_step2_rules_20261104.py |
| DEMON_FORM_CARD | Demon Form | POWER | RARE | - | cards_ironclad.cpp | multiplayer_cards.cpp,relic_coverage_round7.cpp |
| DEMONIC_SHIELD | Demonic Shield | SKILL | UNCOMMON | MULTIPLAYER_ONLY,EXHAUST | cards_ironclad.cpp | multiplayer_cards.cpp |
| DISMANTLE | Dismantle | ATTACK | UNCOMMON | - | cards_ironclad.cpp | - |
| DOMINATE | Dominate | SKILL | RARE | EXHAUST | cards_ironclad.cpp | native_card_round3_alignment.cpp |
| DRUM_OF_BATTLE_CARD | Drum of Battle | SKILL | UNCOMMON | - | battle.cpp,cards_ironclad.cpp | native_card_round3_alignment.cpp,rules_regression.cpp |
| EVIL_EYE | Evil Eye | SKILL | UNCOMMON | - | cards_ironclad.cpp | - |
| EXPECT_A_FIGHT | Expect a Fight | SKILL | UNCOMMON | - | cards_ironclad.cpp | native_underdocks_events.cpp |
| FEED | Feed | ATTACK | RARE | CANNOT_GENERATE,EXHAUST | cards_ironclad.cpp | native_card_round3_alignment.cpp,rules_regression.cpp,test_armg_need.py |
| FEEL_NO_PAIN_CARD | Feel No Pain | POWER | UNCOMMON | - | cards_ironclad.cpp | rules_regression.cpp |
| FIEND_FIRE | Fiend Fire | ATTACK | RARE | EXHAUST | cards_ironclad.cpp | native_card_round3_alignment.cpp,rules_regression.cpp |
| FIGHT_ME | Fight Me! | ATTACK | UNCOMMON | - | cards_ironclad.cpp | native_relic_round2_alignment.cpp,native_relic_round3_alignment.cpp,native_run_alignment.cpp,test_run_reward.py |
| FLAME_BARRIER_CARD | Flame Barrier | SKILL | UNCOMMON | - | cards_ironclad.cpp | - |
| FORGOTTEN_RITUAL | Forgotten Ritual | SKILL | UNCOMMON | EXHAUST | cards_ironclad.cpp | - |
| GRAPPLE | GRAPPLE | ATTACK | UNCOMMON | - | cards.cpp,cards_ironclad.cpp | native_card_round3_alignment.cpp,rules_regression.cpp,test_smoke.py |
| HAVOC | Havoc | SKILL | COMMON | - | cards_ironclad.cpp | rules_regression.cpp |
| HEADBUTT | Headbutt | ATTACK | COMMON | - | cards_ironclad.cpp | rules_regression.cpp |
| HELLRAISER_CARD | Hellraiser | POWER | RARE | - | cards_ironclad.cpp | monster_audit_regression.cpp,rules_regression.cpp |
| HEMOKINESIS | Hemokinesis | ATTACK | UNCOMMON | - | cards_ironclad.cpp | - |
| HOWL_FROM_BEYOND | Howl from Beyond | ATTACK | UNCOMMON | - | battle_turns.cpp,cards_ironclad.cpp | rules_regression.cpp |
| IMPERVIOUS | Impervious | SKILL | RARE | EXHAUST | cards_ironclad.cpp | native_card_round3_alignment.cpp,rules_regression.cpp |
| INFERNAL_BLADE | Infernal Blade | SKILL | UNCOMMON | EXHAUST | cards_ironclad.cpp | rules_regression.cpp |
| INFERNO_CARD | Inferno | POWER | UNCOMMON | - | cards_ironclad.cpp | native_step1_self_damage.cpp,test_native_step1_state.py |
| INFLAME | Inflame | POWER | UNCOMMON | - | cards_ironclad.cpp | hidden_resampling.cpp,rules_regression.cpp |
| IRON_WAVE | Iron Wave | ATTACK | COMMON | - | cards_ironclad.cpp | native_event_oracle_alignment.cpp,native_event_round3_alignment.cpp,native_relic_round2_alignment.cpp,native_relic_round3_alignment.cpp,native_run_alignment.cpp |
| JUGGERNAUT_CARD | Juggernaut | POWER | RARE | - | cards_ironclad.cpp | - |
| JUGGLING_CARD | Juggling | POWER | UNCOMMON | - | cards_ironclad.cpp | rules_regression.cpp |
| MANGLE | Mangle | ATTACK | RARE | - | cards_ironclad.cpp | test_rules.py |
| MOLTEN_FIST | Molten Fist | ATTACK | COMMON | EXHAUST | cards_ironclad.cpp | - |
| OFFERING | Offering | SKILL | RARE | EXHAUST | cards_ironclad.cpp | native_relic_round3_alignment.cpp,rules_regression.cpp |
| ONE_TWO_PUNCH_CARD | One-Two Punch | SKILL | RARE | - | cards_ironclad.cpp | test_run_reward.py |
| PACTS_END | Pact's End | ATTACK | RARE | - | cards_ironclad.cpp | test_run_reward.py |
| PERFECTED_STRIKE | Perfected Strike | ATTACK | COMMON | - | battle.cpp,cards_ironclad.cpp | native_card_alignment.cpp |
| PILLAGE | Pillage | ATTACK | UNCOMMON | - | cards_ironclad.cpp | - |
| POMMEL_STRIKE | Pommel Strike | ATTACK | COMMON | - | cards_ironclad.cpp | native_event_oracle_alignment.cpp,native_event_round3_alignment.cpp,native_relic_round2_alignment.cpp,native_relic_round3_alignment.cpp,native_run_alignment.cpp,test_effects.py |
| PRIMAL_FORCE | Primal Force | SKILL | RARE | - | cards_ironclad.cpp | native_card_round3_alignment.cpp,native_relic_round2_alignment.cpp,native_run_alignment.cpp |
| PYRE | Pyre | POWER | RARE | - | cards_ironclad.cpp | - |
| RAGE_CARD | Rage | SKILL | UNCOMMON | - | cards_ironclad.cpp | rules_regression.cpp |
| RAMPAGE | Rampage | ATTACK | UNCOMMON | - | cards_ironclad.cpp | native_relic_round2_alignment.cpp,observation_contract.cpp |
| RUPTURE_CARD | Rupture | POWER | UNCOMMON | - | cards_ironclad.cpp | native_round3_shared_alignment.cpp,rules_regression.cpp |
| SECOND_WIND | Second Wind | SKILL | UNCOMMON | - | cards_ironclad.cpp | native_card_round3_alignment.cpp,native_relic_round3_alignment.cpp,rules_regression.cpp |
| SETUP_STRIKE_CARD | Setup Strike | ATTACK | COMMON | - | cards_ironclad.cpp | native_card_alignment.cpp,native_relic_round2_alignment.cpp,rules_regression.cpp |
| SHRUG_IT_OFF | Shrug It Off | SKILL | COMMON | - | cards_ironclad.cpp | native_card_round3_alignment.cpp,native_relic_round2_alignment.cpp,test_armg_need.py |
| SPITE | Spite | ATTACK | UNCOMMON | - | cards_ironclad.cpp | native_card_round3_alignment.cpp |
| STAMPEDE_CARD | Stampede | POWER | UNCOMMON | - | cards_ironclad.cpp | rules_regression.cpp |
| STOKE | Stoke | SKILL | RARE | - | cards_ironclad.cpp | native_card_round3_alignment.cpp,rules_regression.cpp |
| STOMP | Stomp | ATTACK | UNCOMMON | - | battle.cpp,cards_ironclad.cpp | rules_regression.cpp |
| STONE_ARMOR | Stone Armor | POWER | UNCOMMON | - | cards_ironclad.cpp | - |
| STRIKE_IRONCLAD | Strike | ATTACK | BASIC | - | cards.cpp,cards_ironclad.cpp,relic_lifecycle.cpp,relics.cpp,run.cpp | audit_rl_regressions.cpp,character_potions.cpp,enchantment_contract.cpp,hidden_resampling.cpp,knowledge_curse.cpp,map_event_audit_regression.cpp,mcts_regression.cpp,monster_audit_regression.cpp,multiplayer_cards.cpp,native_card_alignment.cpp,native_card_round3_alignment.cpp,native_event_oracle_alignment.cpp,native_event_round3_alignment.cpp,native_relic_round2_alignment.cpp,native_relic_round3_alignment.cpp,native_round3_shared_alignment.cpp,native_run_alignment.cpp,native_step1_downgrade.cpp,native_step2_relic_lifecycle.cpp,native_step2_silent.cpp,observation_contract.cpp,potion_coverage_round7.cpp,quest_cards.cpp,regent_mechanics.cpp,relic_contract.cpp,relic_coverage_round7.cpp,relic_event_audit.cpp,relic_shared_round5.cpp,rules_regression.cpp,snapshot_validation.cpp,test_armg_need.py,test_audit_rl_fixes.py,test_binding_schema_contract.py,test_content.py,test_effects.py,test_mcts_depth_priors.py,test_mcts_hidden_depth.py,test_mcts_value_leaf.py,test_rules.py,test_run_reward.py |
| SWORD_BOOMERANG | Sword Boomerang | ATTACK | COMMON | - | cards_ironclad.cpp | native_card_round3_alignment.cpp,native_round3_shared_alignment.cpp,test_rules.py |
| TANK_CARD | Tank | POWER | RARE | MULTIPLAYER_ONLY | cards_ironclad.cpp | multiplayer_cards.cpp,relic_coverage_round7.cpp,rules_regression.cpp |
| TAUNT | Taunt | SKILL | COMMON | - | cards_ironclad.cpp | native_relic_round2_alignment.cpp |
| TEAR_ASUNDER | Tear Asunder | ATTACK | RARE | - | cards_ironclad.cpp | - |
| THRASH | Thrash | ATTACK | RARE | - | cards_ironclad.cpp | native_card_alignment.cpp,native_step1_downgrade.cpp,observation_contract.cpp,rules_regression.cpp |
| THUNDERCLAP | Thunderclap | ATTACK | COMMON | - | cards_ironclad.cpp | rules_regression.cpp |
| TREMBLE | Tremble | SKILL | COMMON | EXHAUST | cards_ironclad.cpp | - |
| TRUE_GRIT | True Grit | SKILL | COMMON | - | cards_ironclad.cpp | native_relic_round2_alignment.cpp,test_effects.py |
| TWIN_STRIKE | Twin Strike | ATTACK | COMMON | - | cards_ironclad.cpp | rules_regression.cpp |
| UNMOVABLE | Unmovable | POWER | RARE | - | cards_ironclad.cpp | rules_regression.cpp |
| UNRELENTING | Unrelenting | ATTACK | UNCOMMON | - | cards_ironclad.cpp | - |
| UPPERCUT | Uppercut | ATTACK | UNCOMMON | - | cards_ironclad.cpp | - |
| VICIOUS_CARD | Vicious | POWER | UNCOMMON | - | cards_ironclad.cpp | - |
| WHIRLWIND | Whirlwind | ATTACK | UNCOMMON | - | cards_ironclad.cpp | native_relic_round2_alignment.cpp,rules_regression.cpp,test_armg_need.py |
| NOT_YET | Not Yet | SKILL | RARE | CANNOT_GENERATE,EXHAUST | cards_ironclad.cpp | native_card_round3_alignment.cpp |
| BLAZE | Blaze | SKILL | UNCOMMON | MULTIPLAYER_ONLY | cards_ironclad.cpp | multiplayer_cards.cpp |
| MIDNIGHT | Midnight | ATTACK | RARE | MULTIPLAYER_ONLY | battle.cpp,cards_ironclad.cpp | multiplayer_cards.cpp |
| OUTRAGE | Outrage | ATTACK | UNCOMMON | MULTIPLAYER_ONLY | cards_ironclad.cpp | multiplayer_cards.cpp |

### SILENT cards (91)
| id | name | type | rarity | flags | effect files | tests |
|---|---|---|---|---|---|---|
| ABRASIVE | Abrasive | POWER | RARE | - | cards_silent.cpp | - |
| ACCELERANT | Accelerant | POWER | UNCOMMON | - | cards_silent.cpp | - |
| ACCURACY | Accuracy | POWER | UNCOMMON | - | cards_silent.cpp | - |
| ACROBATICS | Acrobatics | SKILL | UNCOMMON | - | cards_silent.cpp | - |
| ADRENALINE | Adrenaline | SKILL | RARE | EXHAUST | cards_silent.cpp | - |
| AFTERIMAGE | Afterimage | POWER | RARE | - | cards_silent.cpp | - |
| ANTICIPATE | Anticipate | SKILL | COMMON | - | cards_silent.cpp | - |
| ASSASSINATE | Assassinate | ATTACK | RARE | EXHAUST,INNATE | cards_silent.cpp | - |
| BACKFLIP | Backflip | SKILL | COMMON | - | cards_silent.cpp | - |
| BACKSTAB | Backstab | ATTACK | UNCOMMON | EXHAUST,INNATE | cards_silent.cpp | - |
| BLADE_DANCE | Blade Dance | SKILL | COMMON | EXHAUST | cards_silent.cpp | - |
| BLADE_OF_INK | Blade Of Ink | SKILL | RARE | - | cards_silent.cpp | - |
| BLADE_SYMPHONY | Blade Symphony | SKILL | UNCOMMON | MULTIPLAYER_ONLY | cards_silent.cpp | - |
| BLUR | Blur | SKILL | UNCOMMON | - | cards_silent.cpp | - |
| BOUNCING_FLASK | Bouncing Flask | SKILL | UNCOMMON | - | cards_silent.cpp | - |
| BUBBLE_BUBBLE | Bubble Bubble | SKILL | UNCOMMON | - | cards_silent.cpp | - |
| BULLET_TIME | Bullet Time | SKILL | RARE | - | cards_silent.cpp | - |
| BURST | Burst | SKILL | RARE | - | cards_silent.cpp | - |
| CALCULATED_GAMBLE | Calculated Gamble | SKILL | UNCOMMON | EXHAUST | cards_silent.cpp | - |
| CLOAK_AND_DAGGER | Cloak And Dagger | SKILL | COMMON | - | cards_silent.cpp | - |
| CONCOCT | Concoct | SKILL | UNCOMMON | MULTIPLAYER_ONLY | cards_silent.cpp | - |
| CORROSIVE_WAVE | Corrosive Wave | SKILL | RARE | - | cards_silent.cpp | - |
| DAGGER_SPRAY | Dagger Spray | ATTACK | COMMON | - | cards_silent.cpp | - |
| DAGGER_THROW | Dagger Throw | ATTACK | COMMON | - | cards_silent.cpp | - |
| DASH | Dash | ATTACK | UNCOMMON | - | cards_silent.cpp | - |
| DEADLY_POISON | Deadly Poison | SKILL | COMMON | - | cards_silent.cpp | - |
| DEFEND_SILENT | Defend Silent | SKILL | BASIC | - | cards_silent.cpp,run.cpp | native_step2_silent.cpp,relic_coverage_round7.cpp |
| DEFLECT | Deflect | SKILL | COMMON | - | cards_silent.cpp | - |
| DODGE_AND_ROLL | Dodge And Roll | SKILL | COMMON | - | cards_silent.cpp | - |
| ECHOING_SLASH | Echoing Slash | ATTACK | UNCOMMON | - | cards_silent.cpp | - |
| ENVENOM | Envenom | POWER | RARE | - | cards_silent.cpp | - |
| ESCAPE_PLAN | Escape Plan | SKILL | UNCOMMON | - | cards_silent.cpp | - |
| EXPERTISE | Expertise | SKILL | UNCOMMON | - | cards_silent.cpp | rules_regression.cpp |
| EXPOSE | Expose | SKILL | UNCOMMON | EXHAUST | cards_silent.cpp | - |
| FADE | Fade | SKILL | UNCOMMON | MULTIPLAYER_ONLY,RETAIN | cards_silent.cpp | - |
| FAN_OF_KNIVES | Fan Of Knives | POWER | RARE | - | cards_silent.cpp | - |
| FINISHER | Finisher | ATTACK | UNCOMMON | - | cards_silent.cpp | - |
| FLANKING | Flanking | SKILL | RARE | MULTIPLAYER_ONLY | cards_silent.cpp | - |
| FLECHETTES | Flechettes | ATTACK | UNCOMMON | - | cards_silent.cpp | - |
| FLICK_FLACK | Flick Flack | ATTACK | COMMON | - | cards_silent.cpp | - |
| FOOTWORK | Footwork | POWER | UNCOMMON | - | cards_silent.cpp | - |
| GRAND_FINALE | Grand Finale | ATTACK | RARE | - | cards_silent.cpp,silent.cpp | - |
| HAND_TRICK | Hand Trick | SKILL | UNCOMMON | - | cards_silent.cpp | - |
| HAZE | Haze | SKILL | UNCOMMON | - | cards_silent.cpp | - |
| HIDDEN_DAGGERS | Hidden Daggers | SKILL | UNCOMMON | - | cards_silent.cpp | - |
| INFINITE_BLADES | Infinite Blades | POWER | UNCOMMON | - | cards_silent.cpp | - |
| KNIFE_TRAP | Knife Trap | SKILL | RARE | - | cards_silent.cpp | - |
| LEADING_STRIKE | Leading Strike | ATTACK | COMMON | - | cards_silent.cpp | - |
| LEG_SWEEP | Leg Sweep | SKILL | UNCOMMON | - | cards_silent.cpp | - |
| MALAISE | Malaise | SKILL | RARE | EXHAUST | cards_silent.cpp | - |
| MASTER_PLANNER | Master Planner | POWER | RARE | - | cards_silent.cpp | - |
| MEMENTO_MORI | Memento Mori | ATTACK | UNCOMMON | - | cards_silent.cpp | - |
| MIRAGE | Mirage | SKILL | UNCOMMON | EXHAUST | cards_silent.cpp | - |
| MURDER | Murder | ATTACK | RARE | - | cards_silent.cpp | - |
| NEUTRALIZE | Neutralize | ATTACK | BASIC | - | cards_silent.cpp,events.cpp,run.cpp | rules_regression.cpp |
| NIGHTMARE | Nightmare | SKILL | RARE | CANNOT_GENERATE,EXHAUST | cards_silent.cpp | - |
| NOXIOUS_FUMES | Noxious Fumes | POWER | UNCOMMON | - | cards_silent.cpp | - |
| OUTBREAK | Outbreak | SKILL | RARE | - | cards_silent.cpp | - |
| PHANTOM_BLADES | Phantom Blades | POWER | UNCOMMON | - | cards_silent.cpp | - |
| PIERCING_WAIL | Piercing Wail | SKILL | COMMON | EXHAUST | cards_silent.cpp | - |
| PINPOINT | Pinpoint | ATTACK | UNCOMMON | - | cards_silent.cpp,silent.cpp | - |
| POISONED_STAB | Poisoned Stab | ATTACK | COMMON | - | cards_silent.cpp | - |
| POUNCE | Pounce | ATTACK | UNCOMMON | - | cards_silent.cpp | audit_rl_regressions.cpp,test_audit_rl_fixes.py |
| PRECISE_CUT | Precise Cut | ATTACK | UNCOMMON | - | cards_silent.cpp | - |
| PREDATOR | Predator | ATTACK | COMMON | - | cards_silent.cpp | - |
| PREPARED | Prepared | SKILL | COMMON | - | cards_silent.cpp | - |
| REFLEX | Reflex | SKILL | UNCOMMON | - | cards_silent.cpp | - |
| RICOCHET | Ricochet | ATTACK | COMMON | - | cards_silent.cpp | - |
| SERPENT_FORM | Serpent Form | POWER | RARE | - | cards_silent.cpp | - |
| SHADOW_STEP | Shadow Step | SKILL | RARE | - | cards_silent.cpp | - |
| SHADOWMELD | Shadowmeld | SKILL | RARE | - | cards_silent.cpp | - |
| SIDESTEP | Sidestep | SKILL | UNCOMMON | - | cards_silent.cpp | - |
| SKEWER | Skewer | ATTACK | UNCOMMON | - | cards_silent.cpp | - |
| SLICE | Slice | ATTACK | COMMON | - | cards_silent.cpp | - |
| SNAKEBITE | Snakebite | SKILL | COMMON | RETAIN | cards_silent.cpp | - |
| SNEAKY | Sneaky | POWER | RARE | MULTIPLAYER_ONLY | cards_silent.cpp | monster_audit_regression.cpp |
| SPEEDSTER | Speedster | POWER | UNCOMMON | - | cards_silent.cpp | - |
| STORM_OF_STEEL | Storm Of Steel | SKILL | RARE | - | cards_silent.cpp | - |
| STRANGLE | Strangle | ATTACK | UNCOMMON | - | cards_silent.cpp | rules_regression.cpp |
| STRIKE_SILENT | Strike Silent | ATTACK | BASIC | - | cards.cpp,cards_silent.cpp,run.cpp | native_step2_silent.cpp |
| SUCKER_PUNCH | Sucker Punch | ATTACK | COMMON | - | cards_silent.cpp | - |
| SUPPRESS | Suppress | ATTACK | ANCIENT | INNATE | cards_silent.cpp,relic_card_rewards.cpp | - |
| SURVIVOR | Survivor | SKILL | BASIC | - | cards_silent.cpp,run.cpp | - |
| TACTICIAN | Tactician | SKILL | UNCOMMON | - | cards_silent.cpp | - |
| THE_HUNT | The Hunt | ATTACK | RARE | CANNOT_GENERATE,EXHAUST | cards_silent.cpp | - |
| TOOLS_OF_THE_TRADE | Tools Of The Trade | POWER | RARE | - | cards_silent.cpp,silent.cpp | - |
| TRACKING | Tracking | POWER | RARE | - | cards_silent.cpp | - |
| UNTOUCHABLE | Untouchable | SKILL | COMMON | - | cards_silent.cpp | - |
| UP_MY_SLEEVE | Up My Sleeve | SKILL | UNCOMMON | - | cards_silent.cpp | - |
| WELL_LAID_PLANS | Well Laid Plans | POWER | RARE | - | cards_silent.cpp | - |
| WRAITH_FORM | Wraith Form | POWER | ANCIENT | - | cards_silent.cpp | - |

### DEFECT cards (91)
| id | name | type | rarity | flags | effect files | tests |
|---|---|---|---|---|---|---|
| ADAPTIVE_STRIKE | Adaptive Strike | ATTACK | RARE | - | cards_defect.cpp | - |
| ALL_FOR_ONE | All For One | ATTACK | RARE | - | cards_defect.cpp | - |
| BALL_LIGHTNING | Ball Lightning | ATTACK | COMMON | - | cards_defect.cpp | - |
| BARRAGE | Barrage | ATTACK | COMMON | - | cards_defect.cpp | - |
| BEAM_CELL | Beam Cell | ATTACK | COMMON | - | cards_defect.cpp | - |
| BIASED_COGNITION | Biased Cognition | POWER | ANCIENT | - | cards_defect.cpp | - |
| BOOST_AWAY | Boost Away | SKILL | COMMON | - | cards_defect.cpp | - |
| BOOT_SEQUENCE | Boot Sequence | SKILL | UNCOMMON | EXHAUST,INNATE | cards_defect.cpp | - |
| BUFFER | Buffer | POWER | RARE | - | cards_defect.cpp | potion_coverage_round7.cpp,rules_regression.cpp |
| BULK_UP | Bulk Up | POWER | UNCOMMON | - | cards_defect.cpp | - |
| CAPACITOR | Capacitor | POWER | UNCOMMON | - | cards_defect.cpp | relic_coverage_round7.cpp |
| CHAOS | Chaos | SKILL | UNCOMMON | - | cards_defect.cpp | map_event_audit_regression.cpp,rules_regression.cpp |
| CHARGE_BATTERY | Charge Battery | SKILL | COMMON | - | cards_defect.cpp | - |
| CHILL | Chill | SKILL | UNCOMMON | EXHAUST | cards_defect.cpp | - |
| CLAW | Claw | ATTACK | COMMON | - | cards_defect.cpp | map_event_audit_regression.cpp,rules_regression.cpp |
| COLD_SNAP | Cold Snap | ATTACK | COMMON | - | cards_defect.cpp | - |
| COMPACT | Compact | SKILL | UNCOMMON | - | cards_defect.cpp | - |
| COMPILE_DRIVER | Compile Driver | ATTACK | COMMON | - | cards_defect.cpp | - |
| CONSUMING_SHADOW | Consuming Shadow | POWER | RARE | - | cards_defect.cpp | - |
| COOLANT | Coolant | POWER | RARE | - | cards_defect.cpp | - |
| COOLHEADED | Coolheaded | SKILL | COMMON | - | cards_defect.cpp | - |
| CREATIVE_AI | Creative Ai | POWER | RARE | - | cards_defect.cpp | - |
| DARKNESS | Darkness | SKILL | UNCOMMON | - | cards_defect.cpp | character_potions.cpp |
| DEFEND_DEFECT | Defend Defect | SKILL | BASIC | - | cards_defect.cpp,run.cpp | - |
| DEFRAGMENT | Defragment | POWER | RARE | - | cards_defect.cpp | - |
| DOUBLE_ENERGY | Double Energy | SKILL | UNCOMMON | EXHAUST | cards_defect.cpp | - |
| DUALCAST | Dualcast | SKILL | BASIC | - | cards_defect.cpp,events.cpp,run.cpp | rules_regression.cpp |
| ECHO_FORM | Echo Form | POWER | RARE | ETHEREAL | cards_defect.cpp | - |
| ENERGY_SURGE | Energy Surge | SKILL | UNCOMMON | MULTIPLAYER_ONLY,EXHAUST | cards_defect.cpp | - |
| FERAL | Feral | POWER | UNCOMMON | - | cards_defect.cpp | - |
| FIGHT_THROUGH | Fight Through | SKILL | UNCOMMON | - | cards_defect.cpp | - |
| FLAK_CANNON | Flak Cannon | ATTACK | RARE | - | cards_defect.cpp | - |
| FOCUSED_STRIKE | Focused Strike | ATTACK | COMMON | - | cards_defect.cpp | - |
| FTL | Ftl | ATTACK | UNCOMMON | - | cards_defect.cpp | - |
| FUSION | Fusion | SKILL | UNCOMMON | EXHAUST | cards_defect.cpp | - |
| GENETIC_ALGORITHM | Genetic Algorithm | SKILL | RARE | EXHAUST | cards_defect.cpp | - |
| GLACIER | Glacier | SKILL | UNCOMMON | - | cards_defect.cpp | - |
| GLASSWORK | Glasswork | SKILL | UNCOMMON | - | cards_defect.cpp | - |
| GO_FOR_THE_EYES | Go For The Eyes | ATTACK | COMMON | - | cards_defect.cpp | - |
| GUNK_UP | Gunk Up | ATTACK | COMMON | - | cards_defect.cpp | - |
| HAILSTORM | Hailstorm | POWER | UNCOMMON | - | cards_defect.cpp | - |
| HELIX_DRILL | Helix Drill | ATTACK | RARE | - | cards_defect.cpp | - |
| HIBERNATE | Hibernate | SKILL | UNCOMMON | MULTIPLAYER_ONLY | cards_defect.cpp | - |
| HOLOGRAM | Hologram | SKILL | COMMON | EXHAUST | cards_defect.cpp | - |
| HOTFIX | Hotfix | SKILL | COMMON | EXHAUST | cards_defect.cpp | - |
| HYPERBEAM | Hyperbeam | ATTACK | RARE | - | cards_defect.cpp | - |
| ICE_LANCE | Ice Lance | ATTACK | RARE | - | cards_defect.cpp | - |
| IGNITION | Ignition | SKILL | UNCOMMON | MULTIPLAYER_ONLY,EXHAUST | cards_defect.cpp | - |
| IMITATION_LEARNING | Imitation Learning | SKILL | RARE | MULTIPLAYER_ONLY,EXHAUST | cards_defect.cpp | multiplayer_cards.cpp,test_smoke.py |
| ITERATION | Iteration | POWER | UNCOMMON | - | cards_defect.cpp | - |
| LEAP | Leap | SKILL | COMMON | - | cards_defect.cpp | - |
| LIGHTNING_ROD | Lightning Rod | SKILL | COMMON | - | cards_defect.cpp | - |
| LOOP | Loop | POWER | UNCOMMON | - | cards_defect.cpp | - |
| MACHINE_LEARNING | Machine Learning | POWER | RARE | - | cards_defect.cpp | - |
| METEOR_STRIKE | Meteor Strike | ATTACK | RARE | - | cards_defect.cpp | - |
| MODDED | Modded | SKILL | RARE | - | cards_defect.cpp | - |
| MOMENTUM_STRIKE | Momentum Strike | ATTACK | COMMON | - | cards_defect.cpp | - |
| MULTI_CAST | Multi Cast | SKILL | RARE | - | cards_defect.cpp | - |
| NULL_CARD | Null | ATTACK | UNCOMMON | - | cards_defect.cpp | - |
| ONE_FOR_ALL | One For All | POWER | RARE | MULTIPLAYER_ONLY | cards_defect.cpp | - |
| OVERCLOCK | Overclock | SKILL | UNCOMMON | - | cards_defect.cpp | - |
| QUADCAST | Quadcast | SKILL | ANCIENT | - | cards_defect.cpp,relic_card_rewards.cpp | - |
| RAINBOW | Rainbow | SKILL | RARE | EXHAUST | cards_defect.cpp | relic_coverage_round7.cpp |
| REBOOT | Reboot | SKILL | RARE | EXHAUST | cards_defect.cpp | - |
| REFRACT | Refract | ATTACK | UNCOMMON | - | cards_defect.cpp | - |
| ROCKET_PUNCH | Rocket Punch | ATTACK | UNCOMMON | - | cards_defect.cpp,defect.cpp | - |
| SCAVENGE | Scavenge | SKILL | UNCOMMON | - | cards_defect.cpp | - |
| SCRAPE | Scrape | ATTACK | UNCOMMON | - | cards_defect.cpp,defect.cpp | - |
| SHADOW_SHIELD | Shadow Shield | SKILL | UNCOMMON | - | cards_defect.cpp | - |
| SHATTER | Shatter | ATTACK | RARE | EXHAUST | cards_defect.cpp | map_event_audit_regression.cpp |
| SIGNAL_BOOST | Signal Boost | SKILL | RARE | EXHAUST | cards_defect.cpp | - |
| SKIM | Skim | SKILL | UNCOMMON | - | cards_defect.cpp | - |
| SMOKESTACK | Smokestack | POWER | UNCOMMON | - | cards_defect.cpp | - |
| SPINNER | Spinner | POWER | RARE | - | cards_defect.cpp | - |
| STORM | Storm | POWER | UNCOMMON | - | cards_defect.cpp | - |
| STRIKE_DEFECT | Strike Defect | ATTACK | BASIC | - | cards.cpp,cards_defect.cpp,run.cpp | - |
| SUBROUTINE | Subroutine | POWER | UNCOMMON | - | cards_defect.cpp | - |
| SUNDER | Sunder | ATTACK | UNCOMMON | - | cards_defect.cpp | - |
| SUPERCRITICAL | Supercritical | SKILL | RARE | EXHAUST | cards_defect.cpp | - |
| SWEEPING_BEAM | Sweeping Beam | ATTACK | COMMON | - | cards_defect.cpp | - |
| SYNCHRONIZE | Synchronize | SKILL | UNCOMMON | - | cards_defect.cpp | - |
| SYNTHESIS | Synthesis | ATTACK | UNCOMMON | - | cards_defect.cpp | - |
| TEMPEST | Tempest | SKILL | UNCOMMON | - | cards_defect.cpp | - |
| TESLA_COIL | Tesla Coil | ATTACK | UNCOMMON | - | cards_defect.cpp | - |
| THUNDER | Thunder | POWER | UNCOMMON | - | cards_defect.cpp | - |
| TRASH_TO_TREASURE | Trash To Treasure | POWER | RARE | - | cards_defect.cpp | - |
| TURBO | Turbo | SKILL | COMMON | - | cards_defect.cpp | - |
| UPROAR | Uproar | ATTACK | COMMON | - | cards_defect.cpp | - |
| VOLTAIC | Voltaic | SKILL | RARE | EXHAUST | cards_defect.cpp | - |
| WHITE_NOISE | White Noise | SKILL | UNCOMMON | EXHAUST | cards_defect.cpp | - |
| ZAP | Zap | SKILL | BASIC | - | cards_defect.cpp,run.cpp | - |

### REGENT cards (91)
| id | name | type | rarity | flags | effect files | tests |
|---|---|---|---|---|---|---|
| ALIGNMENT | Alignment | SKILL | UNCOMMON | - | cards_regent.cpp | - |
| ARSENAL | Arsenal | POWER | RARE | - | cards_regent.cpp | regent_mechanics.cpp |
| ASTRAL_PULSE | Astral Pulse | ATTACK | COMMON | - | cards_regent.cpp | regent_mechanics.cpp |
| BEAT_INTO_SHAPE | Beat Into Shape | ATTACK | RARE | - | cards_regent.cpp | - |
| BEGONE | Begone | SKILL | COMMON | - | cards_regent.cpp | - |
| BIG_BANG | Big Bang | SKILL | RARE | EXHAUST | cards_regent.cpp | - |
| BLACK_HOLE | Black Hole | POWER | UNCOMMON | - | cards_regent.cpp | - |
| BOMBARDMENT | Bombardment | ATTACK | RARE | EXHAUST | cards_regent.cpp | - |
| BULWARK | Bulwark | SKILL | UNCOMMON | - | cards_regent.cpp | - |
| BUNDLE_OF_JOY | Bundle Of Joy | SKILL | RARE | EXHAUST | cards_regent.cpp | - |
| CELESTIAL_MIGHT | Celestial Might | ATTACK | COMMON | - | cards_regent.cpp | - |
| CHARGE | Charge | SKILL | UNCOMMON | - | cards_regent.cpp | - |
| CHILD_OF_THE_STARS | Child Of The Stars | POWER | UNCOMMON | - | cards_regent.cpp | - |
| CLOAK_OF_STARS | Cloak Of Stars | SKILL | COMMON | - | cards_regent.cpp | - |
| COLLISION_COURSE | Collision Course | ATTACK | COMMON | - | cards_regent.cpp | - |
| COMET | Comet | ATTACK | RARE | - | cards_regent.cpp | - |
| CONQUEROR | Conqueror | SKILL | UNCOMMON | - | cards_regent.cpp | - |
| CONSTELLATION | Constellation | SKILL | UNCOMMON | MULTIPLAYER_ONLY | cards_regent.cpp | - |
| CONVERGENCE | Convergence | SKILL | UNCOMMON | - | cards_regent.cpp | - |
| COSMIC_INDIFFERENCE | Cosmic Indifference | SKILL | COMMON | - | cards_regent.cpp | - |
| CRASH_LANDING | Crash Landing | ATTACK | RARE | - | cards_regent.cpp | - |
| CRESCENT_SPEAR | Crescent Spear | ATTACK | COMMON | - | cards_regent.cpp | - |
| CRUSH_UNDER | Crush Under | ATTACK | COMMON | - | cards_regent.cpp | - |
| DECISIONS_DECISIONS | Decisions Decisions | SKILL | RARE | EXHAUST | cards_regent.cpp | - |
| DEFEND_REGENT | Defend Regent | SKILL | BASIC | - | cards_regent.cpp,run.cpp | - |
| DEVASTATE | Devastate | ATTACK | UNCOMMON | - | cards_regent.cpp | - |
| DYING_STAR | Dying Star | ATTACK | RARE | ETHEREAL | cards_regent.cpp | - |
| FALLING_STAR | Falling Star | ATTACK | BASIC | - | cards_regent.cpp,events.cpp,run.cpp | - |
| FOREGONE_CONCLUSION | Foregone Conclusion | SKILL | RARE | - | cards_regent.cpp | - |
| FURNACE | Furnace | POWER | UNCOMMON | - | cards_regent.cpp | - |
| GAMMA_BLAST | Gamma Blast | ATTACK | UNCOMMON | - | cards_regent.cpp | - |
| GATHER_LIGHT | Gather Light | SKILL | COMMON | - | cards_regent.cpp | - |
| GENESIS | Genesis | POWER | RARE | - | cards_regent.cpp | - |
| GLIMMER | Glimmer | SKILL | UNCOMMON | - | cards_regent.cpp | - |
| GLITTERSTREAM | Glitterstream | SKILL | COMMON | - | cards_regent.cpp | - |
| GLOW | Glow | SKILL | COMMON | - | cards_regent.cpp | - |
| GUARDS | Guards | SKILL | RARE | EXHAUST | cards_regent.cpp | - |
| GUIDING_STAR | Guiding Star | ATTACK | COMMON | - | cards_regent.cpp | - |
| HAMMER_TIME | Hammer Time | POWER | RARE | MULTIPLAYER_ONLY | cards_regent.cpp | - |
| HEAVENLY_DRILL | Heavenly Drill | ATTACK | RARE | - | cards_regent.cpp | - |
| HEGEMONY | Hegemony | ATTACK | UNCOMMON | - | cards_regent.cpp | - |
| HEIRLOOM_HAMMER | Heirloom Hammer | ATTACK | RARE | - | cards_regent.cpp | - |
| HIDDEN_CACHE | Hidden Cache | SKILL | COMMON | - | cards_regent.cpp | - |
| I_AM_INVINCIBLE | I Am Invincible | SKILL | RARE | - | cards_regent.cpp | - |
| KINGLY_KICK | Kingly Kick | ATTACK | UNCOMMON | - | cards_regent.cpp | - |
| KINGLY_PUNCH | Kingly Punch | ATTACK | UNCOMMON | - | cards_regent.cpp | - |
| KNOCKOUT_BLOW | Knockout Blow | ATTACK | UNCOMMON | - | cards_regent.cpp | - |
| KNOW_THY_PLACE | Know Thy Place | SKILL | COMMON | EXHAUST | cards_regent.cpp | - |
| LARGESSE | Largesse | SKILL | UNCOMMON | MULTIPLAYER_ONLY | cards_regent.cpp | - |
| LUNAR_BLAST | Lunar Blast | ATTACK | UNCOMMON | - | cards_regent.cpp | - |
| MAKE_IT_SO | Make It So | ATTACK | RARE | - | cards_regent.cpp | - |
| MANIFEST_AUTHORITY | Manifest Authority | SKILL | UNCOMMON | - | cards_regent.cpp | - |
| METEOR_SHOWER | Meteor Shower | ATTACK | ANCIENT | - | cards_regent.cpp,relic_card_rewards.cpp | - |
| MONARCHS_GAZE | Monarchs Gaze | POWER | RARE | - | cards_regent.cpp | - |
| MONOLOGUE | Monologue | SKILL | UNCOMMON | - | cards_regent.cpp | regent_mechanics.cpp |
| NEUTRON_AEGIS | Neutron Aegis | POWER | RARE | - | cards_regent.cpp | - |
| ORBIT | Orbit | POWER | UNCOMMON | - | cards_regent.cpp | regent_mechanics.cpp |
| PALE_BLUE_DOT | Pale Blue Dot | POWER | UNCOMMON | - | cards_regent.cpp | regent_mechanics.cpp |
| PARRY | Parry | POWER | UNCOMMON | - | cards_regent.cpp | relic_coverage_round7.cpp |
| PARTICLE_WALL | Particle Wall | SKILL | UNCOMMON | - | cards_regent.cpp | - |
| PATTER | Patter | SKILL | COMMON | - | cards_regent.cpp | - |
| PHOTON_CUT | Photon Cut | ATTACK | COMMON | - | cards_regent.cpp | - |
| PILLAR_OF_CREATION | Pillar Of Creation | POWER | UNCOMMON | - | cards_regent.cpp | - |
| PLOT | Plot | SKILL | UNCOMMON | MULTIPLAYER_ONLY | cards_regent.cpp | - |
| PROPHESIZE | Prophesize | SKILL | UNCOMMON | - | cards_regent.cpp | - |
| QUASAR | Quasar | SKILL | UNCOMMON | - | cards_regent.cpp | - |
| RADIATE | Radiate | ATTACK | UNCOMMON | - | cards_regent.cpp | monster_audit_regression.cpp |
| REFINE_BLADE | Refine Blade | SKILL | COMMON | - | cards_regent.cpp | - |
| REFLECT | Reflect | SKILL | UNCOMMON | - | cards_regent.cpp | map_event_audit_regression.cpp,regent_mechanics.cpp |
| RESONANCE | Resonance | SKILL | UNCOMMON | - | cards_regent.cpp | - |
| ROYAL_GAMBLE | Royal Gamble | SKILL | UNCOMMON | EXHAUST | cards_regent.cpp | - |
| ROYALTIES | Royalties | POWER | RARE | CANNOT_GENERATE | cards_regent.cpp | - |
| SEEKING_EDGE | Seeking Edge | POWER | RARE | - | cards_regent.cpp | - |
| SEVEN_STARS | Seven Stars | ATTACK | RARE | - | cards_regent.cpp | - |
| SHINING_STRIKE | Shining Strike | ATTACK | UNCOMMON | - | cards_regent.cpp | - |
| SOLAR_STRIKE | Solar Strike | ATTACK | COMMON | - | cards_regent.cpp | - |
| SPECTRUM_SHIFT | Spectrum Shift | POWER | UNCOMMON | - | cards_regent.cpp | regent_mechanics.cpp |
| SPOILS_OF_BATTLE | Spoils Of Battle | SKILL | COMMON | - | cards_regent.cpp | - |
| STARDUST | Stardust | ATTACK | UNCOMMON | - | cards_regent.cpp | regent_mechanics.cpp |
| STRIKE_REGENT | Strike Regent | ATTACK | BASIC | - | cards.cpp,cards_regent.cpp,run.cpp | - |
| SUMMON_FORTH | Summon Forth | SKILL | UNCOMMON | - | cards_regent.cpp | - |
| SUPERMASSIVE | Supermassive | ATTACK | UNCOMMON | - | cards_regent.cpp | regent_mechanics.cpp |
| SWORD_SAGE | Sword Sage | POWER | RARE | - | cards_regent.cpp | regent_mechanics.cpp |
| TERRAFORMING | Terraforming | SKILL | UNCOMMON | - | cards_regent.cpp | - |
| THE_SEALED_THRONE | The Sealed Throne | POWER | ANCIENT | - | cards_regent.cpp | - |
| THE_SMITH | The Smith | SKILL | RARE | - | cards_regent.cpp | - |
| TUTOR | Tutor | SKILL | RARE | MULTIPLAYER_ONLY | cards_regent.cpp | - |
| TYRANNY | Tyranny | POWER | RARE | - | cards_regent.cpp | regent_mechanics.cpp |
| VENERATE | Venerate | SKILL | BASIC | - | cards_regent.cpp,run.cpp | - |
| VOID_FORM | Void Form | POWER | RARE | ETHEREAL | cards_regent.cpp | regent_mechanics.cpp |
| WROUGHT_IN_WAR | Wrought In War | ATTACK | COMMON | - | cards_regent.cpp | - |

### NECROBINDER cards (91)
| id | name | type | rarity | flags | effect files | tests |
|---|---|---|---|---|---|---|
| AFTERLIFE | Afterlife | SKILL | COMMON | EXHAUST | cards_necrobinder.cpp | - |
| BANSHEES_CRY | Banshees Cry | ATTACK | RARE | - | cards_necrobinder.cpp,necrobinder.cpp | native_step2_necrobinder.cpp |
| BLIGHT_STRIKE | Blight Strike | ATTACK | COMMON | - | cards_necrobinder.cpp | - |
| BODYGUARD | Bodyguard | SKILL | BASIC | - | cards_necrobinder.cpp,run.cpp | - |
| BONE_SHARDS | Bone Shards | ATTACK | UNCOMMON | - | cards_necrobinder.cpp,necrobinder.cpp | - |
| BORROWED_TIME | Borrowed Time | SKILL | UNCOMMON | - | cards_necrobinder.cpp | - |
| BURY | Bury | ATTACK | UNCOMMON | - | cards_necrobinder.cpp | - |
| CACOPHONY | Cacophony | POWER | RARE | MULTIPLAYER_ONLY | cards_necrobinder.cpp | - |
| CALCIFY | Calcify | POWER | UNCOMMON | - | cards_necrobinder.cpp | - |
| CALL_OF_THE_VOID | Call Of The Void | POWER | RARE | - | cards_necrobinder.cpp | - |
| CAPTURE_SPIRIT | Capture Spirit | SKILL | UNCOMMON | - | cards_necrobinder.cpp | - |
| CLEANSE | Cleanse | SKILL | UNCOMMON | - | cards_necrobinder.cpp | - |
| COUNTDOWN | Countdown | POWER | UNCOMMON | - | cards_necrobinder.cpp | - |
| DANSE_MACABRE | Danse Macabre | POWER | UNCOMMON | - | cards_necrobinder.cpp | - |
| DEATH_MARCH | Death March | ATTACK | UNCOMMON | - | cards_necrobinder.cpp | - |
| DEATHBRINGER | Deathbringer | SKILL | UNCOMMON | - | cards_necrobinder.cpp | - |
| DEATHS_DOOR | Deaths Door | SKILL | UNCOMMON | - | cards_necrobinder.cpp | - |
| DEBILITATE | Debilitate | ATTACK | UNCOMMON | - | cards_necrobinder.cpp | native_step2_necrobinder.cpp |
| DEFEND_NECROBINDER | Defend Necrobinder | SKILL | BASIC | - | cards_necrobinder.cpp,run.cpp | - |
| DEFILE | Defile | ATTACK | COMMON | ETHEREAL | cards_necrobinder.cpp | native_step2_necrobinder.cpp |
| DEFY | Defy | SKILL | COMMON | ETHEREAL | cards_necrobinder.cpp | - |
| DELAY | Delay | SKILL | UNCOMMON | - | cards_necrobinder.cpp | - |
| DEMESNE | Demesne | POWER | RARE | ETHEREAL | cards_necrobinder.cpp | - |
| DEVOUR_LIFE | Devour Life | POWER | RARE | - | cards_necrobinder.cpp | - |
| DIRGE | Dirge | SKILL | UNCOMMON | EXHAUST | cards_necrobinder.cpp | - |
| DRAIN_POWER | Drain Power | ATTACK | COMMON | - | cards_necrobinder.cpp | - |
| DREDGE | Dredge | SKILL | UNCOMMON | EXHAUST | cards_necrobinder.cpp | - |
| EIDOLON | Eidolon | SKILL | RARE | CANNOT_GENERATE,EXHAUST | cards_necrobinder.cpp | - |
| END_OF_DAYS | End Of Days | SKILL | RARE | - | cards_necrobinder.cpp | - |
| ENFEEBLING_TOUCH | Enfeebling Touch | SKILL | UNCOMMON | ETHEREAL | cards_necrobinder.cpp | - |
| ERADICATE | Eradicate | ATTACK | RARE | RETAIN | cards_necrobinder.cpp | - |
| FEAR | Fear | ATTACK | COMMON | ETHEREAL | cards_necrobinder.cpp | - |
| FETCH | Fetch | ATTACK | UNCOMMON | - | cards_necrobinder.cpp,necrobinder.cpp | - |
| FLATTEN | Flatten | ATTACK | COMMON | - | cards_necrobinder.cpp,necrobinder.cpp | - |
| FORBIDDEN_GRIMOIRE | Forbidden Grimoire | POWER | ANCIENT | ETERNAL | cards_necrobinder.cpp | - |
| FRIENDSHIP | Friendship | POWER | UNCOMMON | - | cards_necrobinder.cpp | - |
| GLIMPSE_BEYOND | Glimpse Beyond | SKILL | RARE | MULTIPLAYER_ONLY,EXHAUST | cards_necrobinder.cpp | - |
| GRAVE_WARDEN | Grave Warden | SKILL | COMMON | - | cards_necrobinder.cpp | - |
| GRAVEBLAST | Graveblast | ATTACK | COMMON | EXHAUST | cards_necrobinder.cpp | - |
| HANG | Hang | ATTACK | RARE | - | cards_necrobinder.cpp,necrobinder.cpp | - |
| HAUNT | Haunt | POWER | UNCOMMON | - | cards_necrobinder.cpp | - |
| HIGH_FIVE | High Five | ATTACK | UNCOMMON | - | cards_necrobinder.cpp,necrobinder.cpp | - |
| INVOKE | Invoke | SKILL | COMMON | - | cards_necrobinder.cpp | - |
| LEGION_OF_BONE | Legion Of Bone | SKILL | UNCOMMON | MULTIPLAYER_ONLY | cards_necrobinder.cpp | - |
| LETHALITY | Lethality | POWER | UNCOMMON | ETHEREAL | cards_necrobinder.cpp | - |
| MELANCHOLY | Melancholy | SKILL | UNCOMMON | - | cards_necrobinder.cpp,necrobinder.cpp | - |
| MISERY | Misery | ATTACK | RARE | - | cards_necrobinder.cpp | - |
| NECRO_MASTERY | Necro Mastery | POWER | RARE | - | cards_necrobinder.cpp | - |
| NEGATIVE_PULSE | Negative Pulse | SKILL | COMMON | - | cards_necrobinder.cpp | - |
| NEUROSURGE | Neurosurge | POWER | RARE | - | cards_necrobinder.cpp | - |
| NO_ESCAPE | No Escape | SKILL | UNCOMMON | - | cards_necrobinder.cpp | - |
| OBLIVION | Oblivion | SKILL | RARE | - | cards_necrobinder.cpp | - |
| PAGESTORM | Pagestorm | POWER | UNCOMMON | - | cards_necrobinder.cpp | - |
| PARSE | Parse | SKILL | UNCOMMON | ETHEREAL | cards_necrobinder.cpp | - |
| POKE | Poke | ATTACK | COMMON | - | cards_necrobinder.cpp,necrobinder.cpp | native_step2_necrobinder.cpp |
| PROTECTOR | Protector | ATTACK | ANCIENT | - | cards_necrobinder.cpp,necrobinder.cpp,relic_card_rewards.cpp | - |
| PULL_AGGRO | Pull Aggro | SKILL | COMMON | - | cards_necrobinder.cpp | - |
| PULL_FROM_BELOW | Pull From Below | ATTACK | UNCOMMON | - | cards_necrobinder.cpp | native_step2_necrobinder.cpp |
| PUTREFY | Putrefy | SKILL | UNCOMMON | EXHAUST | cards_necrobinder.cpp | - |
| RATTLE | Rattle | ATTACK | UNCOMMON | - | cards_necrobinder.cpp,necrobinder.cpp | native_step2_necrobinder.cpp |
| REANIMATE | Reanimate | SKILL | RARE | EXHAUST | cards_necrobinder.cpp | - |
| REAP | Reap | ATTACK | COMMON | RETAIN | cards_necrobinder.cpp | - |
| REAPER_FORM | Reaper Form | POWER | RARE | - | cards_necrobinder.cpp | - |
| REAVE | Reave | ATTACK | COMMON | - | cards_necrobinder.cpp | - |
| RIGHT_HAND_HAND | Right Hand Hand | ATTACK | UNCOMMON | - | cards_necrobinder.cpp,necrobinder.cpp | - |
| SACRIFICE | Sacrifice | SKILL | RARE | RETAIN | cards_necrobinder.cpp | native_step2_necrobinder.cpp |
| SCOURGE | Scourge | SKILL | COMMON | - | cards_necrobinder.cpp | - |
| SCULPTING_STRIKE | Sculpting Strike | ATTACK | COMMON | - | cards_necrobinder.cpp | - |
| SEANCE | Seance | SKILL | RARE | ETHEREAL | cards_necrobinder.cpp | - |
| SENTRY_MODE | Sentry Mode | POWER | RARE | - | cards_necrobinder.cpp | - |
| SEVERANCE | Severance | ATTACK | UNCOMMON | - | cards_necrobinder.cpp | - |
| SHARED_FATE | Shared Fate | SKILL | RARE | EXHAUST | cards_necrobinder.cpp | - |
| SHROUD | Shroud | POWER | UNCOMMON | - | cards_necrobinder.cpp | - |
| SIC_EM | Sic Em | ATTACK | UNCOMMON | - | cards_necrobinder.cpp,necrobinder.cpp | native_step2_necrobinder.cpp |
| SLEIGHT_OF_FLESH | Sleight Of Flesh | POWER | UNCOMMON | - | cards_necrobinder.cpp | - |
| SNAP | Snap | ATTACK | COMMON | - | cards_necrobinder.cpp,necrobinder.cpp | - |
| SOUL_STORM | Soul Storm | ATTACK | RARE | - | cards_necrobinder.cpp | - |
| SOULBOUND | Soulbound | POWER | UNCOMMON | MULTIPLAYER_ONLY | cards_necrobinder.cpp | - |
| SOW | Sow | ATTACK | COMMON | RETAIN | cards_necrobinder.cpp | - |
| SPIRIT_OF_ASH | Spirit Of Ash | POWER | RARE | - | cards_necrobinder.cpp | - |
| SPUR | Spur | SKILL | UNCOMMON | RETAIN | cards_necrobinder.cpp | - |
| SQUEEZE | Squeeze | ATTACK | RARE | - | cards_necrobinder.cpp,necrobinder.cpp | - |
| STRIKE_NECROBINDER | Strike Necrobinder | ATTACK | BASIC | - | cards.cpp,cards_necrobinder.cpp,run.cpp | native_step2_necrobinder.cpp |
| THE_SCYTHE | The Scythe | ATTACK | RARE | EXHAUST | cards_necrobinder.cpp | - |
| TIMES_UP | Times Up | ATTACK | RARE | - | cards_necrobinder.cpp | - |
| TRANSFIGURE | Transfigure | SKILL | RARE | CANNOT_GENERATE,EXHAUST | cards_necrobinder.cpp | - |
| UNDEATH | Undeath | SKILL | RARE | - | cards_necrobinder.cpp | - |
| UNDERWORLD | Underworld | SKILL | UNCOMMON | MULTIPLAYER_ONLY,EXHAUST | cards_necrobinder.cpp | - |
| UNLEASH | Unleash | ATTACK | BASIC | - | cards_necrobinder.cpp,events.cpp,necrobinder.cpp,run.cpp | rules_regression.cpp |
| VEILPIERCER | Veilpiercer | ATTACK | UNCOMMON | - | cards_necrobinder.cpp | - |
| WISP | Wisp | SKILL | COMMON | EXHAUST | cards_necrobinder.cpp | map_event_audit_regression.cpp |

### COLORLESS cards (65)
| id | name | type | rarity | flags | effect files | tests |
|---|---|---|---|---|---|---|
| ALCHEMIZE | Alchemize | SKILL | RARE | CANNOT_GENERATE,EXHAUST | cards_colorless.cpp | rules_regression.cpp,test_rules.py |
| ANOINTED | Anointed | SKILL | RARE | EXHAUST | cards_colorless.cpp | native_card_round3_alignment.cpp,rules_regression.cpp |
| AUTOMATION | Automation | POWER | UNCOMMON | - | cards_colorless.cpp | rules_regression.cpp |
| BEACON_OF_HOPE | Beacon of Hope | POWER | RARE | MULTIPLAYER_ONLY | cards_colorless.cpp | multiplayer_cards.cpp,rules_regression.cpp |
| BEAT_DOWN | Beat Down | SKILL | RARE | - | cards_colorless.cpp | rules_regression.cpp |
| BELIEVE_IN_YOU | Believe in You | SKILL | UNCOMMON | MULTIPLAYER_ONLY | cards_colorless.cpp | - |
| BOLAS | Bolas | ATTACK | RARE | - | cards_colorless.cpp | - |
| CALAMITY_CARD | Calamity | POWER | RARE | - | cards_colorless.cpp | rules_regression.cpp |
| CATASTROPHE | Catastrophe | SKILL | UNCOMMON | - | cards_colorless.cpp | native_card_round3_alignment.cpp |
| COORDINATE_CARD | Coordinate | SKILL | UNCOMMON | MULTIPLAYER_ONLY | cards_colorless.cpp | - |
| DARK_SHACKLES | Dark Shackles | SKILL | UNCOMMON | EXHAUST | cards_colorless.cpp | rules_regression.cpp,test_rules.py |
| DISCOVERY | Discovery | SKILL | UNCOMMON | EXHAUST | cards_colorless.cpp | native_act_alignment.cpp,rules_regression.cpp,test_audit_regressions.py,test_content_filtering.py,test_rules.py |
| DRAMATIC_ENTRANCE | Dramatic Entrance | ATTACK | UNCOMMON | EXHAUST,INNATE | cards_colorless.cpp | native_card_alignment.cpp,relic_contract.cpp,rules_regression.cpp |
| ENTROPY | Entropy | POWER | RARE | - | cards_colorless.cpp | - |
| EQUILIBRIUM | Equilibrium | SKILL | UNCOMMON | - | cards_colorless.cpp | - |
| ETERNAL_ARMOR | Eternal Armor | POWER | RARE | - | cards_colorless.cpp | - |
| FASTEN | Fasten | POWER | UNCOMMON | - | cards_colorless.cpp | - |
| FINESSE | Finesse | SKILL | UNCOMMON | - | cards_colorless.cpp | - |
| FISTICUFFS | Fisticuffs | ATTACK | UNCOMMON | - | cards_colorless.cpp | rules_regression.cpp |
| FLASH_OF_STEEL | Flash of Steel | ATTACK | UNCOMMON | - | cards_colorless.cpp | rules_regression.cpp |
| GANG_UP | Gang Up | ATTACK | UNCOMMON | MULTIPLAYER_ONLY | cards_colorless.cpp | multiplayer_cards.cpp |
| GOLD_AXE | Gold Axe | ATTACK | RARE | - | battle.cpp,cards_colorless.cpp | native_card_alignment.cpp |
| HAND_OF_GREED | Hand of Greed | ATTACK | RARE | CANNOT_GENERATE | cards_colorless.cpp | rules_regression.cpp |
| HIDDEN_GEM | Hidden Gem | SKILL | RARE | CANNOT_GENERATE | cards_colorless.cpp | native_card_round3_alignment.cpp,rules_regression.cpp |
| HUDDLE_UP | Huddle Up | SKILL | UNCOMMON | MULTIPLAYER_ONLY,EXHAUST | cards_colorless.cpp | multiplayer_cards.cpp |
| IMPATIENCE | Impatience | SKILL | UNCOMMON | - | cards_colorless.cpp | - |
| INTERCEPT_CARD | Intercept | SKILL | UNCOMMON | MULTIPLAYER_ONLY | cards_colorless.cpp | multiplayer_cards.cpp |
| JACK_OF_ALL_TRADES | Jack of All Trades | SKILL | UNCOMMON | EXHAUST | cards_colorless.cpp | rules_regression.cpp |
| JACKPOT | Jackpot | ATTACK | RARE | - | cards_colorless.cpp | - |
| KNOCKDOWN | Knockdown | ATTACK | RARE | MULTIPLAYER_ONLY | cards_colorless.cpp | multiplayer_cards.cpp |
| LIFT | Lift | SKILL | UNCOMMON | MULTIPLAYER_ONLY | cards_colorless.cpp | map_event_audit_regression.cpp,multiplayer_cards.cpp,rules_regression.cpp |
| MASTER_OF_STRATEGY | Master of Strategy | SKILL | RARE | EXHAUST | cards_colorless.cpp | - |
| MAYHEM_CARD | Mayhem | POWER | RARE | - | cards_colorless.cpp | rules_regression.cpp |
| MIMIC | Mimic | SKILL | RARE | MULTIPLAYER_ONLY,EXHAUST | cards_colorless.cpp | multiplayer_cards.cpp |
| MIND_BLAST | Mind Blast | ATTACK | UNCOMMON | INNATE | battle.cpp,cards_colorless.cpp | - |
| NOSTALGIA_CARD | Nostalgia | POWER | RARE | - | cards_colorless.cpp | rules_regression.cpp |
| OMNISLICE | Omnislice | ATTACK | UNCOMMON | - | cards_colorless.cpp | rules_regression.cpp |
| PANACHE_CARD | Panache | POWER | UNCOMMON | - | cards_colorless.cpp | rules_regression.cpp |
| PANIC_BUTTON | Panic Button | SKILL | UNCOMMON | EXHAUST | cards_colorless.cpp | - |
| PREP_TIME | Prep Time | POWER | UNCOMMON | - | cards_colorless.cpp | - |
| PRODUCTION | Production | SKILL | UNCOMMON | EXHAUST | cards_colorless.cpp | test_armg_rules_integration.py |
| PROLONG | Prolong | SKILL | UNCOMMON | EXHAUST | cards_colorless.cpp | rules_regression.cpp |
| PROWESS | Prowess | POWER | UNCOMMON | - | cards_colorless.cpp | - |
| PURITY | Purity | SKILL | UNCOMMON | EXHAUST,RETAIN | cards_colorless.cpp | - |
| RALLY | Rally | SKILL | RARE | MULTIPLAYER_ONLY | cards_colorless.cpp | multiplayer_cards.cpp |
| REND | Rend | ATTACK | RARE | - | cards_colorless.cpp | native_card_round3_alignment.cpp |
| RESTLESSNESS | Restlessness | SKILL | UNCOMMON | RETAIN | cards_colorless.cpp | - |
| ROLLING_BOULDER | Rolling Boulder | POWER | RARE | - | cards_colorless.cpp | - |
| SALVO | Salvo | ATTACK | UNCOMMON | - | cards_colorless.cpp | - |
| SCRAWL | Scrawl | SKILL | RARE | EXHAUST | cards_colorless.cpp | rules_regression.cpp |
| SECRET_TECHNIQUE | Secret Technique | SKILL | RARE | EXHAUST | cards_colorless.cpp | rules_regression.cpp |
| SECRET_WEAPON | Secret Weapon | SKILL | RARE | EXHAUST | cards_colorless.cpp | rules_regression.cpp |
| SEEKER_STRIKE | Seeker Strike | ATTACK | UNCOMMON | - | battle.cpp,cards_colorless.cpp | rules_regression.cpp |
| SHOCKWAVE | Shockwave | SKILL | UNCOMMON | EXHAUST | cards_colorless.cpp | - |
| SPLASH | Splash | SKILL | RARE | - | cards_colorless.cpp | native_card_round3_alignment.cpp,test_step2_rules_20261104.py |
| STRATAGEM | Stratagem | POWER | UNCOMMON | - | cards_colorless.cpp | monster_audit_regression.cpp,rules_regression.cpp |
| TAG_TEAM | Tag Team | ATTACK | UNCOMMON | MULTIPLAYER_ONLY | cards_colorless.cpp | multiplayer_cards.cpp |
| THE_BOMB_CARD | The Bomb | SKILL | UNCOMMON | - | cards_colorless.cpp | rules_regression.cpp |
| THE_GAMBIT | The Gambit | SKILL | RARE | - | cards_colorless.cpp | rules_regression.cpp |
| THINKING_AHEAD | Thinking Ahead | SKILL | UNCOMMON | EXHAUST | cards_colorless.cpp | - |
| THRUMMING_HATCHET | Thrumming Hatchet | ATTACK | UNCOMMON | - | battle_turns.cpp,cards_colorless.cpp | rules_regression.cpp |
| ULTIMATE_DEFEND | Ultimate Defend | SKILL | UNCOMMON | - | events.cpp | rules_regression.cpp |
| ULTIMATE_STRIKE | Ultimate Strike | ATTACK | UNCOMMON | - | events.cpp | rules_regression.cpp |
| VOLLEY | Volley | ATTACK | UNCOMMON | - | cards_colorless.cpp | native_card_round3_alignment.cpp |
| THE_BALL | The Ball | ATTACK | UNCOMMON | MULTIPLAYER_ONLY | cards_colorless.cpp | multiplayer_cards.cpp |

### EVENT cards (28)
| id | name | type | rarity | flags | effect files | tests |
|---|---|---|---|---|---|---|
| APOTHEOSIS | Apotheosis | SKILL | ANCIENT | EXHAUST,INNATE | cards_colorless.cpp,relics.cpp | rules_regression.cpp |
| APPARITION | Apparition | SKILL | ANCIENT | ETHEREAL,EXHAUST | cards_colorless.cpp,relics.cpp | native_relic_round3_alignment.cpp,relic_contract.cpp,rules_regression.cpp |
| BRIGHTEST_FLAME | Brightest Flame | SKILL | ANCIENT | - | cards_colorless.cpp,relics.cpp | native_card_round3_alignment.cpp,rules_regression.cpp,test_content.py |
| BYRD_SWOOP | Byrd Swoop | ATTACK | EVENT | - | cards_colorless.cpp,relic_persistent.cpp | native_step2_persistent.cpp,rules_regression.cpp |
| CALTROPS | Caltrops | POWER | EVENT | - | cards_colorless.cpp,events.cpp | rules_regression.cpp |
| CLASH | Clash | ATTACK | EVENT | - | battle.cpp,events.cpp | rules_regression.cpp |
| DISTRACTION | Distraction | SKILL | EVENT | EXHAUST | cards_colorless.cpp,events.cpp | rules_regression.cpp |
| DUAL_WIELD | Dual Wield | SKILL | EVENT | - | cards_colorless.cpp,events.cpp | rules_regression.cpp |
| ENLIGHTENMENT | Enlightenment | SKILL | EVENT | EXHAUST | cards_colorless.cpp,events.cpp | native_card_round3_alignment.cpp,rules_regression.cpp |
| ENTRENCH | Entrench | SKILL | EVENT | - | cards_ironclad.cpp,events.cpp | native_underdocks_events.cpp,rules_regression.cpp |
| EXTERMINATE | Exterminate | ATTACK | EVENT | - | cards_colorless.cpp,events.cpp | rules_regression.cpp |
| FEEDING_FRENZY_CARD | Feeding Frenzy | SKILL | EVENT | - | cards_colorless.cpp,events.cpp | rules_regression.cpp |
| HELLO_WORLD_CARD | Hello World | POWER | EVENT | - | cards_colorless.cpp,events.cpp | rules_regression.cpp |
| MAD_SCIENCE | Mad Science | ATTACK | EVENT | - | cards.cpp,cards_colorless.cpp,events.cpp | audit_rl_regressions.cpp,native_card_round3_alignment.cpp,rules_regression.cpp,test_audit_rl_fixes.py |
| MAUL | Maul | ATTACK | ANCIENT | - | cards_colorless.cpp | enchantment_contract.cpp,native_card_round3_alignment.cpp,rules_regression.cpp |
| METAMORPHOSIS | Metamorphosis | SKILL | EVENT | EXHAUST | cards_colorless.cpp,events.cpp | rules_regression.cpp |
| NEOWS_FURY | Neow's Fury | ATTACK | ANCIENT | CANNOT_GENERATE,EXHAUST | cards_colorless.cpp,relics.cpp | native_relic_round3_alignment.cpp,rules_regression.cpp |
| OUTMANEUVER | Outmaneuver | SKILL | EVENT | - | cards_colorless.cpp,events.cpp | rules_regression.cpp |
| PECK | Peck | ATTACK | EVENT | - | cards_colorless.cpp,events.cpp | rules_regression.cpp |
| REBOUND | Rebound | ATTACK | EVENT | - | battle.cpp,cards_colorless.cpp,events.cpp | rules_regression.cpp |
| RELAX | Relax | SKILL | ANCIENT | EXHAUST | cards_colorless.cpp,relics.cpp | test_content.py |
| RIP_AND_TEAR | Rip and Tear | ATTACK | EVENT | - | cards_colorless.cpp,events.cpp | native_card_round3_alignment.cpp,native_round3_shared_alignment.cpp,rules_regression.cpp |
| SQUASH | Squash | ATTACK | EVENT | - | cards_colorless.cpp,events.cpp | rules_regression.cpp |
| STACK | Stack | SKILL | EVENT | - | cards_colorless.cpp,events.cpp | audit_rl_regressions.cpp,rules_regression.cpp |
| TORIC_TOUGHNESS | Toric Toughness | SKILL | EVENT | - | cards_colorless.cpp,events.cpp | rules_regression.cpp |
| WISH | Wish | SKILL | ANCIENT | EXHAUST | cards_colorless.cpp,relics.cpp | native_relic_round3_alignment.cpp,relic_contract.cpp,rules_regression.cpp |
| WHISTLE | Whistle | ATTACK | ANCIENT | EXHAUST | cards_colorless.cpp,relics.cpp | relic_contract.cpp,rules_regression.cpp |
| ABUNDANCE | Abundance | SKILL | ANCIENT | CANNOT_GENERATE,EXHAUST | cards_colorless.cpp,run.cpp | quest_cards.cpp |

### CURSE cards (18)
| id | name | type | rarity | flags | effect files | tests |
|---|---|---|---|---|---|---|
| ASCENDERS_BANE | Ascender's Bane | CURSE | CURSE | UNPLAYABLE,CANNOT_GENERATE,ETHEREAL,ETERNAL | events.cpp,run.cpp | enchantment_contract.cpp,snapshot_validation.cpp |
| BAD_LUCK | Bad Luck | CURSE | CURSE | UNPLAYABLE,ETERNAL | battle_turns.cpp,events.cpp | test_content.py |
| CLUMSY | Clumsy | CURSE | CURSE | UNPLAYABLE,ETHEREAL | events.cpp,relics.cpp | native_relic_round3_alignment.cpp,rules_regression.cpp,test_content.py |
| CURSE_OF_THE_BELL | Curse of the Bell | CURSE | CURSE | UNPLAYABLE,ETERNAL | events.cpp,relics.cpp | relic_contract.cpp |
| DEBT | Debt | CURSE | CURSE | UNPLAYABLE | battle_turns.cpp,events.cpp,relics.cpp | rules_regression.cpp,test_content.py |
| DECAY | Decay | CURSE | CURSE | UNPLAYABLE | battle_turns.cpp,events.cpp,relics.cpp | map_event_audit_regression.cpp,rules_regression.cpp,test_content.py |
| DOUBT | Doubt | CURSE | CURSE | UNPLAYABLE | battle_turns.cpp,events.cpp,relics.cpp | rules_regression.cpp,test_content.py |
| ENTHRALLED | Enthralled | CURSE | CURSE | ETERNAL | battle.cpp,events.cpp,relics.cpp | relic_contract.cpp,rules_regression.cpp |
| FOLLY | Folly | CURSE | CURSE | UNPLAYABLE,ETHEREAL,INNATE,ETERNAL | events.cpp,relics.cpp,run.cpp | native_relic_round2_alignment.cpp,native_run_alignment.cpp,relic_contract.cpp |
| GREED | Greed | CURSE | CURSE | UNPLAYABLE,ETERNAL | events.cpp,relics.cpp | native_event_round3_alignment.cpp,native_underdocks_events.cpp,rules_regression.cpp,test_content.py |
| GUILTY | Guilty | CURSE | CURSE | UNPLAYABLE | events.cpp,relics.cpp,run.cpp | enchantment_contract.cpp,map_event_audit_regression.cpp,native_relic_round3_alignment.cpp,rules_regression.cpp,snapshot_validation.cpp,test_content.py |
| INJURY | Injury | CURSE | CURSE | UNPLAYABLE | events.cpp,relics.cpp | rules_regression.cpp |
| NORMALITY | Normality | CURSE | CURSE | UNPLAYABLE | battle.cpp,battle_flow.cpp,events.cpp,relics.cpp | native_relic_round3_alignment.cpp,rules_regression.cpp,test_content.py |
| POOR_SLEEP | Poor Sleep | CURSE | CURSE | UNPLAYABLE,RETAIN | events.cpp | map_event_audit_regression.cpp,test_content.py |
| REGRET | Regret | CURSE | CURSE | UNPLAYABLE | battle_turns.cpp,events.cpp,relics.cpp | native_relic_round3_alignment.cpp,rules_regression.cpp,test_content.py |
| SHAME | Shame | CURSE | CURSE | UNPLAYABLE | battle_turns.cpp,events.cpp,relics.cpp | rules_regression.cpp,test_content.py |
| SPORE_MIND | Spore Mind | CURSE | CURSE | EXHAUST | events.cpp | rules_regression.cpp |
| WRITHE | Writhe | CURSE | CURSE | UNPLAYABLE,INNATE | relics.cpp | rules_regression.cpp |

### STATUS cards (12)
| id | name | type | rarity | flags | effect files | tests |
|---|---|---|---|---|---|---|
| BECKON | Beckon | STATUS | STATUS | - | battle_turns.cpp,cards_status.cpp | rules_regression.cpp |
| BURN | Burn | STATUS | STATUS | UNPLAYABLE | battle_turns.cpp,cards_defect.cpp,cards_status.cpp | monster_audit_regression.cpp,native_relic_round2_alignment.cpp,native_step1_relic_replace.cpp,relic_coverage_round7.cpp,rules_regression.cpp,test_armg_need.py,test_content.py |
| DAZED | Dazed | STATUS | STATUS | UNPLAYABLE,ETHEREAL | battle_damage.cpp,cards_defect.cpp,cards_status.cpp,relics.cpp,run.cpp | observation_contract.cpp,rules_regression.cpp,snapshot_validation.cpp,test_audit_regressions.py |
| DEBRIS | Debris | STATUS | STATUS | EXHAUST | cards_regent.cpp,cards_status.cpp | - |
| FRANTIC_ESCAPE | Frantic Escape | STATUS | STATUS | CANNOT_GENERATE | cards_status.cpp | monster_audit_regression.cpp |
| INFECTION | Infection | STATUS | STATUS | UNPLAYABLE | battle_turns.cpp,cards_status.cpp | - |
| SLIMED | Slimed | STATUS | STATUS | EXHAUST | cards_defect.cpp,cards_status.cpp | native_card_round3_alignment.cpp,rules_regression.cpp,test_audit_regressions.py |
| SOOT | Soot | STATUS | STATUS | UNPLAYABLE,CANNOT_GENERATE | cards_status.cpp,relics.cpp | - |
| TOXIC | Toxic | STATUS | STATUS | EXHAUST | battle_turns.cpp,cards_status.cpp | rules_regression.cpp,test_audit_regressions.py |
| VOID | Void | STATUS | STATUS | UNPLAYABLE,ETHEREAL | battle.cpp,cards_defect.cpp,cards_status.cpp | regent_mechanics.cpp |
| WOUND | Wound | STATUS | STATUS | UNPLAYABLE | battle.cpp,cards_defect.cpp,cards_status.cpp | native_card_round3_alignment.cpp,rules_regression.cpp,test_audit_regressions.py |
| WITHER | Wither | STATUS | STATUS | UNPLAYABLE | battle.cpp,battle_turns.cpp | test_step2_rules_20261104.py |

### TOKEN cards (14)
| id | name | type | rarity | flags | effect files | tests |
|---|---|---|---|---|---|---|
| DISINTEGRATION | Disintegration | STATUS | STATUS | CANNOT_GENERATE | battle.cpp,battle_turns.cpp | knowledge_curse.cpp |
| FUEL | Fuel | SKILL | TOKEN | EXHAUST | cards_colorless.cpp,cards_defect.cpp | - |
| GIANT_ROCK | Giant Rock | ATTACK | TOKEN | - | cards_ironclad.cpp | rules_regression.cpp |
| LUMINESCE | Luminesce | SKILL | TOKEN | EXHAUST,RETAIN | cards_status.cpp,relics.cpp | relic_coverage_round7.cpp,rules_regression.cpp |
| MIND_ROT | Mind Rot | STATUS | STATUS | CANNOT_GENERATE | battle.cpp,battle_turns.cpp | knowledge_curse.cpp |
| MINION_DIVE_BOMB | Minion Dive Bomb | ATTACK | TOKEN | EXHAUST | cards.cpp,cards_regent.cpp | - |
| MINION_SACRIFICE | Minion Sacrifice | SKILL | TOKEN | EXHAUST | cards.cpp,cards_regent.cpp | - |
| MINION_STRIKE | Minion Strike | ATTACK | TOKEN | EXHAUST | cards.cpp,cards_regent.cpp | relic_coverage_round7.cpp |
| SHIV | Shiv | ATTACK | TOKEN | EXHAUST | cards_silent.cpp,relics.cpp,silent.cpp | character_potions.cpp,native_step2_silent.cpp,relic_coverage_round7.cpp |
| SLOTH_STATUS | SLOTH_STATUS | STATUS | STATUS | CANNOT_GENERATE | battle.cpp,battle_turns.cpp | knowledge_curse.cpp,native_card_round3_alignment.cpp |
| SOUL | Soul | SKILL | TOKEN | EXHAUST | cards_colorless.cpp,cards_necrobinder.cpp,necrobinder.cpp | character_potions.cpp,native_step2_necrobinder.cpp,rules_regression.cpp |
| SOVEREIGN_BLADE | Sovereign Blade | ATTACK | TOKEN | RETAIN | cards_regent.cpp,regent.cpp | character_potions.cpp,regent_mechanics.cpp,relic_coverage_round7.cpp |
| SWEEPING_GAZE | Sweeping Gaze | ATTACK | TOKEN | ETHEREAL,EXHAUST | cards_necrobinder.cpp,necrobinder.cpp | - |
| WASTE_AWAY | Waste Away | STATUS | STATUS | CANNOT_GENERATE | battle_turns.cpp | knowledge_curse.cpp |

### QUEST cards (4)
| id | name | type | rarity | flags | effect files | tests |
|---|---|---|---|---|---|---|
| BYRDONIS_EGG | Byrdonis Egg | QUEST | QUEST | UNPLAYABLE | events.cpp,relic_persistent.cpp | map_event_audit_regression.cpp,native_step2_persistent.cpp,test_step2_rules_20261104.py |
| DOWSING | Dowsing | QUEST | QUEST | UNPLAYABLE | relics.cpp,run.cpp | quest_cards.cpp,rules_regression.cpp |
| LANTERN_KEY | Lantern Key | QUEST | QUEST | UNPLAYABLE | events.cpp,run.cpp | quest_cards.cpp,rules_regression.cpp |
| SPOILS_MAP | Spoils Map | QUEST | QUEST | UNPLAYABLE | events.cpp,run.cpp | quest_cards.cpp,rules_regression.cpp,test_smoke.py |

### potions (66)
| id | name | rarity | usage | target | effect files | tests |
|---|---|---|---|---|---|---|
| INVALID |  | COMMON | COMBAT_ONLY | SELF | potions.cpp,run.cpp | snapshot_validation.cpp |
| ATTACK_POTION | Attack Potion | COMMON | COMBAT_ONLY | SELF | potions.cpp | rules_regression.cpp |
| BLOCK_POTION | Block Potion | COMMON | COMBAT_ONLY | ANY_PLAYER | potions.cpp | rules_regression.cpp |
| BLOOD_POTION | Blood Potion | COMMON | ANY_TIME | ANY_PLAYER | potions.cpp,run.cpp | audit_rl_regressions.cpp,character_potions.cpp,enchantment_contract.cpp,native_round3_shared_alignment.cpp,observation_contract.cpp |
| COLORLESS_POTION | Colorless Potion | COMMON | COMBAT_ONLY | SELF | potions.cpp | rules_regression.cpp |
| DEXTERITY_POTION | Dexterity Potion | COMMON | COMBAT_ONLY | ANY_PLAYER | potions.cpp | potion_coverage_round7.cpp |
| ENERGY_POTION | Energy Potion | COMMON | COMBAT_ONLY | ANY_PLAYER | potions.cpp | character_potions.cpp |
| EXPLOSIVE_AMPOULE | Explosive Ampoule | COMMON | COMBAT_ONLY | ALL_ENEMIES | potions.cpp | rules_regression.cpp |
| FIRE_POTION | Fire Potion | COMMON | COMBAT_ONLY | ANY_ENEMY | potions.cpp | audit_rl_regressions.cpp,map_event_audit_regression.cpp,native_event_round3_alignment.cpp,native_underdocks_events.cpp,observation_contract.cpp,relic_contract.cpp,rules_regression.cpp |
| FLEX_POTION | Flex Potion | COMMON | COMBAT_ONLY | ANY_PLAYER | potions.cpp | rules_regression.cpp |
| FOCUS_POTION | Focus Potion | COMMON | COMBAT_ONLY | SELF | potions.cpp | character_potions.cpp |
| POISON_POTION | Poison Potion | COMMON | COMBAT_ONLY | ANY_ENEMY | potions.cpp | character_potions.cpp |
| POTION_OF_DOOM | Potion Of Doom | COMMON | COMBAT_ONLY | ANY_ENEMY | potions.cpp | character_potions.cpp |
| POWER_POTION | Power Potion | COMMON | COMBAT_ONLY | SELF | potions.cpp | potion_coverage_round7.cpp |
| SKILL_POTION | Skill Potion | COMMON | COMBAT_ONLY | SELF | potions.cpp | potion_coverage_round7.cpp |
| SPEED_POTION | Speed Potion | COMMON | COMBAT_ONLY | ANY_PLAYER | potions.cpp | rules_regression.cpp |
| STAR_POTION | Star Potion | COMMON | COMBAT_ONLY | SELF | potions.cpp | character_potions.cpp |
| STRENGTH_POTION | Strength Potion | COMMON | COMBAT_ONLY | ANY_PLAYER | potions.cpp | rules_regression.cpp |
| SWIFT_POTION | Swift Potion | COMMON | COMBAT_ONLY | ANY_PLAYER | potions.cpp | potion_coverage_round7.cpp |
| VULNERABLE_POTION | Vulnerable Potion | COMMON | COMBAT_ONLY | ANY_ENEMY | potions.cpp | native_event_round3_alignment.cpp |
| WEAK_POTION | Weak Potion | COMMON | COMBAT_ONLY | ANY_ENEMY | potions.cpp | potion_coverage_round7.cpp |
| ASHWATER | Ashwater | UNCOMMON | COMBAT_ONLY | SELF | potions.cpp | character_potions.cpp |
| BLESSING_OF_THE_FORGE | Blessing Of The Forge | UNCOMMON | COMBAT_ONLY | SELF | potions.cpp | potion_coverage_round7.cpp |
| BONE_BREW | Bone Brew | UNCOMMON | COMBAT_ONLY | SELF | potions.cpp | character_potions.cpp |
| CLARITY | Clarity | UNCOMMON | COMBAT_ONLY | ANY_PLAYER | potions.cpp | rules_regression.cpp |
| CUNNING_POTION | Cunning Potion | UNCOMMON | COMBAT_ONLY | SELF | potions.cpp | character_potions.cpp |
| CURE_ALL | Cure All | UNCOMMON | COMBAT_ONLY | ANY_PLAYER | potions.cpp | potion_coverage_round7.cpp |
| DUPLICATOR | Duplicator | UNCOMMON | COMBAT_ONLY | SELF | potions.cpp | potion_coverage_round7.cpp |
| FORTIFIER | Fortifier | UNCOMMON | COMBAT_ONLY | ANY_PLAYER | potions.cpp | rules_regression.cpp |
| FYSH_OIL | Fysh Oil | UNCOMMON | COMBAT_ONLY | ANY_PLAYER | potions.cpp | potion_coverage_round7.cpp |
| GAMBLERS_BREW | Gamblers Brew | UNCOMMON | COMBAT_ONLY | SELF | potions.cpp | potion_coverage_round7.cpp |
| HEART_OF_IRON | Heart Of Iron | UNCOMMON | COMBAT_ONLY | ANY_PLAYER | potions.cpp | rules_regression.cpp |
| KINGS_COURAGE | Kings Courage | UNCOMMON | COMBAT_ONLY | ANY_PLAYER | potions.cpp | character_potions.cpp |
| LIQUID_BRONZE | Liquid Bronze | UNCOMMON | COMBAT_ONLY | ANY_PLAYER | potions.cpp | potion_coverage_round7.cpp |
| POTION_OF_BINDING | Potion Of Binding | UNCOMMON | COMBAT_ONLY | ALL_ENEMIES | potions.cpp | potion_coverage_round7.cpp |
| POTION_OF_CAPACITY | Potion Of Capacity | UNCOMMON | COMBAT_ONLY | SELF | potions.cpp | character_potions.cpp |
| POWDERED_DEMISE | Powdered Demise | UNCOMMON | COMBAT_ONLY | ANY_ENEMY | potions.cpp | rules_regression.cpp |
| RADIANT_TINCTURE | Radiant Tincture | UNCOMMON | COMBAT_ONLY | ANY_PLAYER | potions.cpp | rules_regression.cpp |
| REGEN_POTION | Regen Potion | UNCOMMON | COMBAT_ONLY | ANY_PLAYER | potions.cpp | potion_coverage_round7.cpp |
| STABLE_SERUM | Stable Serum | UNCOMMON | COMBAT_ONLY | ANY_PLAYER | potions.cpp | potion_coverage_round7.cpp |
| TOUCH_OF_INSANITY | Touch Of Insanity | UNCOMMON | COMBAT_ONLY | SELF | potions.cpp | potion_coverage_round7.cpp |
| BEETLE_JUICE | Beetle Juice | RARE | COMBAT_ONLY | ANY_ENEMY | potions.cpp | rules_regression.cpp |
| BOTTLED_POTENTIAL | Bottled Potential | RARE | COMBAT_ONLY | ANY_PLAYER | potions.cpp | rules_regression.cpp |
| COSMIC_CONCOCTION | Cosmic Concoction | RARE | COMBAT_ONLY | SELF | potions.cpp | character_potions.cpp |
| DISTILLED_CHAOS | Distilled Chaos | RARE | COMBAT_ONLY | SELF | potions.cpp | rules_regression.cpp |
| DROPLET_OF_PRECOGNITION | Droplet Of Precognition | RARE | COMBAT_ONLY | SELF | potions.cpp | rules_regression.cpp |
| ENTROPIC_BREW | Entropic Brew | RARE | ANY_TIME | SELF | potions.cpp,run.cpp | rules_regression.cpp |
| ESSENCE_OF_DARKNESS | Essence Of Darkness | RARE | COMBAT_ONLY | SELF | potions.cpp | character_potions.cpp |
| FAIRY_IN_ABOTTLE | Fairy In ABottle | RARE | AUTOMATIC | SELF | potions.cpp,relics.cpp | native_event_round3_alignment.cpp,native_run_alignment.cpp,native_underdocks_events.cpp |
| FRUIT_JUICE | Fruit Juice | RARE | ANY_TIME | ANY_PLAYER | potions.cpp,run.cpp | potion_coverage_round7.cpp |
| GHOST_IN_AJAR | Ghost In AJar | RARE | COMBAT_ONLY | ANY_PLAYER | potions.cpp | character_potions.cpp |
| GIGANTIFICATION_POTION | Gigantification Potion | RARE | COMBAT_ONLY | ANY_PLAYER | potions.cpp | rules_regression.cpp |
| LIQUID_MEMORIES | Liquid Memories | RARE | COMBAT_ONLY | SELF | potions.cpp | rules_regression.cpp |
| LUCKY_TONIC | Lucky Tonic | RARE | COMBAT_ONLY | ANY_PLAYER | potions.cpp | potion_coverage_round7.cpp |
| MAZALETHS_GIFT | Mazaleths Gift | RARE | COMBAT_ONLY | ANY_PLAYER | potions.cpp | potion_coverage_round7.cpp |
| OROBIC_ACID | Orobic Acid | RARE | COMBAT_ONLY | SELF | potions.cpp | rules_regression.cpp |
| POT_OF_GHOULS | Pot Of Ghouls | RARE | COMBAT_ONLY | SELF | potions.cpp | character_potions.cpp |
| SHACKLING_POTION | Shackling Potion | RARE | COMBAT_ONLY | ALL_ENEMIES | potions.cpp | rules_regression.cpp |
| SHIP_IN_ABOTTLE | Ship In ABottle | RARE | COMBAT_ONLY | ANY_PLAYER | potions.cpp | potion_coverage_round7.cpp |
| SNECKO_OIL | Snecko Oil | RARE | COMBAT_ONLY | ANY_PLAYER | potions.cpp | rules_regression.cpp |
| SOLDIERS_STEW | Soldiers Stew | RARE | COMBAT_ONLY | ANY_PLAYER | potions.cpp | character_potions.cpp |
| FOUL_POTION | Foul Potion | SPECIAL | ANY_TIME | SELF | events.cpp,potions.cpp,run.cpp | map_event_audit_regression.cpp,rules_regression.cpp |
| GLOWWATER_POTION | Glowwater Potion | SPECIAL | COMBAT_ONLY | SELF | events.cpp,potions.cpp | native_underdocks_events.cpp |
| POTION_SHAPED_ROCK | Potion Shaped Rock | SPECIAL | COMBAT_ONLY | ANY_ENEMY | potions.cpp,relics.cpp | potion_coverage_round7.cpp,relic_coverage_round7.cpp |
| DEPRECATED_POTION | Deprecated Potion | SPECIAL | COMBAT_ONLY | ANY_ENEMY | - | rules_regression.cpp |
| AMBERGRIS | Ambergris | SPECIAL | ANY_TIME | ANY_PLAYER | potions.cpp,relics.cpp,run.cpp | rules_regression.cpp |

### relics (300)
| id | name | rarity | pool | effect files | tests |
|---|---|---|---|---|---|
| INVALID |  | SPECIAL | OTHER | events.cpp,relics.cpp,run.cpp | native_step2_relic_lifecycle.cpp,relic_contract.cpp,relic_raw_rarity.cpp,snapshot_validation.cpp |
| BURNING_BLOOD | BurningBlood | SPECIAL | IRONCLAD | relics.cpp,run.cpp | native_relic_round2_alignment.cpp,native_step1_relic_replace.cpp,native_step2_card_rewards.cpp,native_step2_relic_lifecycle.cpp,relic_raw_rarity.cpp,rules_regression.cpp |
| BLACK_BLOOD | BlackBlood | SPECIAL | EVENT | relics.cpp | native_relic_round2_alignment.cpp,native_step1_relic_replace.cpp |
| RING_OF_THE_SNAKE | RingOfTheSnake | SPECIAL | SILENT | relics.cpp,run.cpp | relic_coverage_round7.cpp |
| RING_OF_THE_DRAKE | RingOfTheDrake | SPECIAL | EVENT | relics.cpp | relic_coverage_round7.cpp |
| CRACKED_CORE | CrackedCore | SPECIAL | DEFECT | relics.cpp,run.cpp | relic_coverage_round7.cpp |
| INFUSED_CORE | InfusedCore | SPECIAL | EVENT | defect.cpp,relics.cpp | relic_coverage_round7.cpp |
| BOUND_PHYLACTERY | BoundPhylactery | SPECIAL | NECROBINDER | necrobinder.cpp,relics.cpp,run.cpp | native_step2_necrobinder.cpp |
| PHYLACTERY_UNBOUND | PhylacteryUnbound | SPECIAL | EVENT | necrobinder.cpp,relics.cpp | relic_coverage_round7.cpp |
| DIVINE_RIGHT | DivineRight | SPECIAL | REGENT | relics.cpp,run.cpp | relic_coverage_round7.cpp |
| DIVINE_DESTINY | DivineDestiny | SPECIAL | EVENT | relics.cpp | relic_coverage_round7.cpp |
| AMETHYST_AUBERGINE | AmethystAubergine | COMMON | SHARED | relics.cpp | relic_contract.cpp,rules_regression.cpp,snapshot_validation.cpp |
| ANCHOR | Anchor | COMMON | SHARED | relics.cpp | observation_contract.cpp,relic_contract.cpp,relic_raw_rarity.cpp,rules_regression.cpp |
| BAG_OF_PREPARATION | BagOfPreparation | COMMON | SHARED | relics.cpp | rules_regression.cpp |
| BLOOD_VIAL | BloodVial | COMMON | SHARED | relics.cpp | rules_regression.cpp |
| BONE_FLUTE | BoneFlute | COMMON | NECROBINDER | necrobinder.cpp,relics.cpp | relic_shared_round5.cpp |
| BRONZE_SCALES | BronzeScales | COMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| CENTENNIAL_PUZZLE | CentennialPuzzle | COMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| DATA_DISK | DataDisk | COMMON | DEFECT | relics.cpp | relic_coverage_round7.cpp |
| FENCING_MANUAL | FencingManual | COMMON | REGENT | relics.cpp | relic_coverage_round7.cpp |
| FESTIVE_POPPER | FestivePopper | COMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| GORGET | Gorget | COMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| HAPPY_FLOWER | HappyFlower | COMMON | SHARED | relics.cpp | native_step1_relic_replace.cpp |
| JUZU_BRACELET | JuzuBracelet | COMMON | SHARED | relics.cpp,run.cpp | relic_contract.cpp,relic_shared_round5.cpp |
| LANTERN | Lantern | COMMON | SHARED | relics.cpp | rules_regression.cpp |
| MEAL_TICKET | MealTicket | COMMON | SHARED | relics.cpp,run.cpp | relic_contract.cpp,rules_regression.cpp |
| ODDLY_SMOOTH_STONE | OddlySmoothStone | COMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| PENDULUM | Pendulum | COMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| PERMAFROST | Permafrost | COMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| POTION_BELT | PotionBelt | COMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| RED_SKULL | RedSkull | COMMON | IRONCLAD | battle.cpp,relics.cpp | native_round3_shared_alignment.cpp |
| REGAL_PILLOW | RegalPillow | COMMON | SHARED | events.cpp,relics.cpp,run.cpp | native_event_round3_alignment.cpp |
| SNECKO_SKULL | SneckoSkull | COMMON | SILENT | battle_powers.cpp,relics.cpp | relic_coverage_round7.cpp |
| STRAWBERRY | Strawberry | COMMON | SHARED | relics.cpp | native_step1_relic_replace.cpp |
| STRIKE_DUMMY | StrikeDummy | COMMON | SHARED | relics.cpp | native_relic_round3_alignment.cpp,rules_regression.cpp |
| TINY_MAILBOX | TinyMailbox | COMMON | SHARED | relics.cpp,run.cpp | native_event_round3_alignment.cpp |
| VAJRA | Vajra | COMMON | SHARED | relics.cpp | native_step2_relic_lifecycle.cpp |
| VENERABLE_TEA_SET | VenerableTeaSet | COMMON | SHARED | relics.cpp,run.cpp | native_event_round3_alignment.cpp |
| WAR_PAINT | WarPaint | COMMON | SHARED | relics.cpp | native_relic_round2_alignment.cpp |
| WHETSTONE | Whetstone | COMMON | SHARED | relics.cpp | native_relic_round2_alignment.cpp |
| BOOK_OF_FIVE_RINGS | BookOfFiveRings | COMMON | SHARED | relics.cpp,run.cpp | native_relic_round2_alignment.cpp,native_relic_round3_alignment.cpp,native_run_alignment.cpp,native_step2_persistent.cpp,relic_contract.cpp,snapshot_validation.cpp |
| AKABEKO | Akabeko | UNCOMMON | SHARED | relics.cpp | relic_raw_rarity.cpp |
| BAG_OF_MARBLES | BagOfMarbles | UNCOMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| BELLOWS | Bellows | UNCOMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| BOOK_REPAIR_KNIFE | BookRepairKnife | UNCOMMON | NECROBINDER | necrobinder.cpp,relics.cpp | relic_shared_round5.cpp |
| BOWLER_HAT | BowlerHat | UNCOMMON | SHARED | battle.cpp,relics.cpp | relic_contract.cpp,rules_regression.cpp |
| CANDELABRA | Candelabra | UNCOMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| ETERNAL_FEATHER | EternalFeather | UNCOMMON | SHARED | relics.cpp,run.cpp | native_event_round3_alignment.cpp |
| FUNERARY_MASK | FuneraryMask | UNCOMMON | NECROBINDER | necrobinder.cpp,relics.cpp | relic_shared_round5.cpp |
| GALACTIC_DUST | GalacticDust | UNCOMMON | REGENT | relics.cpp | relic_coverage_round7.cpp |
| GOLD_PLATED_CABLES | GoldPlatedCables | UNCOMMON | DEFECT | defect.cpp,relics.cpp | relic_shared_round5.cpp |
| GREMLIN_HORN | GremlinHorn | UNCOMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| HORN_CLEAT | HornCleat | UNCOMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| JOSS_PAPER | JossPaper | UNCOMMON | SHARED | relics.cpp | rules_regression.cpp |
| KUSARIGAMA | Kusarigama | UNCOMMON | SHARED | relics.cpp | rules_regression.cpp |
| LETTER_OPENER | LetterOpener | UNCOMMON | SHARED | relics.cpp | rules_regression.cpp |
| LUCKY_FYSH | LuckyFysh | UNCOMMON | SHARED | relics.cpp,run.cpp | map_event_audit_regression.cpp,native_relic_round2_alignment.cpp,native_relic_round3_alignment.cpp,native_step2_persistent.cpp,relic_contract.cpp,scroll_boxes_regression.cpp,snapshot_validation.cpp |
| MERCURY_HOURGLASS | MercuryHourglass | UNCOMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| MINIATURE_CANNON | MiniatureCannon | UNCOMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| NUNCHAKU | Nunchaku | UNCOMMON | SHARED | relics.cpp | rules_regression.cpp |
| ORICHALCUM | Orichalcum | UNCOMMON | SHARED | relics.cpp | rules_regression.cpp |
| ORNAMENTAL_FAN | OrnamentalFan | UNCOMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| PANTOGRAPH | Pantograph | UNCOMMON | SHARED | relics.cpp,run.cpp | rules_regression.cpp |
| PAPER_PHROG | PaperPhrog | UNCOMMON | IRONCLAD | battle.cpp,necrobinder.cpp,relics.cpp | relic_coverage_round7.cpp |
| PARRYING_SHIELD | ParryingShield | UNCOMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| PEAR | Pear | UNCOMMON | SHARED | relics.cpp | native_step1_relic_replace.cpp |
| PEN_NIB | PenNib | UNCOMMON | SHARED | battle.cpp,relics.cpp | native_card_alignment.cpp,native_step1_relic_replace.cpp,native_step2_relic_lifecycle.cpp,rules_regression.cpp |
| PETRIFIED_TOAD | PetrifiedToad | UNCOMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| PLANISPHERE | Planisphere | UNCOMMON | SHARED | relics.cpp,run.cpp | relic_contract.cpp,rules_regression.cpp |
| RED_MASK | RedMask | UNCOMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| REGALITE | Regalite | UNCOMMON | REGENT | relics.cpp | relic_coverage_round7.cpp |
| REPTILE_TRINKET | ReptileTrinket | UNCOMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| RIPPLE_BASIN | RippleBasin | UNCOMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| SELF_FORMING_CLAY | SelfFormingClay | UNCOMMON | IRONCLAD | relics.cpp | rules_regression.cpp |
| SPARKLING_ROUGE | SparklingRouge | UNCOMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| STONE_CRACKER | StoneCracker | UNCOMMON | SHARED | relics.cpp | native_relic_round3_alignment.cpp |
| TUNING_FORK | TuningFork | UNCOMMON | SHARED | relics.cpp | rules_regression.cpp |
| TINGSHA | Tingsha | UNCOMMON | SILENT | relics.cpp | relic_coverage_round7.cpp |
| VAMBRACE | Vambrace | UNCOMMON | SHARED | relics.cpp | rules_regression.cpp |
| ART_OF_WAR | ArtOfWar | RARE | SHARED | relics.cpp | relic_raw_rarity.cpp |
| BEATING_REMNANT | BeatingRemnant | RARE | SHARED | relics.cpp | relic_coverage_round7.cpp |
| BIG_HAT | BigHat | RARE | NECROBINDER | relics.cpp | relic_coverage_round7.cpp |
| BOOKMARK | Bookmark | RARE | NECROBINDER | relics.cpp | relic_coverage_round7.cpp |
| CAPTAINS_WHEEL | CaptainsWheel | RARE | SHARED | relics.cpp | relic_coverage_round7.cpp |
| CHANDELIER | Chandelier | RARE | SHARED | relics.cpp | relic_coverage_round7.cpp |
| CHARONS_ASHES | CharonsAshes | RARE | IRONCLAD | relics.cpp | relic_coverage_round7.cpp |
| DEMON_TONGUE | DemonTongue | RARE | IRONCLAD | relics.cpp | relic_coverage_round7.cpp |
| EMOTION_CHIP | EmotionChip | RARE | DEFECT | relics.cpp | relic_coverage_round7.cpp |
| FROZEN_EGG | FrozenEgg | RARE | SHARED | events.cpp,relic_card_rewards.cpp,relics.cpp,run.cpp | native_step2_card_rewards.cpp,relic_contract.cpp |
| GAMBLING_CHIP | GamblingChip | RARE | SHARED | relics.cpp | relic_coverage_round7.cpp |
| GAME_PIECE | GamePiece | RARE | SHARED | relics.cpp | relic_coverage_round7.cpp |
| GIRYA | Girya | RARE | SHARED | relics.cpp,run.cpp | relic_contract.cpp |
| HELICAL_DART | HelicalDart | RARE | SILENT | relics.cpp | relic_coverage_round7.cpp |
| ICE_CREAM | IceCream | RARE | SHARED | relics.cpp | relic_coverage_round7.cpp |
| INTIMIDATING_HELMET | IntimidatingHelmet | RARE | SHARED | battle.cpp,relics.cpp | rules_regression.cpp |
| IVORY_TILE | IvoryTile | RARE | NECROBINDER | relics.cpp | relic_coverage_round7.cpp |
| KUNAI | Kunai | RARE | SHARED | relics.cpp | relic_coverage_round7.cpp |
| LASTING_CANDY | LastingCandy | RARE | SHARED | relics.cpp,run.cpp | relic_contract.cpp,relic_shared_round5.cpp |
| LIZARD_TAIL | LizardTail | RARE | SHARED | relics.cpp | native_event_round3_alignment.cpp,native_relic_round3_alignment.cpp,native_round3_shared_alignment.cpp,native_run_alignment.cpp,native_step1_relic_replace.cpp,native_step1_self_damage.cpp,native_step2_relic_lifecycle.cpp |
| LUNAR_PASTRY | LunarPastry | RARE | REGENT | relics.cpp | relic_coverage_round7.cpp |
| MANGO | Mango | RARE | SHARED | relics.cpp | relic_coverage_round7.cpp |
| MEAT_ON_THE_BONE | MeatOnTheBone | RARE | SHARED | relics.cpp | native_relic_round2_alignment.cpp |
| METRONOME | Metronome | RARE | DEFECT | defect.cpp,relics.cpp | relic_shared_round5.cpp |
| MINI_REGENT | MiniRegent | RARE | REGENT | relics.cpp | relic_coverage_round7.cpp |
| MOLTEN_EGG | MoltenEgg | RARE | SHARED | events.cpp,relic_card_rewards.cpp,relic_persistent.cpp,relics.cpp,run.cpp | map_event_audit_regression.cpp,native_relic_round2_alignment.cpp,native_relic_round3_alignment.cpp,native_step2_card_rewards.cpp,native_step2_persistent.cpp,native_step2_relic_lifecycle.cpp,relic_contract.cpp |
| MUMMIFIED_HAND | MummifiedHand | RARE | SHARED | relics.cpp | rules_regression.cpp |
| OLD_COIN | OldCoin | RARE | SHARED | relics.cpp | relic_contract.cpp,snapshot_validation.cpp |
| ORANGE_DOUGH | OrangeDough | RARE | REGENT | relics.cpp | relic_coverage_round7.cpp |
| POCKETWATCH | Pocketwatch | RARE | SHARED | relics.cpp | relic_coverage_round7.cpp |
| POWER_CELL | PowerCell | RARE | DEFECT | relics.cpp | relic_coverage_round7.cpp |
| PRAYER_WHEEL | PrayerWheel | RARE | SHARED | relics.cpp,run.cpp | relic_coverage_round7.cpp |
| RAINBOW_RING | RainbowRing | RARE | SHARED | relics.cpp | relic_coverage_round7.cpp |
| RAZOR_TOOTH | RazorTooth | RARE | SHARED | battle.cpp,relics.cpp | relic_coverage_round7.cpp |
| SHOVEL | Shovel | RARE | SHARED | relics.cpp,run.cpp | relic_contract.cpp |
| SHURIKEN | Shuriken | RARE | SHARED | relics.cpp | relic_coverage_round7.cpp |
| STONE_CALENDAR | StoneCalendar | RARE | SHARED | relics.cpp | relic_coverage_round7.cpp |
| STURDY_CLAMP | SturdyClamp | RARE | SHARED | relics.cpp | relic_coverage_round7.cpp |
| THE_COURIER | TheCourier | RARE | SHARED | relics.cpp,run.cpp | rules_regression.cpp,snapshot_validation.cpp |
| TOUGH_BANDAGES | ToughBandages | RARE | SILENT | relics.cpp | relic_coverage_round7.cpp |
| TOXIC_EGG | ToxicEgg | RARE | SHARED | events.cpp,relic_card_rewards.cpp,relics.cpp,run.cpp | native_step2_card_rewards.cpp,relic_contract.cpp,rules_regression.cpp |
| TUNGSTEN_ROD | TungstenRod | RARE | SHARED | events.cpp,relics.cpp | native_card_round3_alignment.cpp,native_event_round3_alignment.cpp,native_relic_round3_alignment.cpp,native_run_alignment.cpp,native_step1_self_damage.cpp,native_step2_necrobinder.cpp,native_underdocks_events.cpp |
| UNCEASING_TOP | UnceasingTop | RARE | SHARED | relics.cpp | relic_coverage_round7.cpp |
| UNSETTLING_LAMP | UnsettlingLamp | RARE | SHARED | battle_powers.cpp,relics.cpp | relic_coverage_round7.cpp |
| RUINED_HELMET | RuinedHelmet | RARE | IRONCLAD | relics.cpp | rules_regression.cpp |
| VEXING_PUZZLEBOX | VexingPuzzlebox | RARE | SHARED | relics.cpp | relic_coverage_round7.cpp |
| WHITE_BEAST_STATUE | WhiteBeastStatue | RARE | SHARED | relics.cpp,run.cpp | relic_contract.cpp |
| WHITE_STAR | WhiteStar | RARE | SHARED | relics.cpp,run.cpp | relic_contract.cpp,relic_shared_round5.cpp |
| PAPER_KRANE | PaperKrane | RARE | SILENT | battle.cpp,relics.cpp | relic_coverage_round7.cpp |
| BELT_BUCKLE | BeltBuckle | SPECIAL | SHARED | relics.cpp | relic_contract.cpp,relic_coverage_round7.cpp |
| BREAD | Bread | SPECIAL | SHARED | relics.cpp | relic_coverage_round7.cpp |
| BRIMSTONE | Brimstone | SPECIAL | IRONCLAD | relics.cpp | relic_coverage_round7.cpp |
| BURNING_STICKS | BurningSticks | SPECIAL | SHARED | relics.cpp | relic_coverage_round7.cpp |
| CAULDRON | Cauldron | SPECIAL | SHARED | relics.cpp,run.cpp | relic_raw_rarity.cpp,snapshot_validation.cpp |
| CHEMICAL_X | ChemicalX | SPECIAL | SHARED | battle.cpp,battle_flow.cpp,relics.cpp | rules_regression.cpp |
| DINGY_RUG | DingyRug | SPECIAL | SHARED | relic_card_rewards.cpp,relics.cpp,run.cpp | native_step2_card_rewards.cpp |
| DOLLYS_MIRROR | DollysMirror | SPECIAL | SHARED | relics.cpp,run.cpp | relic_shared_round5.cpp |
| DRAGON_FRUIT | DragonFruit | SPECIAL | SHARED | battle.cpp,relics.cpp | relic_contract.cpp,rules_regression.cpp |
| GHOST_SEED | GhostSeed | SPECIAL | SHARED | relics.cpp,run.cpp | relic_coverage_round7.cpp |
| GNARLED_HAMMER | GnarledHammer | SPECIAL | SHARED | relics.cpp,run.cpp | relic_shared_round5.cpp |
| KIFUDA | Kifuda | SPECIAL | SHARED | relics.cpp,run.cpp | relic_shared_round5.cpp |
| LAVA_LAMP | LavaLamp | SPECIAL | SHARED | battle_damage.cpp,relics.cpp,run.cpp | rules_regression.cpp |
| LEES_WAFFLE | LeesWaffle | SPECIAL | SHARED | relics.cpp | relic_coverage_round7.cpp |
| MEMBERSHIP_CARD | MembershipCard | SPECIAL | SHARED | relics.cpp,run.cpp | rules_regression.cpp,snapshot_validation.cpp |
| MINIATURE_TENT | MiniatureTent | SPECIAL | SHARED | relics.cpp,run.cpp | relic_coverage_round7.cpp |
| MYSTIC_LIGHTER | MysticLighter | SPECIAL | SHARED | battle.cpp,relics.cpp | relic_coverage_round7.cpp |
| NINJA_SCROLL | NinjaScroll | SPECIAL | SILENT | relics.cpp | relic_coverage_round7.cpp |
| ORRERY | Orrery | SPECIAL | SHARED | relics.cpp,run.cpp | relic_shared_round5.cpp |
| PUNCH_DAGGER | PunchDagger | SPECIAL | SHARED | relics.cpp,run.cpp | relic_shared_round5.cpp |
| RINGING_TRIANGLE | RingingTriangle | SPECIAL | SHARED | relics.cpp | relic_coverage_round7.cpp |
| ROYAL_STAMP | RoyalStamp | SPECIAL | SHARED | relics.cpp,run.cpp | relic_shared_round5.cpp |
| RUNIC_CAPACITOR | RunicCapacitor | SPECIAL | DEFECT | relics.cpp | relic_coverage_round7.cpp |
| SCREAMING_FLAGON | ScreamingFlagon | SPECIAL | SHARED | relics.cpp | relic_coverage_round7.cpp |
| SLING_OF_COURAGE | SlingOfCourage | SPECIAL | SHARED | relics.cpp | relic_coverage_round7.cpp |
| THE_ABACUS | TheAbacus | SPECIAL | SHARED | relics.cpp | relic_coverage_round7.cpp |
| TOOLBOX | Toolbox | SPECIAL | SHARED | relics.cpp | rules_regression.cpp |
| UNDYING_SIGIL | UndyingSigil | SPECIAL | NECROBINDER | necrobinder.cpp,relics.cpp | relic_shared_round5.cpp |
| VITRUVIAN_MINION | VitruvianMinion | SPECIAL | REGENT | battle.cpp,relics.cpp | relic_coverage_round7.cpp |
| WING_CHARM | WingCharm | SPECIAL | SHARED | relic_card_rewards.cpp,relics.cpp,run.cpp | native_step2_card_rewards.cpp,relic_shared_round5.cpp |
| ALCHEMICAL_COFFER | AlchemicalCoffer | SPECIAL | EVENT | events.cpp,relics.cpp | relic_coverage_round7.cpp |
| ARCANE_SCROLL | ArcaneScroll | SPECIAL | EVENT | events.cpp,relic_card_rewards.cpp,relics.cpp | native_step2_card_rewards.cpp,rules_regression.cpp |
| ARCHAIC_TOOTH | ArchaicTooth | SPECIAL | EVENT | events.cpp,relics.cpp | relic_coverage_round7.cpp |
| ASTROLABE | Astrolabe | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | map_event_audit_regression.cpp,native_run_alignment.cpp,rules_regression.cpp |
| BEAUTIFUL_BRACELET | BeautifulBracelet | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp,native_run_alignment.cpp |
| BIG_MUSHROOM | BigMushroom | SPECIAL | EVENT | events.cpp,relics.cpp | relic_contract.cpp |
| BIIIG_HUG | BiiigHug | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | map_event_audit_regression.cpp |
| BING_BONG | BingBong | SPECIAL | EVENT | events.cpp,relic_card_rewards.cpp,relic_persistent.cpp,relics.cpp,run.cpp | map_event_audit_regression.cpp,native_relic_round2_alignment.cpp,native_relic_round3_alignment.cpp,native_run_alignment.cpp,native_step2_persistent.cpp,native_step2_relic_lifecycle.cpp,relic_raw_rarity.cpp,rules_regression.cpp,scroll_boxes_regression.cpp,snapshot_validation.cpp |
| BLACK_STAR | BlackStar | SPECIAL | EVENT | events.cpp,run.cpp | map_event_audit_regression.cpp,snapshot_validation.cpp |
| BLESSED_ANTLER | BlessedAntler | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp |
| BLOOD_SOAKED_ROSE | BloodSoakedRose | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp,relic_contract.cpp |
| BONE_TEA | BoneTea | SPECIAL | EVENT | battle.cpp,events.cpp,relic_persistent.cpp,relics.cpp | native_step2_persistent.cpp,rules_regression.cpp |
| BOOMING_CONCH | BoomingConch | SPECIAL | EVENT | events.cpp,relics.cpp | rules_regression.cpp |
| BRILLIANT_SCARF | BrilliantScarf | SPECIAL | EVENT | battle.cpp,events.cpp | map_event_audit_regression.cpp |
| BYRDPIP | Byrdpip | SPECIAL | EVENT | relic_persistent.cpp,relics.cpp | native_step2_persistent.cpp |
| CALLING_BELL | CallingBell | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | map_event_audit_regression.cpp,relic_contract.cpp,snapshot_validation.cpp |
| CHOICES_PARADOX | ChoicesParadox | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp,rules_regression.cpp |
| CHOSEN_CHEESE | ChosenCheese | SPECIAL | EVENT | events.cpp,relics.cpp | relic_coverage_round7.cpp |
| CLAWS | Claws | SPECIAL | EVENT | events.cpp,relics.cpp | enchantment_contract.cpp |
| CROSSBOW | Crossbow | SPECIAL | EVENT | events.cpp,relics.cpp | relic_coverage_round7.cpp |
| CURSED_PEARL | CursedPearl | SPECIAL | EVENT | events.cpp,relics.cpp | rules_regression.cpp |
| DARKSTONE_PERIAPT | DarkstonePeriapt | SPECIAL | EVENT | events.cpp,run.cpp | rules_regression.cpp,snapshot_validation.cpp |
| DAUGHTER_OF_THE_WIND | DaughterOfTheWind | SPECIAL | EVENT | events.cpp,relics.cpp | rules_regression.cpp |
| DELICATE_FROND | DelicateFrond | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp |
| DIAMOND_DIADEM | DiamondDiadem | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp |
| DISTINGUISHED_CAPE | DistinguishedCape | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | map_event_audit_regression.cpp,native_relic_round3_alignment.cpp,native_round3_shared_alignment.cpp,relic_contract.cpp |
| DREAM_CATCHER | DreamCatcher | SPECIAL | EVENT | events.cpp,relic_card_rewards.cpp,run.cpp | native_step2_card_rewards.cpp,rules_regression.cpp |
| DRIFTWOOD | Driftwood | SPECIAL | EVENT | events.cpp,run.cpp | relic_event_audit.cpp,relic_shared_round5.cpp |
| DUSTY_TOME | DustyTome | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | map_event_audit_regression.cpp |
| ECTOPLASM | Ectoplasm | SPECIAL | EVENT | battle.cpp,events.cpp,relics.cpp | relic_coverage_round7.cpp |
| ELECTRIC_SHRYMP | ElectricShrymp | SPECIAL | EVENT | events.cpp,relics.cpp | relic_coverage_round7.cpp |
| EMBER_TEA | EmberTea | SPECIAL | EVENT | events.cpp,relics.cpp | rules_regression.cpp |
| EMPTY_CAGE | EmptyCage | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | map_event_audit_regression.cpp,native_run_alignment.cpp |
| FAKE_ANCHOR | FakeAnchor | SPECIAL | EVENT | events.cpp,relics.cpp | relic_coverage_round7.cpp |
| FAKE_BLOOD_VIAL | FakeBloodVial | SPECIAL | EVENT | events.cpp,relics.cpp | relic_coverage_round7.cpp |
| FAKE_HAPPY_FLOWER | FakeHappyFlower | SPECIAL | EVENT | events.cpp,relics.cpp | relic_coverage_round7.cpp |
| FAKE_LEES_WAFFLE | FakeLeesWaffle | SPECIAL | EVENT | events.cpp,relics.cpp | relic_coverage_round7.cpp |
| FAKE_MANGO | FakeMango | SPECIAL | EVENT | events.cpp,relics.cpp | relic_coverage_round7.cpp |
| FAKE_MERCHANTS_RUG | FakeMerchantsRug | SPECIAL | EVENT | events.cpp | relic_event_audit.cpp,rules_regression.cpp |
| FAKE_ORICHALCUM | FakeOrichalcum | SPECIAL | EVENT | events.cpp,relics.cpp | relic_coverage_round7.cpp |
| FAKE_SNECKO_EYE | FakeSneckoEye | SPECIAL | EVENT | battle.cpp,events.cpp | relic_coverage_round7.cpp |
| FAKE_STRIKE_DUMMY | FakeStrikeDummy | SPECIAL | EVENT | events.cpp,relics.cpp | native_relic_round3_alignment.cpp |
| FAKE_VENERABLE_TEA_SET | FakeVenerableTeaSet | SPECIAL | EVENT | events.cpp,relic_persistent.cpp,relics.cpp | native_step2_persistent.cpp |
| FIDDLE | Fiddle | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp |
| FORGOTTEN_SOUL | ForgottenSoul | SPECIAL | EVENT | events.cpp,relics.cpp | rules_regression.cpp |
| FRAGRANT_MUSHROOM | FragrantMushroom | SPECIAL | EVENT | events.cpp,relics.cpp | native_run_alignment.cpp |
| FRESNEL_LENS | FresnelLens | SPECIAL | EVENT | events.cpp,relic_card_rewards.cpp,run.cpp | native_step2_card_rewards.cpp,native_step2_persistent.cpp,native_underdocks_events.cpp |
| FUR_COAT | FurCoat | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp |
| GLASS_EYE | GlassEye | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | relic_raw_rarity.cpp,snapshot_validation.cpp |
| GLITTER | Glitter | SPECIAL | EVENT | events.cpp,relic_card_rewards.cpp,run.cpp | map_event_audit_regression.cpp,native_step2_card_rewards.cpp,relic_event_audit.cpp |
| GOLDEN_COMPASS | GoldenCompass | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | map_event_audit_regression.cpp,native_act_alignment.cpp |
| GOLDEN_PEARL | GoldenPearl | SPECIAL | EVENT | events.cpp,relics.cpp | rules_regression.cpp |
| HAND_DRILL | HandDrill | SPECIAL | EVENT | battle_damage.cpp,events.cpp | rules_regression.cpp |
| HISTORY_COURSE | HistoryCourse | SPECIAL | EVENT | events.cpp,relics.cpp | quest_cards.cpp,rules_regression.cpp |
| IRON_CLUB | IronClub | SPECIAL | EVENT | events.cpp,relics.cpp | rules_regression.cpp |
| JEWELED_MASK | JeweledMask | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp |
| JEWELRY_BOX | JewelryBox | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp,rules_regression.cpp |
| LARGE_CAPSULE | LargeCapsule | SPECIAL | EVENT | events.cpp,relics.cpp | native_step2_relic_lifecycle.cpp,rules_regression.cpp |
| LAVA_ROCK | LavaRock | SPECIAL | EVENT | events.cpp,run.cpp | rules_regression.cpp |
| LEAD_PAPERWEIGHT | LeadPaperweight | SPECIAL | EVENT | events.cpp,relic_card_rewards.cpp,relics.cpp | native_step2_card_rewards.cpp,rules_regression.cpp |
| LEAFY_POULTICE | LeafyPoultice | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | native_relic_round3_alignment.cpp,rules_regression.cpp |
| LOOMING_FRUIT | LoomingFruit | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp |
| LORDS_PARASOL | LordsParasol | SPECIAL | EVENT | events.cpp,run.cpp | map_event_audit_regression.cpp |
| LOST_COFFER | LostCoffer | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | rules_regression.cpp,snapshot_validation.cpp |
| LOST_WISP | LostWisp | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp |
| MASSIVE_SCROLL | MassiveScroll | SPECIAL | EVENT | events.cpp,relics.cpp | rules_regression.cpp |
| MAW_BANK | MawBank | SPECIAL | EVENT | events.cpp,run.cpp | rules_regression.cpp |
| MEAT_CLEAVER | MeatCleaver | SPECIAL | EVENT | events.cpp,run.cpp | rules_regression.cpp |
| MR_STRUGGLES | MrStruggles | SPECIAL | EVENT | events.cpp,relics.cpp | rules_regression.cpp |
| MUSIC_BOX | MusicBox | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp |
| NEOWS_TORMENT | NeowsTorment | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | native_relic_round3_alignment.cpp,native_round3_shared_alignment.cpp,rules_regression.cpp |
| NEW_LEAF | NewLeaf | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | rules_regression.cpp |
| NUTRITIOUS_OYSTER | NutritiousOyster | SPECIAL | EVENT | events.cpp,relics.cpp | rules_regression.cpp |
| NUTRITIOUS_SOUP | NutritiousSoup | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp,relic_event_audit.cpp |
| PAELS_BLOOD | PaelsBlood | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp |
| PAELS_CLAW | PaelsClaw | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp,rules_regression.cpp |
| PAELS_EYE | PaelsEye | SPECIAL | EVENT | battle_turns.cpp,events.cpp | map_event_audit_regression.cpp,relic_event_audit.cpp,relic_shared_round5.cpp |
| PAELS_FLESH | PaelsFlesh | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp |
| PAELS_GROWTH | PaelsGrowth | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | map_event_audit_regression.cpp |
| PAELS_HORN | PaelsHorn | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp |
| PAELS_LEGION | PaelsLegion | SPECIAL | EVENT | events.cpp,relic_persistent.cpp,relics.cpp | map_event_audit_regression.cpp |
| PAELS_TEARS | PaelsTears | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp |
| PAELS_TOOTH | PaelsTooth | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | map_event_audit_regression.cpp,native_relic_round2_alignment.cpp |
| PAELS_WING | PaelsWing | SPECIAL | EVENT | events.cpp,run.cpp | map_event_audit_regression.cpp |
| PANDORAS_BOX | PandorasBox | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | map_event_audit_regression.cpp,native_relic_round2_alignment.cpp |
| PHILOSOPHERS_STONE | PhilosophersStone | SPECIAL | EVENT | events.cpp,relics.cpp | relic_coverage_round7.cpp |
| POLLINOUS_CORE | PollinousCore | SPECIAL | EVENT | events.cpp,relics.cpp | rules_regression.cpp |
| POMANDER | Pomander | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | native_relic_round2_alignment.cpp,observation_contract.cpp,rules_regression.cpp |
| PRECARIOUS_SHEARS | PrecariousShears | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | native_run_alignment.cpp,rules_regression.cpp |
| PRECISE_SCISSORS | PreciseScissors | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | native_relic_round2_alignment.cpp,native_run_alignment.cpp,rules_regression.cpp |
| PRESERVED_FOG | PreservedFog | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | map_event_audit_regression.cpp,native_run_alignment.cpp,relic_contract.cpp |
| PRISMATIC_GEM | PrismaticGem | SPECIAL | EVENT | events.cpp,relic_card_rewards.cpp,relics.cpp,run.cpp | native_step2_card_rewards.cpp |
| PUMPKIN_CANDLE | PumpkinCandle | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp,relic_contract.cpp |
| RADIANT_PEARL | RadiantPearl | SPECIAL | EVENT | events.cpp,relics.cpp | relic_coverage_round7.cpp |
| ROYAL_POISON | RoyalPoison | SPECIAL | EVENT | events.cpp,relics.cpp | rules_regression.cpp |
| RUNIC_PYRAMID | RunicPyramid | SPECIAL | EVENT | battle_turns.cpp,events.cpp | map_event_audit_regression.cpp,rules_regression.cpp |
| SAI | Sai | SPECIAL | EVENT | events.cpp,relics.cpp | relic_coverage_round7.cpp |
| SAND_CASTLE | SandCastle | SPECIAL | EVENT | events.cpp,relics.cpp | native_relic_round2_alignment.cpp |
| SCROLL_BOXES | ScrollBoxes | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | rules_regression.cpp,scroll_boxes_regression.cpp |
| SEA_GLASS | SeaGlass | SPECIAL | EVENT | events.cpp,relic_card_rewards.cpp,relics.cpp | native_step2_card_rewards.cpp |
| SEAL_OF_GOLD | SealOfGold | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp,native_relic_round3_alignment.cpp |
| SERE_TALON | SereTalon | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | map_event_audit_regression.cpp,native_relic_round3_alignment.cpp,native_round3_shared_alignment.cpp,relic_contract.cpp |
| SIGNET_RING | SignetRing | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp |
| SILVER_CRUCIBLE | SilverCrucible | SPECIAL | EVENT | events.cpp,relic_card_rewards.cpp,relics.cpp,run.cpp | native_step2_card_rewards.cpp,rules_regression.cpp |
| SMALL_CAPSULE | SmallCapsule | SPECIAL | EVENT | events.cpp,relics.cpp | native_step2_relic_lifecycle.cpp,rules_regression.cpp |
| SNECKO_EYE | SneckoEye | SPECIAL | EVENT | battle.cpp,events.cpp,relics.cpp | map_event_audit_regression.cpp,rules_regression.cpp |
| SOZU | Sozu | SPECIAL | EVENT | events.cpp,potions.cpp,relics.cpp,run.cpp | rules_regression.cpp |
| SPIKED_GAUNTLETS | SpikedGauntlets | SPECIAL | EVENT | battle.cpp,events.cpp,relics.cpp | relic_coverage_round7.cpp |
| STONE_HUMIDIFIER | StoneHumidifier | SPECIAL | EVENT | events.cpp,run.cpp | native_event_round3_alignment.cpp,rules_regression.cpp |
| STORYBOOK | Storybook | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp |
| SWORD_OF_STONE | SwordOfStone | SPECIAL | EVENT | events.cpp,relics.cpp | relic_contract.cpp |
| SWORD_OF_JADE | SwordOfJade | SPECIAL | EVENT | relics.cpp | relic_contract.cpp |
| TANXS_WHISTLE | TanxsWhistle | SPECIAL | EVENT | events.cpp,relics.cpp | relic_contract.cpp |
| TEA_OF_DISCOURTESY | TeaOfDiscourtesy | SPECIAL | EVENT | events.cpp,relics.cpp | rules_regression.cpp |
| THE_BOOT | TheBoot | SPECIAL | EVENT | battle_damage.cpp,events.cpp | rules_regression.cpp |
| THROWING_AXE | ThrowingAxe | SPECIAL | EVENT | battle.cpp,events.cpp | relic_coverage_round7.cpp |
| TOASTY_MITTENS | ToastyMittens | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp,relic_contract.cpp |
| TOUCH_OF_OROBAS | TouchOfOrobas | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | native_step1_relic_replace.cpp |
| TOY_BOX | ToyBox | SPECIAL | EVENT | events.cpp,relic_lifecycle.cpp,relics.cpp | map_event_audit_regression.cpp,native_step2_relic_lifecycle.cpp |
| TRI_BOOMERANG | TriBoomerang | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | rules_regression.cpp |
| VELVET_CHOKER | VelvetChoker | SPECIAL | EVENT | battle.cpp,battle_flow.cpp,events.cpp,relics.cpp | rules_regression.cpp |
| VERY_HOT_COCOA | VeryHotCocoa | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp,relic_contract.cpp |
| WAR_HAMMER | WarHammer | SPECIAL | EVENT | events.cpp,relics.cpp | rules_regression.cpp |
| WHISPERING_EARRING | WhisperingEarring | SPECIAL | EVENT | events.cpp,relics.cpp | map_event_audit_regression.cpp |
| WONGO_CUSTOMER_APPRECIATION_BADGE | WongoCustomerAppreciationBadge | SPECIAL | EVENT | - | relic_event_audit.cpp |
| WONGOS_MYSTERY_TICKET | WongosMysteryTicket | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | relic_contract.cpp |
| YUMMY_COOKIE | YummyCookie | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | map_event_audit_regression.cpp,native_relic_round2_alignment.cpp,observation_contract.cpp |
| SYMBIOTIC_VIRUS | SymbioticVirus | UNCOMMON | DEFECT | relics.cpp | relic_coverage_round7.cpp |
| TWISTED_FUNNEL | TwistedFunnel | UNCOMMON | SHARED | relics.cpp | relic_coverage_round7.cpp |
| CLOAK_CLASP | CloakClasp | RARE | SHARED | relics.cpp | relic_coverage_round7.cpp |
| CIRCLET | Circlet | COMMON | OTHER | relics.cpp,run.cpp | native_step1_relic_replace.cpp,relic_raw_rarity.cpp,snapshot_validation.cpp |
| DEPRECATED_RELIC | DeprecatedRelic | COMMON | OTHER | - | relic_raw_rarity.cpp |
| SILKEN_TRESS | SilkenTress | SPECIAL | EVENT | events.cpp,relic_card_rewards.cpp,relics.cpp,run.cpp | native_step2_card_rewards.cpp,relic_event_audit.cpp,rules_regression.cpp |
| DOWSING_ROD | DowsingRod | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | rules_regression.cpp |
| HEFTY_TABLET | HeftyTablet | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | rules_regression.cpp |
| NEOWS_BONES | NeowsBones | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | rules_regression.cpp |
| NEOWS_SACRIFICE | NeowsSacrifice | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | rules_regression.cpp |
| FISHING_ROD | FishingRod | SPECIAL | EVENT | events.cpp,relics.cpp | rules_regression.cpp |
| KALEIDOSCOPE | Kaleidoscope | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | rules_regression.cpp |
| PHIAL_HOLSTER | PhialHolster | SPECIAL | EVENT | events.cpp,relics.cpp | rules_regression.cpp |
| WINGED_BOOTS | WingedBoots | SPECIAL | EVENT | events.cpp,relics.cpp,run.cpp | rules_regression.cpp |
| NEOWS_TALISMAN | NeowsTalisman | SPECIAL | EVENT | events.cpp,relics.cpp | rules_regression.cpp |

## Gaps (no source-effect reference)
- cards: none
- potions: DEPRECATED_POTION
- relics: WONGO_CUSTOMER_APPRECIATION_BADGE, DEPRECATED_RELIC
