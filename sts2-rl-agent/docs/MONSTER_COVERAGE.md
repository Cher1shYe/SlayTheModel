# 怪物与遭遇覆盖清单

范围：act1–act4 原生战斗遭遇 81 个；当前通用公开状态可接入 **80**，待处理 **1**。

接入判据（静态、可复算）：

1. 当前招式可由“可见意图”唯一确定：没有两个可及后继（含初始招式的采样）显示相同意图签名；
2. 粒子能用公开招式历史重建同一个 AI 状态（不读取隐藏状态机字段、RNG 或未来分支）。

`TEST_SUBJECT` 的三形态由既有 `boss_phases` 专用契约处理，因此不进入通用判据。

| 幕 | 遭遇 | 原生阵容 | 通用接入 | 阻塞原因 |
|---|---|---|---|---|
| act3 | setup_axebots_normal | AXEBOT+AXEBOT | 是 | — |
| act2 | setup_bowlbugs_normal | BOWLBUG_EGG+BOWLBUG_ROCK+BOWLBUG_SILK | 是 | — |
| act2 | setup_bowlbugs_weak | BOWLBUG_EGG+BOWLBUG_NECTAR | 是 | — |
| act1 | setup_bygone_effigy_elite | BYGONE_EFFIGY | 是 | — |
| act1 | setup_byrdonis_elite | BYRDONIS | 是 | — |
| act1 | setup_ceremonial_beast_boss | CEREMONIAL_BEAST | 是 | — |
| act2 | setup_chompers_normal | CHOMPER+CHOMPER | 是 | — |
| act3 | setup_construct_menagerie_normal | PUNCH_CONSTRUCT+CUBEX_CONSTRUCT+CUBEX_CONSTRUCT | 是 | — |
| act4 | setup_corpse_slugs_normal | CORPSE_SLUG+CORPSE_SLUG+CORPSE_SLUG | 是 | — |
| act4 | setup_corpse_slugs_weak | CORPSE_SLUG+CORPSE_SLUG | 是 | — |
| act1 | setup_cubex_construct_normal | CUBEX_CONSTRUCT | 是 | — |
| act4 | setup_cultists_normal | CALCIFIED_CULTIST+DAMP_CULTIST | 是 | — |
| act2 | setup_decimillipede_elite | DECIMILLIPEDE_SEGMENT+DECIMILLIPEDE_SEGMENT+DECIMILLIPEDE_SEGMENT | 是 | — |
| act3 | setup_devoted_sculptor_weak | DEVOTED_SCULPTOR | 是 | — |
| act3 | setup_doormaker_boss | DOOR | 是 | — |
| act2 | setup_entomancer_elite | ENTOMANCER | 是 | — |
| act2 | setup_exoskeletons_normal | EXOSKELETON+EXOSKELETON+EXOSKELETON | 是 | — |
| act2 | setup_exoskeletons_weak | EXOSKELETON+EXOSKELETON | 是 | — |
| act3 | setup_fabricator_normal | FABRICATOR | 是 | — |
| act1 | setup_flyconid_normal | LEAF_SLIME_M+FLYCONID / TWIG_SLIME_M+FLYCONID | 是 | — |
| act1 | setup_fogmog_normal | FOGMOG | 是 | — |
| act4 | setup_fossil_stalker_normal | FOSSIL_STALKER | 是 | — |
| act3 | setup_frog_knight_normal | FROG_KNIGHT | 是 | — |
| act1 | setup_fuzzy_wurm_crawler_weak | FUZZY_WURM_CRAWLER | 是 | — |
| act3 | setup_globe_head_normal | GLOBE_HEAD | 是 | — |
| act4 | setup_gremlin_merc_normal | GREMLIN_MERC+SNEAKY_GREMLIN+FAT_GREMLIN | 是 | — |
| act4 | setup_haunted_ship_normal | HAUNTED_SHIP | 是 | — |
| act2 | setup_hunter_killer_normal | HUNTER_KILLER | 是 | — |
| act2 | setup_infested_prisms_elite | INFESTED_PRISM | 是 | — |
| act1 | setup_inklets_normal | INKLET+INKLET+INKLET | 是 | — |
| act2 | setup_kaiser_crab_boss | CRUSHER+ROCKET | 是 | — |
| act3 | setup_knights_elite | FLAIL_KNIGHT+SPECTRAL_KNIGHT+MAGI_KNIGHT | 是 | — |
| act2 | setup_knowledge_demon_boss | KNOWLEDGE_DEMON | 是 | — |
| act4 | setup_lagavulin_matriarch_boss | LAGAVULIN_MATRIARCH | 是 | — |
| act4 | setup_living_fog_normal | LIVING_FOG | 是 | — |
| act2 | setup_louse_progenitor_normal | LOUSE_PROGENITOR | 是 | — |
| act1 | setup_mawler_normal | MAWLER | 是 | — |
| act3 | setup_mecha_knight_elite | MECHA_KNIGHT | 是 | — |
| act2 | setup_mytes_normal | MYTE+MYTE | 是 | — |
| act1 | setup_nibbits_normal | NIBBIT+NIBBIT | 是 | — |
| act1 | setup_nibbits_weak | NIBBIT | 是 | — |
| act1 | setup_overgrowth_crawlers | SHRINKER_BEETLE+FUZZY_WURM_CRAWLER | 是 | — |
| act2 | setup_ovicopter_normal | OVICOPTER | 是 | — |
| act3 | setup_owl_magistrate_normal | OWL_MAGISTRATE | 是 | — |
| act4 | setup_phantasmal_gardeners_elite | PHANTASMAL_GARDENER+PHANTASMAL_GARDENER+PHANTASMAL_GARDENER+PHANTASMAL_GARDENER | 是 | — |
| act1 | setup_phrog_parasite_elite | PHROG_PARASITE | 是 | — |
| act4 | setup_punch_construct_normal | PUNCH_CONSTRUCT | 是 | — |
| act3 | setup_queen_boss | TORCH_HEAD_AMALGAM+QUEEN | 是 | — |
| act1 | setup_ruby_raiders_normal | ASSASSIN_RUBY_RAIDER+AXE_RUBY_RAIDER+CROSSBOW_RUBY_RAIDER / ASSASSIN_RUBY_RAIDER+BRUTE_RUBY_RAIDER+AXE_RUBY_RAIDER / ASSASSIN_RUBY_RAIDER+CROSSBOW_RUBY_RAIDER+TRACKER_RUBY_RAIDER / CROSSBOW_RUBY_RAIDER+ASSASSIN_RUBY_RAIDER+AXE_RUBY_RAIDER / CROSSBOW_RUBY_RAIDER+TRACKER_RUBY_RAIDER+BRUTE_RUBY_RAIDER / TRACKER_RUBY_RAIDER+CROSSBOW_RUBY_RAIDER+ASSASSIN_RUBY_RAIDER | 是 | — |
| act3 | setup_scrolls_of_biting_normal | SCROLL_OF_BITING+SCROLL_OF_BITING+SCROLL_OF_BITING+SCROLL_OF_BITING | 是 | — |
| act3 | setup_scrolls_of_biting_weak | SCROLL_OF_BITING+SCROLL_OF_BITING+SCROLL_OF_BITING | 是 | — |
| act4 | setup_seapunk_weak | SEAPUNK | 是 | — |
| act4 | setup_sewer_clam_normal | SEWER_CLAM | 是 | — |
| act1 | setup_shrinker_beetle_weak | SHRINKER_BEETLE | 是 | — |
| act4 | setup_skulking_colony_elite | SKULKING_COLONY | 是 | — |
| act3 | setup_slimed_berserker_normal | SLIMED_BERSERKER | 是 | — |
| act1 | setup_slimes_normal | TWIG_SLIME_M+LEAF_SLIME_M+LEAF_SLIME_S+TWIG_SLIME_S / TWIG_SLIME_M+LEAF_SLIME_M+TWIG_SLIME_S+LEAF_SLIME_S | 是 | — |
| act1 | setup_slimes_weak | LEAF_SLIME_S+TWIG_SLIME_S+LEAF_SLIME_M / LEAF_SLIME_S+TWIG_SLIME_S+TWIG_SLIME_M / TWIG_SLIME_S+LEAF_SLIME_S+LEAF_SLIME_M / TWIG_SLIME_S+LEAF_SLIME_S+TWIG_SLIME_M | 是 | — |
| act1 | setup_slithering_strangler_normal | LEAF_SLIME_M+SLITHERING_STRANGLER / LEAF_SLIME_S+LEAF_SLIME_S+SLITHERING_STRANGLER / SNAPPING_JAXFRUIT+SLITHERING_STRANGLER / TWIG_SLIME_S+TWIG_SLIME_S+SLITHERING_STRANGLER | 是 | — |
| act4 | setup_sludge_spinner_weak | SLUDGE_SPINNER | 是 | — |
| act2 | setup_slumbering_beetle_normal | SLUMBERING_BEETLE | 是 | — |
| act1 | setup_snapping_jaxfruit_normal | SNAPPING_JAXFRUIT+FLYCONID | 是 | — |
| act4 | setup_soul_fysh_boss | SOUL_FYSH | 是 | — |
| act3 | setup_soul_nexus_elite | SOUL_NEXUS | 是 | — |
| act2 | setup_spiny_toad_normal | SPINY_TOAD | 是 | — |
| act4 | setup_terror_eel_elite | TERROR_EEL | 是 | — |
| act3 | setup_test_subject_boss | TEST_SUBJECT | 否 | TEST_SUBJECT:ambiguous-intent |
| act2 | setup_the_insatiable_boss | THE_INSATIABLE | 是 | — |
| act1 | setup_the_kin_boss | KIN_FOLLOWER+KIN_FOLLOWER+KIN_PRIEST | 是 | — |
| act3 | setup_the_lost_and_forgotten_normal | THE_LOST+THE_FORGOTTEN | 是 | — |
| act2 | setup_the_obscura_normal | THE_OBSCURA | 是 | — |
| act2 | setup_thieving_hopper_weak | THIEVING_HOPPER | 是 | — |
| act4 | setup_toadpoles_normal | CALCIFIED_CULTIST+TOADPOLE | 是 | — |
| act4 | setup_toadpoles_weak | TOADPOLE+TOADPOLE | 是 | — |
| act2 | setup_tunneler_normal | BOWLBUG_EGG+TUNNELER / BOWLBUG_SILK+TUNNELER | 是 | — |
| act2 | setup_tunneler_weak | TUNNELER | 是 | — |
| act3 | setup_turret_operator_weak | LIVING_SHIELD+TURRET_OPERATOR | 是 | — |
| act4 | setup_two_tailed_rats_normal | TWO_TAILED_RAT+TWO_TAILED_RAT+TWO_TAILED_RAT | 是 | — |
| act1 | setup_vantom_boss | VANTOM | 是 | — |
| act1 | setup_vine_shambler_normal | VINE_SHAMBLER | 是 | — |
| act4 | setup_waterfall_giant_boss | WATERFALL_GIANT | 是 | — |

## 怪物逐项

| 怪物 | 招式数 | 初始候选 | 歧义对 | 多意图招式 | 通用接入 |
|---|---:|---|---|---:|---|
| ARCHITECT | 1 | 1 | — | 0 | 是 |
| ASSASSIN_RUBY_RAIDER | 1 | 1 | — | 0 | 是 |
| AXEBOT | 4 | 3 | — | 2 | 是 |
| AXE_RUBY_RAIDER | 3 | 1 | — | 2 | 是 |
| BATTLE_FRIEND_V1 | 1 | 1 | — | 0 | 是 |
| BATTLE_FRIEND_V2 | 1 | 1 | — | 0 | 是 |
| BATTLE_FRIEND_V3 | 1 | 1 | — | 0 | 是 |
| BIG_DUMMY | 1 | 1 | — | 0 | 是 |
| BOWLBUG_EGG | 1 | 1 | — | 1 | 是 |
| BOWLBUG_NECTAR | 3 | 1 | — | 0 | 是 |
| BOWLBUG_ROCK | 2 | 1 | — | 0 | 是 |
| BOWLBUG_SILK | 2 | 1 | — | 0 | 是 |
| BRUTE_RUBY_RAIDER | 2 | 1 | — | 0 | 是 |
| BYGONE_EFFIGY | 4 | 1 | — | 0 | 是 |
| BYRDONIS | 2 | 1 | — | 0 | 是 |
| BYRDPIP | 1 | 1 | — | 0 | 是 |
| CALCIFIED_CULTIST | 2 | 1 | — | 0 | 是 |
| CEREMONIAL_BEAST | 6 | 1 | — | 2 | 是 |
| CHOMPER | 2 | 1 | — | 0 | 是 |
| CORPSE_SLUG | 3 | 1 | — | 0 | 是 |
| CROSSBOW_RUBY_RAIDER | 2 | 1 | — | 0 | 是 |
| CRUSHER | 5 | 1 | — | 2 | 是 |
| CUBEX_CONSTRUCT | 5 | 1 | — | 2 | 是 |
| DAMP_CULTIST | 2 | 1 | — | 0 | 是 |
| DECIMILLIPEDE_SEGMENT | 5 | 1 | — | 2 | 是 |
| DECIMILLIPEDE_SEGMENT_BACK | 5 | 1 | — | 2 | 是 |
| DECIMILLIPEDE_SEGMENT_FRONT | 5 | 1 | — | 2 | 是 |
| DECIMILLIPEDE_SEGMENT_MIDDLE | 5 | 1 | — | 2 | 是 |
| DEVOTED_SCULPTOR | 2 | 1 | — | 0 | 是 |
| DOOR | 4 | 1 | — | 1 | 是 |
| DOORMAKER | 3 | 1 | — | 1 | 是 |
| ENTOMANCER | 3 | 1 | — | 0 | 是 |
| EXOSKELETON | 3 | 1 | — | 0 | 是 |
| EYE_WITH_TEETH | 1 | 1 | — | 0 | 是 |
| FABRICATOR | 3 | 2 | — | 1 | 是 |
| FAKE_MERCHANT_MONSTER | 4 | 1 | — | 1 | 是 |
| FAT_GREMLIN | 2 | 1 | — | 0 | 是 |
| FLAIL_KNIGHT | 3 | 1 | — | 0 | 是 |
| FLYCONID | 3 | 2 | — | 1 | 是 |
| FOGMOG | 4 | 1 | — | 2 | 是 |
| FOSSIL_STALKER | 3 | 1 | — | 1 | 是 |
| FROG_KNIGHT | 4 | 1 | — | 1 | 是 |
| FUZZY_WURM_CRAWLER | 3 | 1 | — | 0 | 是 |
| GAS_BOMB | 1 | 1 | — | 0 | 是 |
| GLOBE_HEAD | 3 | 1 | — | 2 | 是 |
| GREMLIN_MERC | 3 | 1 | — | 2 | 是 |
| GUARDBOT | 1 | 1 | — | 0 | 是 |
| HAUNTED_SHIP | 4 | 1 | — | 1 | 是 |
| HUNTER_KILLER | 3 | 1 | — | 0 | 是 |
| INFESTED_PRISM | 4 | 1 | — | 2 | 是 |
| INKLET | 3 | 1 | — | 0 | 是 |
| KIN_FOLLOWER | 3 | 1 | — | 0 | 是 |
| KIN_PRIEST | 4 | 1 | — | 2 | 是 |
| KNOWLEDGE_DEMON | 4 | 1 | — | 1 | 是 |
| LAGAVULIN_MATRIARCH | 5 | 1 | — | 2 | 是 |
| LEAF_SLIME_M | 2 | 1 | — | 0 | 是 |
| LEAF_SLIME_S | 2 | 2 | — | 0 | 是 |
| LIVING_FOG | 3 | 1 | — | 2 | 是 |
| LIVING_SHIELD | 2 | 1 | — | 1 | 是 |
| LOUSE_PROGENITOR | 3 | 1 | — | 2 | 是 |
| MAGI_KNIGHT | 5 | 1 | — | 1 | 是 |
| MAWLER | 3 | 1 | — | 0 | 是 |
| MECHA_KNIGHT | 4 | 1 | — | 1 | 是 |
| MULTI_ATTACK_MOVE_MONSTER | 1 | 1 | — | 0 | 是 |
| MYSTERIOUS_KNIGHT | 3 | 1 | — | 0 | 是 |
| MYTE | 3 | 1 | — | 1 | 是 |
| NIBBIT | 3 | 1 | — | 0 | 是 |
| NOISEBOT | 1 | 1 | — | 0 | 是 |
| ONE_HP_MONSTER | 1 | 1 | — | 0 | 是 |
| OSTY | 1 | 1 | — | 0 | 是 |
| OVICOPTER | 4 | 1 | — | 1 | 是 |
| OWL_MAGISTRATE | 4 | 1 | — | 1 | 是 |
| PAELS_LEGION | 1 | 1 | — | 0 | 是 |
| PARAFRIGHT | 1 | 1 | — | 0 | 是 |
| PHANTASMAL_GARDENER | 4 | 1 | — | 0 | 是 |
| PHROG_PARASITE | 2 | 1 | — | 0 | 是 |
| PUNCH_CONSTRUCT | 3 | 1 | — | 1 | 是 |
| QUEEN | 6 | 1 | — | 1 | 是 |
| ROCKET | 5 | 1 | — | 0 | 是 |
| ROYAL_GUARD | 1 | 1 | — | 0 | 是 |
| SCROLL_OF_BITING | 3 | 1 | — | 0 | 是 |
| SEAPUNK | 3 | 1 | — | 1 | 是 |
| SEWER_CLAM | 2 | 1 | — | 0 | 是 |
| SHRINKER_BEETLE | 3 | 1 | — | 0 | 是 |
| SINGLE_ATTACK_MOVE_MONSTER | 1 | 1 | — | 0 | 是 |
| SKULKING_COLONY | 4 | 1 | — | 2 | 是 |
| SLIMED_BERSERKER | 4 | 1 | — | 1 | 是 |
| SLITHERING_STRANGLER | 3 | 1 | — | 1 | 是 |
| SLUDGE_SPINNER | 3 | 1 | — | 2 | 是 |
| SLUMBERING_BEETLE | 2 | 1 | — | 1 | 是 |
| SNAPPING_JAXFRUIT | 1 | 1 | — | 1 | 是 |
| SNEAKY_GREMLIN | 2 | 1 | — | 0 | 是 |
| SOUL_FYSH | 5 | 1 | — | 2 | 是 |
| SOUL_NEXUS | 3 | 1 | — | 1 | 是 |
| SPECTRAL_KNIGHT | 3 | 1 | — | 0 | 是 |
| SPINY_TOAD | 3 | 1 | — | 0 | 是 |
| STABBOT | 1 | 1 | — | 1 | 是 |
| TEN_HP_MONSTER | 1 | 1 | — | 0 | 是 |
| TERROR_EEL | 4 | 1 | — | 1 | 是 |
| TEST_SUBJECT | 8 | 1 | RESPAWN_MOVE->MULTI_CLAW_MOVE/PHASE3_LACERATE_MOVE | 3 | 否 |
| THE_ADVERSARY_MK_ONE | 3 | 1 | — | 1 | 是 |
| THE_ADVERSARY_MK_THREE | 3 | 1 | — | 1 | 是 |
| THE_ADVERSARY_MK_TWO | 3 | 1 | — | 1 | 是 |
| THE_FORGOTTEN | 2 | 1 | — | 1 | 是 |
| THE_INSATIABLE | 5 | 1 | — | 1 | 是 |
| THE_LOST | 2 | 1 | — | 1 | 是 |
| THE_OBSCURA | 4 | 1 | — | 1 | 是 |
| THIEVING_HOPPER | 5 | 1 | — | 1 | 是 |
| TOADPOLE | 3 | 1 | — | 0 | 是 |
| TORCH_HEAD_AMALGAM | 5 | 1 | — | 0 | 是 |
| TOUGH_EGG | 2 | 1 | — | 0 | 是 |
| TRACKER_RUBY_RAIDER | 2 | 1 | — | 0 | 是 |
| TUNNELER | 4 | 1 | — | 1 | 是 |
| TURRET_OPERATOR | 3 | 1 | — | 0 | 是 |
| TWIG_SLIME_M | 2 | 1 | — | 0 | 是 |
| TWIG_SLIME_S | 1 | 1 | — | 0 | 是 |
| TWO_TAILED_RAT | 4 | 3 | — | 0 | 是 |
| VANTOM | 4 | 1 | — | 1 | 是 |
| VINE_SHAMBLER | 3 | 1 | — | 1 | 是 |
| WATERFALL_GIANT | 8 | 1 | — | 5 | 是 |
| WRIGGLER | 3 | 1 | — | 1 | 是 |
| ZAPBOT | 1 | 1 | — | 0 | 是 |
