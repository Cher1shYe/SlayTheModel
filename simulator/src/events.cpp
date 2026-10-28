// Run event engine. Event effects follow the v0.111.0 decompilation; options
// that need a card/enchantment UI we do not model yet are marked APPROXIMATE in
// the coverage manifest (see docs/a0-ironclad-coverage.md).
#include "sts2/run.h"

#include <cstring>

#include "sts2/monsters.h"
#include "sts2/relics.h"

namespace sts2 {

namespace {

enum EventId : int {
    EV_NEOW = 0,
    EV_AROMA_OF_CHAOS,
    EV_DENSE_VEGETATION,
    EV_SUNKEN_STATUE,
    EV_WELLSPRING,
    EV_TABLET_OF_TRUTH,
    EV_UNREST_SITE,
    EV_SAPPHIRE_SEED,
    EV_THIS_OR_THAT,
    EV_ROOM_FULL_OF_CHEESE,
    EV_POTION_COURIER,
    EV_BRAIN_LEECH,
    EV_STONE_OF_ALL_TIME,
    EV_WELCOME_TO_WONGOS,
    EV_HUNGRY_FOR_MUSHROOMS,
    EV_REFLECTIONS,
    EV_SPIRIT_GRAFTER,
    EV_LOST_WISP,
    // Unsupported (present for the manifest, excluded from event bags).
    EV_AMALGAMATOR,
    EV_AROMA_PLACEHOLDER,
    EV_BYRDONIS_NEST,
    EV_BUGSLAYER,
    EV_COLORFUL_PHILOSOPHERS,
    EV_COLOSSAL_FLOWER,
    EV_CRYSTAL_SPHERE,
    EV_DOLL_ROOM,
    EV_FAKE_MERCHANT,
    EV_FIELD_OF_MAN_SIZED_HOLES,
    EV_GRAVE_OF_THE_FORGOTTEN,
    EV_INFESTED_AUTOMATON,
    EV_JUNGLE_MAZE_ADVENTURE,
    EV_LUMINOUS_CHOIR,
    EV_MORPHIC_GROVE,
    EV_RANWID_THE_ELDER,
    EV_RELIC_TRADER,
    EV_ROUND_TEA_PARTY,
    EV_SELF_HELP_BOOK,
    EV_SLIPPERY_BRIDGE,
    EV_SYMBIOTE,
    EV_TEA_MASTER,
    EV_THE_FUTURE_OF_POTIONS,
    EV_THE_LANTERN_KEY,
    EV_THE_LEGENDS_WERE_TRUE,
    EV_TINKER_TIME,
    EV_TRIAL,
    EV_WAR_HISTORIAN_REPY,
    EV_BATTLEWORN_DUMMY,
    EV_COUNT
};

const EventInfo EVENTS[EV_COUNT] = {
    {"NEOW", EventStatus::APPROXIMATE, 3},
    {"AROMA_OF_CHAOS", EventStatus::APPROXIMATE, 0},
    {"DENSE_VEGETATION", EventStatus::IMPLEMENTED, 0},
    {"SUNKEN_STATUE", EventStatus::IMPLEMENTED, 0},
    {"WELLSPRING", EventStatus::APPROXIMATE, 0},
    {"TABLET_OF_TRUTH", EventStatus::APPROXIMATE, 0},
    {"UNREST_SITE", EventStatus::APPROXIMATE, 0},
    {"SAPPHIRE_SEED", EventStatus::APPROXIMATE, 0},
    {"THIS_OR_THAT", EventStatus::APPROXIMATE, -1},
    {"ROOM_FULL_OF_CHEESE", EventStatus::APPROXIMATE, -1},
    {"POTION_COURIER", EventStatus::APPROXIMATE, -1},
    {"BRAIN_LEECH", EventStatus::APPROXIMATE, -1},
    {"STONE_OF_ALL_TIME", EventStatus::APPROXIMATE, -1},
    {"WELCOME_TO_WONGOS", EventStatus::APPROXIMATE, -1},
    {"HUNGRY_FOR_MUSHROOMS", EventStatus::IMPLEMENTED, 2},
    {"REFLECTIONS", EventStatus::APPROXIMATE, 2},
    {"SPIRIT_GRAFTER", EventStatus::APPROXIMATE, 1},
    {"LOST_WISP", EventStatus::APPROXIMATE, 1},
    {"AMALGAMATOR", EventStatus::UNSUPPORTED, 1},
    {"AROMA_PLACEHOLDER", EventStatus::UNSUPPORTED, -1},
    {"BYRDONIS_NEST", EventStatus::UNSUPPORTED, 0},
    {"BUGSLAYER", EventStatus::UNSUPPORTED, 1},
    {"COLORFUL_PHILOSOPHERS", EventStatus::UNSUPPORTED, 1},
    {"COLOSSAL_FLOWER", EventStatus::UNSUPPORTED, 1},
    {"CRYSTAL_SPHERE", EventStatus::UNSUPPORTED, -1},
    {"DOLL_ROOM", EventStatus::UNSUPPORTED, -1},
    {"FAKE_MERCHANT", EventStatus::UNSUPPORTED, -1},
    {"FIELD_OF_MAN_SIZED_HOLES", EventStatus::UNSUPPORTED, 1},
    {"GRAVE_OF_THE_FORGOTTEN", EventStatus::UNSUPPORTED, 2},
    {"INFESTED_AUTOMATON", EventStatus::UNSUPPORTED, 1},
    {"JUNGLE_MAZE_ADVENTURE", EventStatus::UNSUPPORTED, 0},
    {"LUMINOUS_CHOIR", EventStatus::UNSUPPORTED, 0},
    {"MORPHIC_GROVE", EventStatus::UNSUPPORTED, 0},
    {"RANWID_THE_ELDER", EventStatus::UNSUPPORTED, -1},
    {"RELIC_TRADER", EventStatus::UNSUPPORTED, -1},
    {"ROUND_TEA_PARTY", EventStatus::UNSUPPORTED, 2},
    {"SELF_HELP_BOOK", EventStatus::UNSUPPORTED, -1},
    {"SLIPPERY_BRIDGE", EventStatus::UNSUPPORTED, -1},
    {"SYMBIOTE", EventStatus::UNSUPPORTED, -1},
    {"TEA_MASTER", EventStatus::UNSUPPORTED, -1},
    {"THE_FUTURE_OF_POTIONS", EventStatus::UNSUPPORTED, -1},
    {"THE_LANTERN_KEY", EventStatus::UNSUPPORTED, 1},
    {"THE_LEGENDS_WERE_TRUE", EventStatus::UNSUPPORTED, -1},
    {"TINKER_TIME", EventStatus::UNSUPPORTED, 2},
    {"TRIAL", EventStatus::UNSUPPORTED, 2},
    {"WAR_HISTORIAN_REPY", EventStatus::UNSUPPORTED, -1},
    {"BATTLEWORN_DUMMY", EventStatus::UNSUPPORTED, 2},
};

bool event_allowed_now(const RunContext &rc, int id) {
    switch (id) {
        case EV_ROOM_FULL_OF_CHEESE: return rc.act < 2;
        case EV_BRAIN_LEECH: return rc.act < 2;
        case EV_POTION_COURIER: return rc.act > 0;
        case EV_WELCOME_TO_WONGOS: return rc.act == 1 && rc.gold >= 100;
        case EV_STONE_OF_ALL_TIME: return rc.act == 1 && rc.potionCount > 0;
        default: return true;
    }
}

bool event_applies_to_act(int id, int act) {
    const int a = EVENTS[id].act;
    if (a == -1) return true;   // shared
    if (a == 3) return true;    // ancient (never in the normal event bag)
    return a == act;
}

// Event RNG: run seed + player id + deterministic hash(event name).
Rng event_rng(const RunContext &rc, int id) {
    return Rng(rc.seed + 1u, EVENTS[id].name);
}

int random_deck_index(const RunContext &rc, Rng &rng) {
    return rc.deckCount > 0 ? rng.next_int(0, rc.deckCount - 1) : -1;
}

int random_upgradable_index(const RunContext &rc, Rng &rng) {
    int candidates[MAX_DECK];
    int n = 0;
    for (int i = 0; i < rc.deckCount; ++i) {
        if (card_upgradable(rc.deck[i])) candidates[n++] = i;
    }
    return n > 0 ? candidates[rng.next_int(0, n - 1)] : -1;
}

int random_upgraded_index(const RunContext &rc, Rng &rng) {
    int candidates[MAX_DECK];
    int n = 0;
    for (int i = 0; i < rc.deckCount; ++i) {
        if (rc.deck[i].upgraded) candidates[n++] = i;
    }
    return n > 0 ? candidates[rng.next_int(0, n - 1)] : -1;
}

void remove_deck_index(RunContext &rc, int idx) {
    if (idx < 0 || idx >= rc.deckCount) return;
    for (int i = idx; i + 1 < rc.deckCount; ++i) rc.deck[i] = rc.deck[i + 1];
    --rc.deckCount;
}

void lose_hp(RunContext &rc, int amount) {
    rc.hp = std::max(0, rc.hp - amount);
    if (rc.hp <= 0) {
        rc.hp = 0;
        rc.won = false;
        rc.screen = RunScreen::RUN_OVER;
    }
}

void lose_max_hp(RunContext &rc, int amount) {
    const int real = std::min(amount, rc.maxHp - 1);
    rc.maxHp -= real;
    rc.hp = std::min(rc.hp, rc.maxHp);
    if (rc.hp <= 0) {
        rc.hp = 0;
        rc.won = false;
        rc.screen = RunScreen::RUN_OVER;
    }
}

void heal(RunContext &rc, int amount) { rc.hp = std::min(rc.maxHp, rc.hp + std::max(0, amount)); }

void gain_max_hp(RunContext &rc, int amount) {
    rc.maxHp += amount;
    rc.hp += amount;
}

void add_random_deck_card(RunContext &rc, Rng &rng, bool colorless, bool upgrade) {
    CardId pool[128];
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardId id = static_cast<CardId>(i);
        const CardDef &d = card_def(id);
        if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY)) continue;
        if (d.rarity != Rarity::COMMON && d.rarity != Rarity::UNCOMMON &&
            d.rarity != Rarity::RARE) {
            continue;
        }
        const bool isColorless =
            static_cast<int>(id) > static_cast<int>(CardId::WHIRLWIND) &&
            static_cast<int>(id) < static_cast<int>(CardId::BECKON);
        if (colorless != isColorless) continue;
        pool[n++] = id;
    }
    if (n == 0) return;
    Card c = rc.make_run_card(pool[rng.next_int(0, n - 1)], false);
    if (upgrade && card_upgradable(c)) c.upgraded = true;
    rc.add_card_to_deck(c);
}

void add_random_common_card(RunContext &rc, Rng &rng) { add_random_deck_card(rc, rng, false, false); }

void add_random_potion_event(RunContext &rc, Rng &rng, bool uncommonOnly) {
    for (int guard = 0; guard < 100; ++guard) {
        const PotionId p = static_cast<PotionId>(
            rng.next_int(1, static_cast<int>(PotionId::COUNT) - 1));
        if (!potion_def(p).ironclad) continue;
        if (uncommonOnly && potion_def(p).rarity != Rarity::UNCOMMON) continue;
        rc.add_potion(p);
        return;
    }
}

void add_relic(RunContext &rc, RelicId id) { rc.add_relic(id); }

bool add_random_shared_relic(RunContext &rc, Rng &rng, bool rareOnly) {
    int pool[256];
    int n = 0;
    for (int i = 1; i < static_cast<int>(RelicId::COUNT); ++i) {
        const RelicId id = static_cast<RelicId>(i);
        const RelicDef &d = relic_def(id);
        if (d.pool != RelicPool::SHARED && d.pool != RelicPool::IRONCLAD) continue;
        if (!relic_implemented(id)) continue;
        if (rareOnly && d.rarity != Rarity::RARE) continue;
        if (run_has_relic(rc, id)) continue;
        pool[n++] = static_cast<int>(id);
    }
    if (n == 0) return false;
    return rc.add_relic(static_cast<RelicId>(pool[rng.next_int(0, n - 1)]));
}

void finish_event(RunContext &rc) {
    rc.eventId = -1;
    rc.eventPage = 0;
    rc.eventChoiceCount = 0;
    rc.finish_room();
}

void set_page(RunContext &rc, int page, int options) {
    rc.eventPage = static_cast<std::int8_t>(page);
    rc.eventChoiceCount = static_cast<std::int8_t>(options);
}

int option_count_for(const RunContext &rc) {
    switch (rc.eventId) {
        case EV_NEOW: return 3;
        case EV_DENSE_VEGETATION: return rc.eventPage == 0 ? 2 : 1;
        case EV_TABLET_OF_TRUTH: return 2;
        case EV_WELCOME_TO_WONGOS: return 4;
        default: return rc.eventPage == 0 ? 2 : 1;
    }
}

}  // namespace

const EventInfo *event_info(int id) {
    if (id < 0 || id >= EV_COUNT) return nullptr;
    return &EVENTS[id];
}

int event_count() { return EV_COUNT; }

int event_pool_for_act(int act, int *out, int maxOut) {
    int n = 0;
    for (int id = 0; id < EV_COUNT; ++id) {
        if (EVENTS[id].status == EventStatus::UNSUPPORTED) continue;
        if (EVENTS[id].act == 3) continue;  // ancients are entered separately
        if (!event_applies_to_act(id, act)) continue;
        if (out && n < maxOut) out[n] = id;
        ++n;
    }
    return n;
}

int event_ancient_for_act(int act) {
    (void)act;
    return EV_NEOW;  // act-1 ancient; acts 2/3 ancients are not reachable as map nodes
}

void event_begin(RunContext &rc, int eventId, bool ancient) {
    rc.eventId = static_cast<std::int8_t>(eventId);
    rc.eventPage = 0;
    rc.eventChoiceCount = 0;
    rc.eventCombat = false;
    rc.eventReturnPage = 0;
    for (int &v : rc.eventData) v = 0;
    for (int &v : rc.eventRelics) v = 0;
    if (eventId < 0) {
        finish_event(rc);
        return;
    }
    Rng rng = event_rng(rc, eventId);
    switch (eventId) {
        case EV_NEOW: {
            static const RelicId positives[9] = {
                RelicId::ARCANE_SCROLL, RelicId::BOOMING_CONCH, RelicId::POMANDER,
                RelicId::GOLDEN_PEARL, RelicId::LEAD_PAPERWEIGHT, RelicId::NEW_LEAF,
                RelicId::NEOWS_TORMENT, RelicId::PRECISE_SCISSORS, RelicId::LOST_COFFER};
            static const RelicId curses[4] = {RelicId::CURSED_PEARL, RelicId::LARGE_CAPSULE,
                                              RelicId::LEAFY_POULTICE,
                                              RelicId::PRECARIOUS_SHEARS};
            int pool[16];
            int n = 0;
            for (const RelicId id : positives) pool[n++] = static_cast<int>(id);
            pool[n++] = static_cast<int>(rng.next_bool() ? RelicId::NUTRITIOUS_OYSTER
                                                         : RelicId::STONE_HUMIDIFIER);
            pool[n++] = static_cast<int>(rng.next_bool() ? RelicId::LAVA_ROCK
                                                         : RelicId::SMALL_CAPSULE);
            // UnstableShuffle then take 2.
            for (int i = n - 1; i > 0; --i) {
                const int j = rng.next_int(0, i);
                std::swap(pool[i], pool[j]);
            }
            rc.eventRelics[0] = pool[0];
            rc.eventRelics[1] = pool[1];
            rc.eventRelics[2] = static_cast<int>(curses[rng.next_int(0, 3)]);
            rc.eventChoiceCount = 3;
            set_page(rc, 0, 3);
            (void)ancient;
            break;
        }
        case EV_AROMA_OF_CHAOS:
        case EV_SUNKEN_STATUE:
        case EV_WELLSPRING:
        case EV_TABLET_OF_TRUTH:
        case EV_UNREST_SITE:
        case EV_SAPPHIRE_SEED:
        case EV_THIS_OR_THAT:
        case EV_ROOM_FULL_OF_CHEESE:
        case EV_POTION_COURIER:
        case EV_BRAIN_LEECH:
        case EV_STONE_OF_ALL_TIME:
        case EV_HUNGRY_FOR_MUSHROOMS:
        case EV_REFLECTIONS:
        case EV_SPIRIT_GRAFTER:
        case EV_LOST_WISP:
            set_page(rc, 0, 2);
            break;
        case EV_WELCOME_TO_WONGOS:
            rc.eventData[0] = static_cast<int>(RelicId::INVALID);
            for (int i = 1; i < static_cast<int>(RelicId::COUNT); ++i) {
                const RelicId id = static_cast<RelicId>(i);
                if (relic_def(id).pool != RelicPool::SHARED &&
                    relic_def(id).pool != RelicPool::IRONCLAD) {
                    continue;
                }
                if (relic_def(id).rarity != Rarity::RARE) continue;
                if (!relic_implemented(id) || run_has_relic(rc, id)) continue;
                rc.eventData[0] = i;
                break;
            }
            set_page(rc, 0, 4);
            break;
        case EV_DENSE_VEGETATION:
            set_page(rc, 0, 2);
            break;
        default:
            finish_event(rc);
            break;
    }
    rc.screen = RunScreen::EVENT;
}

int event_option_count(const RunContext &rc) {
    if (rc.screen != RunScreen::EVENT || rc.eventId < 0) return 0;
    return option_count_for(rc);
}

bool event_option_available(const RunContext &rc, int option) {
    if (option < 0 || option >= event_option_count(rc)) return false;
    if (rc.eventId == EV_WELCOME_TO_WONGOS && option <= 2) {
        return rc.gold >= 100 * (option + 1);
    }
    if (rc.eventId == EV_STONE_OF_ALL_TIME && option == 0) {
        return rc.potionCount > 0;
    }
    return true;
}

bool event_choose(RunContext &rc, int option) {
    if (rc.screen != RunScreen::EVENT || rc.eventId < 0) return false;
    if (!event_option_available(rc, option)) return false;
    const int id = rc.eventId;
    Rng rng = event_rng(rc, id);
    switch (id) {
        case EV_NEOW: {
            const RelicId pick = static_cast<RelicId>(rc.eventRelics[option]);
            add_relic(rc, pick);
            finish_event(rc);
            return true;
        }
        case EV_AROMA_OF_CHAOS: {
            if (option == 0) {
                const int idx = random_deck_index(rc, rng);
                if (idx >= 0) {
                    const CardId newId = static_cast<CardId>(
                        rng.next_int(1, static_cast<int>(CardId::COUNT) - 1));
                    rc.deck[idx] = rc.make_run_card(newId, false);
                }
            } else {
                const int idx = random_upgradable_index(rc, rng);
                if (idx >= 0) rc.deck[idx].upgraded = true;
            }
            finish_event(rc);
            return true;
        }
        case EV_DENSE_VEGETATION: {
            if (rc.eventPage == 0 && option == 0) {
                remove_deck_index(rc, random_deck_index(rc, rng));
                lose_hp(rc, 11);
                if (rc.screen == RunScreen::RUN_OVER) return true;
                finish_event(rc);
                return true;
            }
            if (rc.eventPage == 0 && option == 1) {
                heal(rc, rc.maxHp - rc.hp);
                set_page(rc, 1, 1);
                return true;
            }
            // page 1: fight
            rc.eventCombat = true;
            rc.eventReturnPage = -1;  // do not resume; finishing the fight ends the room
            rc.combatIsElite = false;
            rc.combatIsBoss = false;
            rc.begin_combat(Encounter::SETUP_DENSE_VEGETATION);
            return true;
        }
        case EV_SUNKEN_STATUE: {
            if (option == 0) {
                add_relic(rc, RelicId::SWORD_OF_STONE);
            } else {
                const int gold = 111 + rng.next_int(-10, 10);
                run_gain_gold(rc, gold);
                lose_hp(rc, 7);
            }
            finish_event(rc);
            return true;
        }
        case EV_WELLSPRING: {
            if (option == 0) {
                add_random_potion_event(rc, rng, false);
            } else {
                remove_deck_index(rc, random_deck_index(rc, rng));
            }
            finish_event(rc);
            return true;
        }
        case EV_TABLET_OF_TRUTH: {
            if (option == 1) {
                heal(rc, 20);
                finish_event(rc);
                return true;
            }
            int count = rc.eventData[0];
            int cost = 3;
            if (count == 1) cost = 6;
            else if (count == 2) cost = 12;
            else if (count == 3) cost = 24;
            else if (count >= 4) cost = std::max(1, rc.maxHp - 1);
            lose_max_hp(rc, cost);
            if (rc.screen == RunScreen::RUN_OVER) return true;
            ++rc.eventData[0];
            if (count + 1 == 4) {
                for (int i = 0; i < rc.deckCount; ++i) {
                    if (card_upgradable(rc.deck[i])) rc.deck[i].upgraded = true;
                }
            } else {
                const int idx = random_upgradable_index(rc, rng);
                if (idx >= 0) rc.deck[idx].upgraded = true;
            }
            if (count + 1 >= 5) {
                finish_event(rc);
            } else {
                set_page(rc, 1, 2);
            }
            return true;
        }
        case EV_UNREST_SITE: {
            if (option == 0) {
                heal(rc, rc.maxHp - rc.hp);
            } else {
                lose_max_hp(rc, 8);
                if (rc.screen == RunScreen::RUN_OVER) return true;
                add_random_shared_relic(rc, rng, false);
            }
            finish_event(rc);
            return true;
        }
        case EV_SAPPHIRE_SEED: {
            if (option == 0) {
                heal(rc, 9);
                const int idx = random_upgradable_index(rc, rng);
                if (idx >= 0) rc.deck[idx].upgraded = true;
            } else {
                const int idx = random_upgradable_index(rc, rng);
                if (idx >= 0) rc.deck[idx].upgraded = true;  // Sown enchantment substitute
            }
            finish_event(rc);
            return true;
        }
        case EV_THIS_OR_THAT: {
            if (option == 0) {
                lose_hp(rc, 6);
                if (rc.screen == RunScreen::RUN_OVER) return true;
                run_gain_gold(rc, rng.next_int(41, 68));
            } else {
                add_random_shared_relic(rc, rng, false);
                // Clumsy curse is not part of the modelled card set.
            }
            finish_event(rc);
            return true;
        }
        case EV_ROOM_FULL_OF_CHEESE: {
            if (option == 0) {
                add_random_common_card(rc, rng);
                add_random_common_card(rc, rng);
            } else {
                lose_hp(rc, 14);
                if (rc.screen == RunScreen::RUN_OVER) return true;
                add_relic(rc, RelicId::CHOSEN_CHEESE);
            }
            finish_event(rc);
            return true;
        }
        case EV_POTION_COURIER: {
            if (option == 0) {
                for (int i = 0; i < 3; ++i) rc.add_potion(PotionId::FOUL_POTION);
            } else {
                add_random_potion_event(rc, rng, true);
            }
            finish_event(rc);
            return true;
        }
        case EV_BRAIN_LEECH: {
            if (option == 0) {
                add_random_deck_card(rc, rng, false, false);
            } else {
                lose_hp(rc, 5);
                if (rc.screen == RunScreen::RUN_OVER) return true;
                add_random_deck_card(rc, rng, true, false);
            }
            finish_event(rc);
            return true;
        }
        case EV_STONE_OF_ALL_TIME: {
            if (option == 0) {
                if (rc.potionCount > 0) {
                    const int idx = rng.next_int(0, rc.potionCount - 1);
                    for (int i = idx; i + 1 < rc.potionCount; ++i) rc.potions[i] = rc.potions[i + 1];
                    --rc.potionCount;
                    gain_max_hp(rc, 10);
                }
            } else {
                lose_hp(rc, 6);
                if (rc.screen == RunScreen::RUN_OVER) return true;
                const int idx = random_upgradable_index(rc, rng);
                if (idx >= 0) rc.deck[idx].upgraded = true;  // Vigorous enchantment substitute
            }
            finish_event(rc);
            return true;
        }
        case EV_WELCOME_TO_WONGOS: {
            if (option == 0 && rc.gold >= 100) {
                rc.gold -= 100;
                add_random_shared_relic(rc, rng, false);
            } else if (option == 1 && rc.gold >= 200) {
                rc.gold -= 200;
                if (rc.eventData[0] > 0) {
                    add_relic(rc, static_cast<RelicId>(rc.eventData[0]));
                } else {
                    add_random_shared_relic(rc, rng, true);
                }
            } else if (option == 2 && rc.gold >= 300) {
                rc.gold -= 300;
                add_relic(rc, RelicId::WONGOS_MYSTERY_TICKET);
            } else if (option == 3) {
                const int idx = random_upgraded_index(rc, rng);
                if (idx >= 0) rc.deck[idx].upgraded = false;
            } else {
                return false;
            }
            finish_event(rc);
            return true;
        }
        case EV_HUNGRY_FOR_MUSHROOMS: {
            if (option == 0) {
                add_relic(rc, RelicId::BIG_MUSHROOM);
            } else {
                add_relic(rc, RelicId::FRAGRANT_MUSHROOM);
                lose_hp(rc, 15);
            }
            finish_event(rc);
            return true;
        }
        case EV_REFLECTIONS: {
            if (option == 0) {
                for (int i = 0; i < 2; ++i) {
                    const int idx = random_upgraded_index(rc, rng);
                    if (idx >= 0) rc.deck[idx].upgraded = false;
                }
                for (int i = 0; i < 4; ++i) {
                    const int idx = random_upgradable_index(rc, rng);
                    if (idx >= 0) rc.deck[idx].upgraded = true;
                }
            } else {
                const int original = rc.deckCount;
                for (int i = 0; i < original && rc.deckCount < MAX_DECK; ++i) {
                    Card copy = rc.deck[i];
                    copy.uid = rc.nextUid++;
                    rc.add_card_to_deck(copy);
                }
                // Bad Luck curse is not part of the modelled card set.
            }
            finish_event(rc);
            return true;
        }
        case EV_SPIRIT_GRAFTER: {
            if (option == 0) {
                heal(rc, 25);
                add_random_deck_card(rc, rng, true, false);
            } else {
                remove_deck_index(rc, random_deck_index(rc, rng));
                lose_hp(rc, 9);
            }
            if (rc.screen == RunScreen::RUN_OVER) return true;
            finish_event(rc);
            return true;
        }
        case EV_LOST_WISP: {
            if (option == 0) {
                add_relic(rc, RelicId::LOST_WISP);
                // Decay curse is not part of the modelled card set.
            } else {
                run_gain_gold(rc, 60 + rng.next_int(-15, 15));
            }
            finish_event(rc);
            return true;
        }
        default:
            return false;
    }
}

void event_resume_after_combat(RunContext &rc) {
    if (rc.eventReturnPage < 0) {
        rc.eventId = -1;
        rc.eventPage = 0;
        rc.eventChoiceCount = 0;
        rc.finish_room();
        return;
    }
    rc.eventPage = rc.eventReturnPage;
    rc.screen = RunScreen::EVENT;
}

}  // namespace sts2
