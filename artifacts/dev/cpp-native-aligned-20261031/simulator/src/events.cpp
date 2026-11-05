#include "sts2/relic_card_rewards.h"
#include "sts2/relic_raw_rarity.h"
#include "sts2/relic_persistent.h"
// Run event engine. Event effects follow the v0.111.0 decompilation; options
// that need a card/enchantment UI we do not model yet are marked APPROXIMATE in
// the coverage manifest (see docs/a0-ironclad-coverage.md).
#include "sts2/run.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <iterator>

#include "sts2/monsters.h"
#include "sts2/card_candidates.h"
#include "sts2/potion_slots.h"
#include "sts2/relics.h"

namespace sts2 {

static void begin_event_card_selection(RunContext &rc, int kind);
void event_crystal_begin(RunContext &rc, int divinations);

namespace {

#include "sts2/native_potion_pool.inc"

int transformable_deck_count(const RunContext &rc);

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
    // Ancients (act 1-3). Neow is act 1; the others are act 2/3 + shared Darv.
    EV_DARV,
    EV_OROBAS,
    EV_PAEL,
    EV_TEZCATARA,
    EV_NONUPEIPE,
    EV_TANX,
    EV_VAKUU,
    EV_ABYSSAL_BATHS,
    EV_DROWNING_BEACON,
    EV_ENDLESS_CONVEYOR,
    EV_PUNCH_OFF,
    EV_SPIRALING_WHIRLPOOL,
    EV_SUNKEN_TREASURY,
    EV_DOORS_OF_LIGHT_AND_DARK,
    EV_TRASH_HEAP,
    EV_WATERLOGGED_SCRIPTORIUM,
    // Present in the target build's act event lists but not modelled yet.
    EV_WHISPERING_HOLLOW,
    EV_WOOD_CARVINGS,
    EV_ZEN_WEAVER,
    EV_COUNT
};

const EventInfo EVENTS[EV_COUNT] = {
    {"NEOW", EventStatus::IMPLEMENTED, 3},
    {"AROMA_OF_CHAOS", EventStatus::IMPLEMENTED, 0},
    {"DENSE_VEGETATION", EventStatus::IMPLEMENTED, 0},
    {"SUNKEN_STATUE", EventStatus::IMPLEMENTED, 0},
    {"WELLSPRING", EventStatus::IMPLEMENTED, 0},
    {"TABLET_OF_TRUTH", EventStatus::IMPLEMENTED, 0},
    {"UNREST_SITE", EventStatus::IMPLEMENTED, 0},
    {"SAPPHIRE_SEED", EventStatus::IMPLEMENTED, 0},
    {"THIS_OR_THAT", EventStatus::IMPLEMENTED, -1},
    {"ROOM_FULL_OF_CHEESE", EventStatus::IMPLEMENTED, -1},
    {"POTION_COURIER", EventStatus::IMPLEMENTED, -1},
    {"BRAIN_LEECH", EventStatus::IMPLEMENTED, -1},
    {"STONE_OF_ALL_TIME", EventStatus::IMPLEMENTED, -1},
    {"WELCOME_TO_WONGOS", EventStatus::IMPLEMENTED, -1},
    {"HUNGRY_FOR_MUSHROOMS", EventStatus::IMPLEMENTED, 2},
    {"REFLECTIONS", EventStatus::IMPLEMENTED, 2},
    {"SPIRIT_GRAFTER", EventStatus::IMPLEMENTED, 1},
    {"LOST_WISP", EventStatus::IMPLEMENTED, 1},
    {"AMALGAMATOR", EventStatus::IMPLEMENTED, 1},
    {"AROMA_PLACEHOLDER", EventStatus::UNSUPPORTED, -1},
    {"BYRDONIS_NEST", EventStatus::IMPLEMENTED, 0},
    {"BUGSLAYER", EventStatus::IMPLEMENTED, 1},
    {"COLORFUL_PHILOSOPHERS", EventStatus::IMPLEMENTED, 1},
    {"COLOSSAL_FLOWER", EventStatus::IMPLEMENTED, 1},
    {"CRYSTAL_SPHERE", EventStatus::IMPLEMENTED, -1},
    {"DOLL_ROOM", EventStatus::IMPLEMENTED, -1},
    {"FAKE_MERCHANT", EventStatus::IMPLEMENTED, -1},
    {"FIELD_OF_MAN_SIZED_HOLES", EventStatus::IMPLEMENTED, 1},
    {"GRAVE_OF_THE_FORGOTTEN", EventStatus::IMPLEMENTED, 2},
    {"INFESTED_AUTOMATON", EventStatus::IMPLEMENTED, 1},
    {"JUNGLE_MAZE_ADVENTURE", EventStatus::IMPLEMENTED, 0},
    {"LUMINOUS_CHOIR", EventStatus::IMPLEMENTED, 0},
    {"MORPHIC_GROVE", EventStatus::IMPLEMENTED, 0},
    {"RANWID_THE_ELDER", EventStatus::IMPLEMENTED, -1},
    {"RELIC_TRADER", EventStatus::IMPLEMENTED, -1},
    {"ROUND_TEA_PARTY", EventStatus::IMPLEMENTED, 2},
    {"SELF_HELP_BOOK", EventStatus::IMPLEMENTED, -1},
    {"SLIPPERY_BRIDGE", EventStatus::IMPLEMENTED, -1},
    {"SYMBIOTE", EventStatus::IMPLEMENTED, -1},
    {"TEA_MASTER", EventStatus::IMPLEMENTED, -1},
    {"THE_FUTURE_OF_POTIONS", EventStatus::IMPLEMENTED, -1},
    {"THE_LANTERN_KEY", EventStatus::IMPLEMENTED, 1},
    {"THE_LEGENDS_WERE_TRUE", EventStatus::IMPLEMENTED, -1},
    {"TINKER_TIME", EventStatus::IMPLEMENTED, 2},
    {"TRIAL", EventStatus::IMPLEMENTED, 2},
    {"WAR_HISTORIAN_REPY", EventStatus::IMPLEMENTED, -1},
    {"BATTLEWORN_DUMMY", EventStatus::IMPLEMENTED, 2},
    {"DARV", EventStatus::IMPLEMENTED, 3},
    {"OROBAS", EventStatus::IMPLEMENTED, 3},
    {"PAEL", EventStatus::IMPLEMENTED, 3},
    {"TEZCATARA", EventStatus::IMPLEMENTED, 3},
    {"NONUPEIPE", EventStatus::IMPLEMENTED, 3},
    {"TANX", EventStatus::IMPLEMENTED, 3},
    {"VAKUU", EventStatus::IMPLEMENTED, 3},
    // 4 denotes the alternate first act, not progression index 3.
    {"ABYSSAL_BATHS", EventStatus::IMPLEMENTED, 4},
    {"DROWNING_BEACON", EventStatus::IMPLEMENTED, 4},
    {"ENDLESS_CONVEYOR", EventStatus::IMPLEMENTED, 4},
    {"PUNCH_OFF", EventStatus::IMPLEMENTED, 4},
    {"SPIRALING_WHIRLPOOL", EventStatus::IMPLEMENTED, 4},
    {"SUNKEN_TREASURY", EventStatus::IMPLEMENTED, 4},
    {"DOORS_OF_LIGHT_AND_DARK", EventStatus::IMPLEMENTED, 4},
    {"TRASH_HEAP", EventStatus::IMPLEMENTED, 4},
    {"WATERLOGGED_SCRIPTORIUM", EventStatus::IMPLEMENTED, 4},
    {"WHISPERING_HOLLOW", EventStatus::IMPLEMENTED, 0},
    {"WOOD_CARVINGS", EventStatus::IMPLEMENTED, 0},
    {"ZEN_WEAVER", EventStatus::IMPLEMENTED, 1},
};

bool event_allowed_now(const RunContext &rc, int id) {
    switch (id) {
        // WarHistorianRepy.IsAllowed is false: it is only reached through the
        // LanternKey card's ModifyNextEvent hook, never from the event bag.
        case EV_WAR_HISTORIAN_REPY: return false;
        case EV_ROOM_FULL_OF_CHEESE: return rc.act < 2;
        case EV_BRAIN_LEECH: return rc.act < 2;
        case EV_POTION_COURIER: return rc.act > 0;
        case EV_WELCOME_TO_WONGOS: return rc.act == 1 && rc.gold >= 100;
        case EV_STONE_OF_ALL_TIME: return rc.act == 1 && rc.potionCount > 0;
        case EV_UNREST_SITE: return rc.hp * 10 <= rc.maxHp * 7;
        case EV_WATERLOGGED_SCRIPTORIUM: return rc.gold >= 55;
        case EV_ENDLESS_CONVEYOR: return rc.gold >= 120;
        case EV_TRASH_HEAP: return rc.hp > 5;
        case EV_RANWID_THE_ELDER: {
            // Act > 0, gold >= 100, at least one potion and one tradable relic.
            if (rc.act == 0 || rc.gold < 100 ||
                potion_occupied_count(rc.potions, rc.potionSlots) == 0)
                return false;
            for (int i = 0; i < rc.relicCount; ++i)
                if (relic_is_tradable(rc, i)) return true;
            return false;
        }
        case EV_RELIC_TRADER: {
            if (rc.act == 0) return false;
            int tradable = 0;
            for (int i = 0; i < rc.relicCount; ++i)
                tradable += relic_is_tradable(rc, i) ? 1 : 0;
            return tradable >= 5;
        }
        case EV_WOOD_CARVINGS: {
            // Native IsAllowed: any Basic, removable deck card.
            for (int i = 0; i < rc.deckCount; ++i)
                if (card_def(rc.deck[i].id).rarity == Rarity::BASIC &&
                    card_can_transform_from_deck(rc.deck[i]))
                    return true;
            return false;
        }
        case EV_FIELD_OF_MAN_SIZED_HOLES: {
            for (int i = 0; i < rc.deckCount; ++i)
                if (card_can_enchant(rc.deck[i], EnchantmentId::PERFECT_FIT))
                    return true;
            return false;
        }
        case EV_GRAVE_OF_THE_FORGOTTEN: {
            for (int i = 0; i < rc.deckCount; ++i)
                if (card_can_enchant(rc.deck[i], EnchantmentId::SOULS_POWER))
                    return true;
            return false;
        }
        case EV_FAKE_MERCHANT: {
            // IsAllowed: act > 0, single player, and gold >= 100 or a FoulPotion.
            if (rc.act < 1) return false;
            if (rc.gold >= 100) return true;
            for (int i = 0; i < rc.potionSlots; ++i)
                if (rc.potions[i] == static_cast<int>(PotionId::FOUL_POTION)) return true;
            return false;
        }
        case EV_SYMBIOTE: return rc.act > 0;
        case EV_PUNCH_OFF: return rc.floor >= 6;
        case EV_TEA_MASTER: return rc.act < 2 && rc.gold >= 150;
        case EV_ROUND_TEA_PARTY: return rc.hp >= 12;
        case EV_COLOSSAL_FLOWER: return rc.hp >= 19;
        case EV_WHISPERING_HOLLOW: return rc.gold >= 44;
        case EV_THE_LEGENDS_WERE_TRUE:
            return rc.act == 0 && rc.deckCount > 0 && rc.hp >= 10;
        case EV_DOLL_ROOM:
            return rc.act == 1;
        case EV_SLIPPERY_BRIDGE: {
            if (rc.floor <= 6) return false;
            for (int i = 0; i < rc.deckCount; ++i)
                if (!(card_def(rc.deck[i].id).flags & CF_ETERNAL)) return true;
            return false;
        }
        case EV_THE_FUTURE_OF_POTIONS:
            return potion_occupied_count(rc.potions, rc.potionSlots) >= 2;
        case EV_ZEN_WEAVER:
            return rc.gold >= 125;
        case EV_COLORFUL_PHILOSOPHERS: {
            // Native IsAllowed: every player has more than one unlocked
            // character card pool.
            CardPool pools[5];
            return native_unlocked_character_pools(rc, pools, 5) > 1;
        }
        case EV_MORPHIC_GROVE:
            return rc.gold >= 100 && transformable_deck_count(rc) >= 2;
        case EV_LUMINOUS_CHOIR: {
            // Native IsAllowed: gold >= 149 and the relic bag has stock.
            if (rc.gold < 149) return false;
            for (int slot = 0; slot < RELIC_BAG_SLOTS; ++slot)
                if (rc.playerRelicBag.counts[slot] > 0) return true;
            return false;
        }
        case EV_AMALGAMATOR: {
            // Native IsAllowed: >= 2 removable Basic Strike-tagged cards and
            // >= 2 removable Basic Defend-tagged cards.
            int strikes = 0, defends = 0;
            for (int i = 0; i < rc.deckCount; ++i) {
                const CardDef &d = card_def(rc.deck[i].id);
                if (d.flags & CF_ETERNAL) continue;
                if (d.rarity != Rarity::BASIC) continue;
                strikes += (d.flags & CF_STRIKE) != 0;
                defends += (d.flags & CF_DEFEND) != 0;
            }
            return strikes >= 2 && defends >= 2;
        }
        case EV_BYRDONIS_NEST:
            // Native IsAllowed: no player owns an event pet.
            return !run_has_event_pet(rc);
        case EV_SPIRALING_WHIRLPOOL:
            for (int i=0;i<rc.deckCount;++i)
                if (card_can_enchant(rc.deck[i],EnchantmentId::SPIRAL)) return true;
            return false;
        default: return true;
    }
}

bool event_applies_to_act(int id, int act) {
    const int a = EVENTS[id].act;
    if (a == -1) return true;   // shared
    if (a == 3) return true;    // ancient (never in the normal event bag)
    return a == act;
}

bool event_is_shared(int id) {
    switch (id) {
        case EV_DENSE_VEGETATION:
        case EV_FAKE_MERCHANT:
        case EV_JUNGLE_MAZE_ADVENTURE:
        case EV_THE_LANTERN_KEY:
        case EV_WAR_HISTORIAN_REPY:
        case EV_BATTLEWORN_DUMMY:
            return true;
        default:
            return false;
    }
}

bool event_transformable(CardId id) {
    switch (id) {
        case CardId::INVALID: case CardId::ASCENDERS_BANE: case CardId::BAD_LUCK:
        case CardId::CURSE_OF_THE_BELL: case CardId::ENTHRALLED:
        case CardId::FOLLY: case CardId::GREED:
            return false;
        default: return true;
    }
}

int transformable_deck_count(const RunContext &rc) {
    int count = 0;
    for (int i = 0; i < rc.deckCount; ++i) count += event_transformable(rc.deck[i].id);
    return count;
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

void transform_event_card(RunContext &rc, int idx, Rng &rng) {
    if (idx < 0 || idx >= rc.deckCount || !event_transformable(rc.deck[idx].id)) return;
    const CardId originalId = rc.deck[idx].id;
    const CardDef &original = card_def(originalId);
    CardPool pool = original.pool;
    // CardFactory.GetDefaultTransformationOptions: Quest cards and Event/
    // Ancient/Token rarities draw from the Colorless pool.
    if (original.type == CardType::QUEST || original.rarity == Rarity::EVENT ||
        original.rarity == Rarity::ANCIENT || original.rarity == Rarity::TOKEN)
        pool = CardPool::COLORLESS;
    const bool unrestrictedRarity = original.rarity == Rarity::STATUS || original.rarity == Rarity::CURSE;
    CardId candidates[static_cast<int>(CardId::COUNT)];
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardId id = static_cast<CardId>(i);
        if (!card_native_available(id)) continue;
        const CardDef &def = card_def(id);
        if (id == originalId || def.pool != pool || (def.flags & CF_MULTIPLAYER_ONLY)) continue;
        if (!unrestrictedRarity && def.rarity != Rarity::COMMON &&
            def.rarity != Rarity::UNCOMMON && def.rarity != Rarity::RARE) continue;
        candidates[n++] = id;
    }
    if (!n) return;
    native_sort_card_ids(candidates, n);
    Card replacement = rc.make_run_card(candidates[rng.next_int(0, n - 1)], false);
    const auto type = card_def(replacement.id).type;
    if ((type == CardType::ATTACK && run_has_relic(rc, RelicId::MOLTEN_EGG)) ||
        (type == CardType::SKILL && run_has_relic(rc, RelicId::TOXIC_EGG)) ||
        (type == CardType::POWER && run_has_relic(rc, RelicId::FROZEN_EGG)))
        card_apply_upgrade(replacement);
    remove_deck_index(rc, idx);
    rc.add_card_to_deck(replacement);
}

// CardCmd.TransformTo<T>: replace the chosen deck card with a specific card.
// Deck transforms remove the original and append the replacement (same as the
// random transform above).
void transform_event_card_to(RunContext &rc, int idx, CardId id) {
    if (idx < 0 || idx >= rc.deckCount || !event_transformable(rc.deck[idx].id)) return;
    Card replacement = rc.make_run_card(id, false);
    remove_deck_index(rc, idx);
    rc.add_card_to_deck(replacement);
}

void lose_hp(RunContext &rc, int amount) {
    run_take_noncombat_damage(rc, amount);
}

void lose_max_hp(RunContext &rc, int amount) {
    // Native damages down to the UNCLAMPED new max first; death-prevention
    // effects see the old maximum. SetMaxHp then clamps the surviving HP.
    const int newMax = rc.maxHp - amount;
    if (newMax < rc.hp) run_take_noncombat_damage(rc, rc.hp - newMax);
    rc.maxHp = std::max(1, newMax);
    rc.hp = std::min(rc.hp, rc.maxHp);
}

void heal(RunContext &rc, int amount) { rc.hp = std::min(rc.maxHp, rc.hp + std::max(0, amount)); }

void gain_max_hp(RunContext &rc, int amount) {
    rc.maxHp += amount;
    rc.hp += amount;
}

void queue_potion_event(RunContext &rc, PotionId potion) {
    int slot = 0;
    while (slot < rc.pendingPotionCount && rc.pendingPotions[slot]) ++slot;
    if (slot >= MAX_REWARD_POTIONS) throw std::logic_error("Event potion reward capacity exceeded");
    if (slot == rc.pendingPotionCount) ++rc.pendingPotionCount;
    rc.pendingPotions[slot] = static_cast<int>(potion);
    rc.pendingPotionReward = rc.pendingPotions[0];
    rc.deferredCustomRewards = true;
}

void add_random_potion_event(RunContext &rc, Rng &rng, bool uncommonOnly) {
    // Native concatenates Ironclad then shared pools and draws once uniformly.
    // This port's progress contract currently assumes these epochs unlocked.
    PotionId pool[static_cast<int>(PotionId::COUNT)];
    int count = 0;
    for (PotionId id : NATIVE_IRONCLAD_POTIONS)
        if (!uncommonOnly || potion_def(id).rarity == Rarity::UNCOMMON) pool[count++] = id;
    if (count) queue_potion_event(rc, pool[rng.next_int(0, count - 1)]);
}

void add_relic(RunContext &rc, RelicId id) { rc.add_relic(id); }

bool add_random_shared_relic(RunContext &rc, Rng &rng) {
    (void)rng;
    // RelicFactory.PullNextRelicFromFront(player): RollRarity from the
    // player's Rewards stream, then the front relic of the player's bag.
    const float roll = rc.playerRng[PRNG_REWARDS].next_float();
    const Rarity rarity = roll < 0.5f ? Rarity::COMMON
                       : roll < 0.83f ? Rarity::UNCOMMON : Rarity::RARE;
    return rc.add_relic(rc.pull_relic(rarity));
}

void finish_event(RunContext &rc) {
    rc.eventId = -1;
    rc.eventPage = 0;
    rc.eventChoiceCount = 0;
    rc.eventCardSelection = 0;
    rc.finish_room();
}

void set_page(RunContext &rc, int page, int options) {
    rc.eventPage = static_cast<std::int8_t>(page);
    rc.eventChoiceCount = static_cast<std::int8_t>(options);
}

void add_deck_card(RunContext &rc, CardId id, bool upgrade = false) {
    Card c = rc.make_run_card(id, upgrade);
    rc.add_card_to_deck(c);
}

// EndlessConveyor dish rotation (C# RollDish). eventData[1] counts grabs,
// eventData[2] is the last dish, eventData[3] the current dish.
enum EndlessDishId : int {
    DISH_NONE = 0,
    DISH_CAVIAR,
    DISH_SPICY_SNAPPY,
    DISH_JELLY_LIVER,
    DISH_FRIED_EEL,
    DISH_SUSPICIOUS_CONDIMENT,
    DISH_CLAM_ROLL,
    DISH_GOLDEN_FYSH,
    DISH_SEAPUNK_SALAD
};

void endless_conveyor_roll_dish(RunContext &rc) {
    ++rc.eventData[1];
    if (rc.eventData[1] % 5 == 0) {
        rc.eventData[2] = DISH_SEAPUNK_SALAD;
        rc.eventData[3] = DISH_SEAPUNK_SALAD;
        return;
    }
    struct DishWeight { int id; float weight; };
    DishWeight list[8];
    int n = 0;
    list[n++] = {DISH_CAVIAR, 6.0f};
    list[n++] = {DISH_SPICY_SNAPPY, 3.0f};
    list[n++] = {DISH_JELLY_LIVER, 3.0f};
    list[n++] = {DISH_FRIED_EEL, 3.0f};
    if (potion_occupied_count(rc.potions, rc.potionSlots) < rc.potionSlots)
        list[n++] = {DISH_SUSPICIOUS_CONDIMENT, 3.0f};
    if (rc.hp != rc.maxHp) list[n++] = {DISH_CLAM_ROLL, 6.0f};
    if (rc.eventData[1] > 1) list[n++] = {DISH_GOLDEN_FYSH, 1.0f};
    // Native RemoveAll(id == lastDishId).
    int m = 0;
    for (int i = 0; i < n; ++i)
        if (list[i].id != rc.eventData[2]) list[m++] = list[i];
    float total = 0.0f;
    for (int i = 0; i < m; ++i) total += list[i].weight;
    const float roll = rc.eventRng.next_float() * total;
    int chosen = m ? list[m - 1].id : DISH_CAVIAR;
    float upto = 0.0f;
    for (int i = 0; i < m; ++i) {
        upto += list[i].weight;
        if (roll < upto) { chosen = list[i].id; break; }
    }
    rc.eventData[3] = chosen;
    rc.eventData[2] = chosen;
}

void endless_conveyor_after_grab(RunContext &rc) {
    endless_conveyor_roll_dish(rc);
    set_page(rc, 1, 2);
}

void endless_conveyor_grab(RunContext &rc) {
    const int dish = rc.eventData[3];
    if (dish != DISH_GOLDEN_FYSH) rc.gold = std::max(0, rc.gold - 40);
    switch (dish) {
        case DISH_CAVIAR: gain_max_hp(rc, 4); break;
        case DISH_SPICY_SNAPPY: {
            const int idx = random_upgradable_index(rc, rc.eventRng);
            if (idx >= 0) card_apply_upgrade(rc.deck[idx]);
            break;
        }
        case DISH_JELLY_LIVER:
            // TransformToRandom runs after the selector resolves; pause here.
            rc.eventData[0] = 1;
            begin_event_card_selection(rc, 4);
            return;
        case DISH_FRIED_EEL: {
            Card card;
            if (make_noncombat_card_candidates(rc, &card, 1, CardPool::COLORLESS,
                                               false) == 1)
                rc.add_card_to_deck(card);
            break;
        }
        case DISH_SUSPICIOUS_CONDIMENT:
            add_random_potion_event(rc, rc.playerRng[PRNG_REWARDS], false);
            break;
        case DISH_CLAM_ROLL: heal(rc, 10); break;
        case DISH_GOLDEN_FYSH: run_gain_gold(rc, 75); break;
        case DISH_SEAPUNK_SALAD: add_deck_card(rc, CardId::FEEDING_FRENZY_CARD); break;
        default: break;
    }
    endless_conveyor_after_grab(rc);
}

int pick_one(const int *pool, int n, Rng &rng) {
    return n > 0 ? pool[rng.next_int(0, n - 1)] : 0;
}

// C# UnstableShuffle: Fisher-Yates from the end.
void shuffle_ints(int *a, int n, Rng &rng) {
    for (int i = n - 1; i > 0; --i) {
        const int j = rng.next_int(0, i);
        const int t = a[i];
        a[i] = a[j];
        a[j] = t;
    }
}

int deck_flag_count(const RunContext &rc, std::uint16_t flag) {
    int n = 0;
    for (int i = 0; i < rc.deckCount; ++i) n += card_has(rc.deck[i], flag) ? 1 : 0;
    return n;
}

// EnchantmentModel.CanEnchant for a deck card (Swift has no extra
// restrictions; Instinct is Attack-only; Goopy is Defend-tagged only).
int deck_enchantable(const RunContext &rc, EnchantmentId enchantment) {
    int n = 0;
    for (int i = 0; i < rc.deckCount; ++i)
        n += card_can_enchant(rc.deck[i], enchantment) ? 1 : 0;
    return n;
}

int swift_enchantable(const RunContext &rc) {
    return deck_enchantable(rc, EnchantmentId::SWIFT);
}

int instinct_enchantable(const RunContext &rc) {
    return deck_enchantable(rc, EnchantmentId::INSTINCT);
}

// CardModel.IsRemovable: every non-Eternal deck card.
int removable_cards(const RunContext &rc) {
    int n = 0;
    for (int i = 0; i < rc.deckCount; ++i) {
        const Card &c = rc.deck[i];
        if (c.id != CardId::INVALID && !(card_def(c.id).flags & CF_ETERNAL)) ++n;
    }
    return n;
}

// SlipperyBridge.GetNewRandomCard: non-Basic removable cards that are neither
// the current card nor previously skipped; if empty, all removable cards.
// The skipped set is a deck-index bitmask; indices >= 62 cannot be marked
// (documented ceiling; native keeps an unbounded HashSet).
bool slippery_pick_card(RunContext &rc, int excludeId, int &outIndex) {
    int cand[MAX_DECK];
    int n = 0;
    const int lo = rc.eventData[2];             // bits 0..30
    const int hi = rc.eventData[3];             // bits 31..61
    for (int i = 0; i < rc.deckCount; ++i) {
        const Card &c = rc.deck[i];
        const CardDef &d = card_def(c.id);
        if (d.rarity == Rarity::BASIC) continue;
        if (d.flags & CF_ETERNAL) continue;
        if (excludeId >= 0 && static_cast<int>(c.id) == excludeId) continue;
        const bool skipped = i < 31 ? ((lo >> i) & 1) != 0
                           : i < 62 ? ((hi >> (i - 31)) & 1) != 0 : false;
        if (skipped) continue;
        cand[n++] = i;
    }
    if (n == 0) {
        for (int i = 0; i < rc.deckCount; ++i) {
            if (card_def(rc.deck[i].id).flags & CF_ETERNAL) continue;
            cand[n++] = i;
        }
    }
    if (n == 0) return false;
    outIndex = cand[rc.eventRng.next_int(0, n - 1)];
    return true;
}

// RelicFactory.PullNextRelicFromFront(player): RollRarity from the rewards
// stream (50/33/17) then pull the front relic from the player's grab bag.
RelicId pull_next_relic_front(RunContext &rc) {
    const float roll = rc.playerRng[PRNG_REWARDS].next_float();
    const Rarity rarity = roll < 0.5f ? Rarity::COMMON
                        : roll < 0.83f ? Rarity::UNCOMMON : Rarity::RARE;
    return rc.pull_relic(rarity, false);
}

void slippery_mark_skipped(RunContext &rc, int deckIndex) {
    if (deckIndex < 0 || deckIndex >= 62) return;
    if (deckIndex < 31) rc.eventData[2] |= 1 << deckIndex;
    else rc.eventData[3] |= 1 << (deckIndex - 31);
}

// TheFutureOfPotions: three distinct cards of one rarity/type from the
// owner's pool under uniform odds, all upgraded. Native uses
// CardCreationOptions.ForNonCombatWithUniformOdds + CardReward(options, 3) and
// upgrades every generated card; the exact distinct-selection order is
// approximated by uniform index removal over CardId order.
int make_uniform_event_reward(RunContext &rc, Card *out, int want, Rarity rarity,
                              CardType type, Rng &rng, CardPool cardPool = CardPool::IRONCLAD,
                              bool anyType = false) {
    CardId pool[static_cast<int>(CardId::COUNT)];
    int n = 0;
    for (int id = 1; id < static_cast<int>(CardId::COUNT); ++id) {
        const CardDef &d = card_def(static_cast<CardId>(id));
        if (!card_native_available(d.id)) continue;
        if (d.pool != cardPool) continue;
        if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY)) continue;
        if (d.rarity != rarity || (!anyType && d.type != type)) continue;
        pool[n++] = d.id;
    }
    int made = 0;
    while (made < want && n > 0) {
        const int k = rng.next_int(0, n - 1);
        out[made++] = rc.make_run_card(pool[k], true);
        pool[k] = pool[--n];
    }
    return made;
}

// ScrollBoxes.CanGenerateBundles: >= 4 unlocked commons and >= 2 uncommons.
bool can_generate_bundles() {
    int common = 0;
    int uncommon = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        if (!card_native_available(static_cast<CardId>(i))) continue;
        const CardDef &d = card_def(static_cast<CardId>(i));
        if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY)) continue;
        if (d.rarity == Rarity::COMMON) ++common;
        else if (d.rarity == Rarity::UNCOMMON) ++uncommon;
    }
    return common >= 4 && uncommon >= 2;
}

// Generate the three relic offers for an Ancient, mirroring the C# event's
// GenerateInitialOptions. The chosen relic id is stored per option so the
// public observation exposes the actual choice.
void generate_ancient_options(RunContext &rc, int id) {
    Rng &rng = rc.eventRng;
    int opts[3] = {0, 0, 0};
    switch (id) {
        case EV_NEOW: {
            // Neow.GenerateInitialOptions (v0.111.0). CurseOptions is drawn
            // first, then conflicts are removed from PositiveOptions, then the
            // three single-relic bool pairs are appended in native order before
            // the IsAllowedAtNeow filter and UnstableShuffle.
            static const RelicId curseOptions[10] = {
                RelicId::CURSED_PEARL, RelicId::DOWSING_ROD, RelicId::HEFTY_TABLET,
                RelicId::LARGE_CAPSULE, RelicId::LEAFY_POULTICE, RelicId::NEOWS_BONES,
                RelicId::NEOWS_SACRIFICE, RelicId::PRECARIOUS_SHEARS,
                RelicId::SILKEN_TRESS, RelicId::SILVER_CRUCIBLE};
            RelicId curses[10];
            int cn = 0;
            for (const RelicId r : curseOptions)
                if (neow_relic_allowed(rc, r)) curses[cn++] = r;
            const RelicId curse = curses[rng.next_int(0, cn - 1)];
            static const RelicId positives[14] = {
                RelicId::ARCANE_SCROLL, RelicId::BOOMING_CONCH, RelicId::FISHING_ROD,
                RelicId::GOLDEN_PEARL, RelicId::KALEIDOSCOPE, RelicId::LEAD_PAPERWEIGHT,
                RelicId::LOST_COFFER, RelicId::MASSIVE_SCROLL, RelicId::NEOWS_TORMENT,
                RelicId::NEW_LEAF, RelicId::PHIAL_HOLSTER, RelicId::PRECISE_SCISSORS,
                RelicId::SCROLL_BOXES, RelicId::WINGED_BOOTS};
            RelicId list[20];
            int n = 0;
            for (const RelicId r : positives) {
                if (curse == RelicId::CURSED_PEARL && r == RelicId::GOLDEN_PEARL) continue;
                if (curse == RelicId::HEFTY_TABLET && r == RelicId::ARCANE_SCROLL) continue;
                if (curse == RelicId::LEAFY_POULTICE && r == RelicId::NEW_LEAF) continue;
                if (curse == RelicId::PRECARIOUS_SHEARS && r == RelicId::PRECISE_SCISSORS) continue;
                if (curse == RelicId::NEOWS_SACRIFICE &&
                    (r == RelicId::PHIAL_HOLSTER || r == RelicId::LOST_COFFER)) continue;
                list[n++] = r;
            }
            if (curse != RelicId::LARGE_CAPSULE)
                list[n++] = rng.next_bool() ? RelicId::LAVA_ROCK : RelicId::SMALL_CAPSULE;
            list[n++] = rng.next_bool() ? RelicId::NUTRITIOUS_OYSTER : RelicId::STONE_HUMIDIFIER;
            list[n++] = rng.next_bool() ? RelicId::NEOWS_TALISMAN : RelicId::POMANDER;
            int m = 0;
            for (int i = 0; i < n; ++i)
                if (neow_relic_allowed(rc, list[i])) list[m++] = list[i];
            for (int i = m - 1; i > 0; --i) {
                const int j = rng.next_int(0, i);
                const RelicId t = list[i]; list[i] = list[j]; list[j] = t;
            }
            opts[0] = static_cast<int>(list[0]);
            opts[1] = static_cast<int>(list[1]);
            opts[2] = static_cast<int>(curse);
            break;
        }
        case EV_OROBAS: {
            CardPool unlocked[5], other[5];
            const int unlockedN=native_unlocked_character_pools(rc,unlocked,5);
            int otherN=0;
            for(int i=0;i<unlockedN;++i) if(unlocked[i]!=rc.character) other[otherN++]=unlocked[i];
            rc.preparedSeaGlassPool=otherN?other[rng.next_int(0,otherN-1)]:rc.character;
            int first[3]={static_cast<int>(RelicId::ELECTRIC_SHRYMP),static_cast<int>(RelicId::GLASS_EYE),
                static_cast<int>(rng.next_float()<0.3333333f?RelicId::PRISMATIC_GEM:RelicId::SEA_GLASS)};
            opts[0]=pick_one(first,3,rng);
            const int second[4]={static_cast<int>(RelicId::ALCHEMICAL_COFFER),static_cast<int>(RelicId::DRIFTWOOD),
                static_cast<int>(RelicId::RADIANT_PEARL),static_cast<int>(RelicId::SAND_CASTLE)};
            opts[1]=pick_one(second,4,rng);
            int third[2], thirdN=0;
            for(int i=0;i<rc.relicCount;++i) if(relic_raw_rarity(static_cast<RelicId>(rc.relics[i]))==0) {
                third[thirdN++]=static_cast<int>(RelicId::TOUCH_OF_OROBAS); break;
            }
            // ArchaicTooth.SetupForPlayer keys: Bash/Neutralize/Unleash/
            // FallingStar/Dualcast (the character's starter card).
            for(int i=0;i<rc.deckCount;++i) {
                const CardId id=rc.deck[i].id;
                if(id==CardId::BASH||id==CardId::NEUTRALIZE||id==CardId::UNLEASH||
                   id==CardId::FALLING_STAR||id==CardId::DUALCAST) {
                    third[thirdN++]=static_cast<int>(RelicId::ARCHAIC_TOOTH); break;
                }
            }
            if (thirdN) {
                opts[2]=pick_one(third,thirdN,rng);
            } else {
                // OptionPool3 still contains the locked EventOption, so
                // NextItem consumes one draw.
                opts[2]=0;
                rng.next_int(0,0);
            }
            break;
        }
        case EV_PAEL: {
            static const int pool1[3] = {
                static_cast<int>(RelicId::PAELS_FLESH),
                static_cast<int>(RelicId::PAELS_HORN),
                static_cast<int>(RelicId::PAELS_TEARS)};
            opts[0] = pick_one(pool1, 3, rng);
            int list[8];
            int n = 0;
            list[n++] = static_cast<int>(RelicId::PAELS_WING);
            if (deck_enchantable(rc, EnchantmentId::GOOPY) >= 3) {
                list[n++] = static_cast<int>(RelicId::PAELS_CLAW);
            }
            if (removable_cards(rc) >= 5) {
                list[n++] = static_cast<int>(RelicId::PAELS_TOOTH);
            }
            // C# list.AddRange(list) duplicates the current entries.
            const int dup = n;
            for (int i = 0; i < dup; ++i) list[n++] = list[i];
            list[n++] = static_cast<int>(RelicId::PAELS_GROWTH);
            opts[1] = pick_one(list, n, rng);
            int list2[3];
            int n2 = 0;
            list2[n2++] = static_cast<int>(RelicId::PAELS_EYE);
            list2[n2++] = static_cast<int>(RelicId::PAELS_BLOOD);
            list2[n2++] = static_cast<int>(RelicId::PAELS_LEGION);  // no existing pet
            opts[2] = pick_one(list2, n2, rng);
            break;
        }
        case EV_TEZCATARA: {
            // OptionPool1: VeryHotCocoa, YummyCookie, plus NutritiousSoup when
            // the deck holds a Basic Strike-tagged card.
            int p1[3] = {static_cast<int>(RelicId::VERY_HOT_COCOA),
                         static_cast<int>(RelicId::YUMMY_COOKIE)};
            int p1n = 2;
            for (int i = 0; i < rc.deckCount; ++i) {
                const CardDef &d = card_def(rc.deck[i].id);
                if (d.rarity == Rarity::BASIC && (d.flags & CF_STRIKE)) {
                    p1[p1n++] = static_cast<int>(RelicId::NUTRITIOUS_SOUP);
                    break;
                }
            }
            static const int p2[3] = {static_cast<int>(RelicId::BIIIG_HUG),
                                      static_cast<int>(RelicId::STORYBOOK),
                                      static_cast<int>(RelicId::TOASTY_MITTENS)};
            static const int p3[4] = {static_cast<int>(RelicId::GOLDEN_COMPASS),
                                      static_cast<int>(RelicId::PUMPKIN_CANDLE),
                                      static_cast<int>(RelicId::TOY_BOX),
                                      static_cast<int>(RelicId::SEAL_OF_GOLD)};
            opts[0] = pick_one(p1, p1n, rng);
            opts[1] = pick_one(p2, 3, rng);
            opts[2] = pick_one(p3, 4, rng);
            break;
        }
        case EV_NONUPEIPE: {
            int list[10];
            int n = 0;
            static const int pool[9] = {
                static_cast<int>(RelicId::BLESSED_ANTLER),
                static_cast<int>(RelicId::BRILLIANT_SCARF),
                static_cast<int>(RelicId::DELICATE_FROND),
                static_cast<int>(RelicId::DIAMOND_DIADEM),
                static_cast<int>(RelicId::FUR_COAT),
                static_cast<int>(RelicId::GLITTER),
                static_cast<int>(RelicId::JEWELRY_BOX),
                static_cast<int>(RelicId::LOOMING_FRUIT),
                static_cast<int>(RelicId::SIGNET_RING)};
            for (int i = 0; i < 9; ++i) list[n++] = pool[i];
            if (swift_enchantable(rc) >= 4) {
                list[n++] = static_cast<int>(RelicId::BEAUTIFUL_BRACELET);
            }
            shuffle_ints(list, n, rng);
            opts[0] = list[0];
            opts[1] = list[1];
            opts[2] = list[2];
            break;
        }
        case EV_TANX: {
            int list[10];
            int n = 0;
            static const int pool[9] = {
                static_cast<int>(RelicId::CLAWS),
                static_cast<int>(RelicId::CROSSBOW),
                static_cast<int>(RelicId::IRON_CLUB),
                static_cast<int>(RelicId::MEAT_CLEAVER),
                static_cast<int>(RelicId::SAI),
                static_cast<int>(RelicId::SPIKED_GAUNTLETS),
                static_cast<int>(RelicId::TANXS_WHISTLE),
                static_cast<int>(RelicId::THROWING_AXE),
                static_cast<int>(RelicId::WAR_HAMMER)};
            for (int i = 0; i < 9; ++i) list[n++] = pool[i];
            if (instinct_enchantable(rc) >= 3) {
                list[n++] = static_cast<int>(RelicId::TRI_BOOMERANG);
            }
            shuffle_ints(list, n, rng);
            opts[0] = list[0];
            opts[1] = list[1];
            opts[2] = list[2];
            break;
        }
        case EV_VAKUU: {
            static const int p1[3] = {static_cast<int>(RelicId::BLOOD_SOAKED_ROSE),
                                      static_cast<int>(RelicId::WHISPERING_EARRING),
                                      static_cast<int>(RelicId::FIDDLE)};
            static const int p2[3] = {static_cast<int>(RelicId::PRESERVED_FOG),
                                      static_cast<int>(RelicId::SERE_TALON),
                                      static_cast<int>(RelicId::DISTINGUISHED_CAPE)};
            static const int p3[4] = {static_cast<int>(RelicId::CHOICES_PARADOX),
                                      static_cast<int>(RelicId::MUSIC_BOX),
                                      static_cast<int>(RelicId::LORDS_PARASOL),
                                      static_cast<int>(RelicId::JEWELED_MASK)};
            int a[3] = {p1[0], p1[1], p1[2]};
            int b[3] = {p2[0], p2[1], p2[2]};
            int c[4] = {p3[0], p3[1], p3[2], p3[3]};
            shuffle_ints(a, 3, rng);
            shuffle_ints(b, 3, rng);
            shuffle_ints(c, 4, rng);
            opts[0] = a[0];
            opts[1] = b[0];
            opts[2] = c[0];
            break;
        }
        case EV_DARV: {
            // One random relic from each valid boss-relic set whose filter
            // passes (C# Darv._validRelicSets).
            int list[11];
            int n = 0;
            static const int singles[7] = {
                static_cast<int>(RelicId::ASTROLABE),
                static_cast<int>(RelicId::BLACK_STAR),
                static_cast<int>(RelicId::CALLING_BELL),
                static_cast<int>(RelicId::EMPTY_CAGE),
                static_cast<int>(RelicId::PANDORAS_BOX),
                static_cast<int>(RelicId::RUNIC_PYRAMID),
                static_cast<int>(RelicId::SNECKO_EYE)};
            for (int i = 0; i < 7; ++i) { rng.next_int(0,0); list[n++] = singles[i]; }
            if(rc.act==1) for(auto id:{RelicId::ECTOPLASM,RelicId::SOZU}) {
                rng.next_int(0,0);list[n++]=static_cast<int>(id);
            }
            if(rc.act>=1) for(auto id:{RelicId::PHILOSOPHERS_STONE,RelicId::VELVET_CHOKER}) {
                rng.next_int(0,0);list[n++]=static_cast<int>(id);
            }
            shuffle_ints(list, n, rng);
            if (rng.next_bool()) {
                opts[0] = list[0];
                opts[1] = list[1];
                opts[2] = static_cast<int>(RelicId::DUSTY_TOME);
                rc.preparedDustyTomeCard=prepare_dusty_tome_card(rc);
            } else {
                opts[0] = list[0];
                opts[1] = list[1];
                opts[2] = list[2];
            }
            break;
        }
        default:
            break;
    }
    for (int i = 0; i < 3; ++i) rc.eventRelics[i] = opts[i];
    set_page(rc, 0, 3);
}

int option_count_for(const RunContext &rc) {
    switch (rc.eventId) {
        case EV_NEOW:
        case EV_DARV:
        case EV_OROBAS:
        case EV_PAEL:
        case EV_TEZCATARA:
        case EV_NONUPEIPE:
        case EV_TANX:
        case EV_VAKUU:
            return 3;
        case EV_DENSE_VEGETATION: return rc.eventPage == 0 ? 2 : 1;
        case EV_ABYSSAL_BATHS:
        case EV_TABLET_OF_TRUTH: return 2;
        case EV_WATERLOGGED_SCRIPTORIUM: return 3;
        case EV_WELCOME_TO_WONGOS: return 4;
        case EV_TEA_MASTER: return 3;
        case EV_DOLL_ROOM: return rc.eventPage == 0 ? 3 : (rc.eventPage == 1 ? 2 : 3);
        case EV_SLIPPERY_BRIDGE: return 2;
        case EV_THE_FUTURE_OF_POTIONS:
            return rc.eventPage == 0 ? rc.eventChoiceCount : 1;
        case EV_ZEN_WEAVER: return 3;
        case EV_ENDLESS_CONVEYOR:
        case EV_TRIAL: return 2;
        case EV_RANWID_THE_ELDER: return 3;
        case EV_RELIC_TRADER: return rc.eventData[3] > 0 ? rc.eventData[3] : 1;
        case EV_SELF_HELP_BOOK: return rc.eventChoiceCount > 0 ? rc.eventChoiceCount : 1;
        case EV_WOOD_CARVINGS: return 3;
        case EV_BATTLEWORN_DUMMY: return 3;
        case EV_THE_LANTERN_KEY: return rc.eventPage == 0 ? 2 : 1;
        case EV_WAR_HISTORIAN_REPY: return rc.eventPage == 0 ? 2 : 1;
        case EV_TINKER_TIME:
            return rc.eventPage == 0 ? 1 : 2;
        case EV_FAKE_MERCHANT:
            // Custom inventory UI; ProceedButton leaves the event.
            return 1;
        case EV_CRYSTAL_SPHERE:
            // Initial options, then the minigame takes over the screen.
            return rc.eventPage == 0 ? 2 : 0;
        case EV_COLORFUL_PHILOSOPHERS: return rc.eventChoiceCount;
        case EV_COLOSSAL_FLOWER:
        case EV_ROUND_TEA_PARTY: return rc.eventId == EV_ROUND_TEA_PARTY && rc.eventPage != 0 ? 1 : 2;
        default: return rc.eventPage == 0 ? 2 : 1;
    }
}

}  // namespace

const EventInfo *event_info(int id) {
    if (id < 0 || id >= EV_COUNT) return nullptr;
    return &EVENTS[id];
}

int event_count() { return EV_COUNT; }

bool neow_relic_allowed(const RunContext &rc, RelicId id) {
    switch (id) {
        case RelicId::KALEIDOSCOPE: {
            // Kaleidoscope.IsAllowedAtNeow: every character card pool unlocked.
            CardPool pools[5];
            return native_unlocked_character_pools(rc, pools, 5) == 5;
        }
        case RelicId::SCROLL_BOXES: return can_generate_bundles();
        // MassiveScroll.IsAllowed requires Players.Count > 1; this rules port
        // covers single-player runs only.
        case RelicId::MASSIVE_SCROLL: return false;
        default: return true;
    }
}

int neow_relic_options(const RunContext &rc, RelicId *out, int capacity, bool excludeBones) {
    // Neow.AllPossibleOptions declaration order: CurseOptions, PositiveOptions,
    // then the six standalone options.
    static const RelicId all[] = {
        RelicId::CURSED_PEARL, RelicId::DOWSING_ROD, RelicId::HEFTY_TABLET,
        RelicId::LARGE_CAPSULE, RelicId::LEAFY_POULTICE, RelicId::NEOWS_BONES,
        RelicId::NEOWS_SACRIFICE, RelicId::PRECARIOUS_SHEARS, RelicId::SILKEN_TRESS,
        RelicId::SILVER_CRUCIBLE,
        RelicId::ARCANE_SCROLL, RelicId::BOOMING_CONCH, RelicId::FISHING_ROD,
        RelicId::GOLDEN_PEARL, RelicId::KALEIDOSCOPE, RelicId::LEAD_PAPERWEIGHT,
        RelicId::LOST_COFFER, RelicId::MASSIVE_SCROLL, RelicId::NEOWS_TORMENT,
        RelicId::NEW_LEAF, RelicId::PHIAL_HOLSTER, RelicId::PRECISE_SCISSORS,
        RelicId::SCROLL_BOXES, RelicId::WINGED_BOOTS,
        RelicId::LAVA_ROCK, RelicId::NEOWS_TALISMAN, RelicId::NUTRITIOUS_OYSTER,
        RelicId::POMANDER, RelicId::SMALL_CAPSULE, RelicId::STONE_HUMIDIFIER};
    int n = 0;
    for (const RelicId id : all) {
        if (excludeBones && id == RelicId::NEOWS_BONES) continue;
        if (!neow_relic_allowed(rc, id)) continue;
        if (out && n < capacity) out[n] = id;
        ++n;
    }
    return n;
}

int event_war_historian_repy_id() { return EV_WAR_HISTORIAN_REPY; }

bool event_is_allowed(const RunContext &rc, int id) {
    return id >= 0 && id < EV_COUNT && event_allowed_now(rc, id);
}

bool event_allowed_by_profile(RunContentProfile profile, int id) {
    switch (profile) {
        case RunContentProfile::ORIGINAL:
            return true;
        case RunContentProfile::SINGLE_PLAYER_TRAINING:
            // CrystalSphere is an interactive divination mini-game outside the
            // current single-player simulation scope; its public observation
            // and policy support stay in place for the original profile.
            return id != EV_CRYSTAL_SPHERE;
    }
    return false;
}

namespace {
// ActModel.GenerateRooms concatenates AllEvents then ModelDb.AllSharedEvents in
// model declaration order (v0.111.0). The order matters: the bag is shuffled
// with the up-front RNG, so enum/alphabetical order picks different events for
// the same seed. Unsupported events stay in the native list but are omitted
// from the bag (documented coverage limitation) rather than substituted.
const char *const NATIVE_SHARED_EVENTS[] = {
    "BRAIN_LEECH", "CRYSTAL_SPHERE", "DOLL_ROOM", "FAKE_MERCHANT",
    "POTION_COURIER", "RANWID_THE_ELDER", "RELIC_TRADER", "ROOM_FULL_OF_CHEESE",
    "SELF_HELP_BOOK", "SLIPPERY_BRIDGE", "STONE_OF_ALL_TIME", "SYMBIOTE",
    "TEA_MASTER", "THE_FUTURE_OF_POTIONS", "THE_LEGENDS_WERE_TRUE",
    "THIS_OR_THAT", "WAR_HISTORIAN_REPY", "WELCOME_TO_WONGOS"
};
const char *const NATIVE_OVERGROWTH_EVENTS[] = {
    "AROMA_OF_CHAOS", "BYRDONIS_NEST", "DENSE_VEGETATION",
    "JUNGLE_MAZE_ADVENTURE", "LUMINOUS_CHOIR", "MORPHIC_GROVE",
    "SAPPHIRE_SEED", "SUNKEN_STATUE", "TABLET_OF_TRUTH", "UNREST_SITE",
    "WELLSPRING", "WHISPERING_HOLLOW", "WOOD_CARVINGS"
};
const char *const NATIVE_HIVE_EVENTS[] = {
    "AMALGAMATOR", "BUGSLAYER", "COLORFUL_PHILOSOPHERS", "COLOSSAL_FLOWER",
    "FIELD_OF_MAN_SIZED_HOLES", "INFESTED_AUTOMATON", "LOST_WISP",
    "SPIRIT_GRAFTER", "THE_LANTERN_KEY", "ZEN_WEAVER"
};
const char *const NATIVE_GLORY_EVENTS[] = {
    "BATTLEWORN_DUMMY", "GRAVE_OF_THE_FORGOTTEN", "HUNGRY_FOR_MUSHROOMS",
    "REFLECTIONS", "ROUND_TEA_PARTY", "TRIAL", "TINKER_TIME"
};
const char *const NATIVE_UNDERDOCKS_EVENTS[] = {
    "ABYSSAL_BATHS", "DROWNING_BEACON", "ENDLESS_CONVEYOR", "PUNCH_OFF",
    "SPIRALING_WHIRLPOOL", "SUNKEN_STATUE", "SUNKEN_TREASURY",
    "DOORS_OF_LIGHT_AND_DARK", "TRASH_HEAP", "WATERLOGGED_SCRIPTORIUM"
};

int append_named_events(const char *const *names, int count, int *out,
                        int maxOut, int start) {
    int n = start;
    for (int k = 0; k < count; ++k) {
        for (int id = 0; id < EV_COUNT; ++id) {
            if (std::strcmp(EVENTS[id].name, names[k]) != 0) continue;
            if (EVENTS[id].status == EventStatus::UNSUPPORTED) break;
            if (out && n < maxOut) out[n] = id;
            ++n;
            break;
        }
    }
    return n;
}
}  // namespace

int event_pool_for_act(int act, int *out, int maxOut) {
    if (act >= 0 && act <= 2)
        return event_pool_for_act_type(static_cast<ActType>(act), out, maxOut);
    // Compatibility accessor for act tags outside the three progression acts
    // (ancients are entered separately and never appear in the normal bag).
    int n = 0;
    for (int id = 0; id < EV_COUNT; ++id) {
        if (EVENTS[id].status == EventStatus::UNSUPPORTED) continue;
        if (EVENTS[id].act == 3) continue;
        if (!event_applies_to_act(id, act)) continue;
        if (out && n < maxOut) out[n] = id;
        ++n;
    }
    return n;
}

int event_pool_for_act_type(ActType actType, int *out, int maxOut) {
    const char *const *actNames = nullptr;
    int actCount = 0;
    switch (actType) {
        case ActType::OVERGROWTH:
            actNames = NATIVE_OVERGROWTH_EVENTS;
            actCount = static_cast<int>(std::size(NATIVE_OVERGROWTH_EVENTS));
            break;
        case ActType::HIVE:
            actNames = NATIVE_HIVE_EVENTS;
            actCount = static_cast<int>(std::size(NATIVE_HIVE_EVENTS));
            break;
        case ActType::GLORY:
            actNames = NATIVE_GLORY_EVENTS;
            actCount = static_cast<int>(std::size(NATIVE_GLORY_EVENTS));
            break;
        case ActType::UNDERDOCKS:
            actNames = NATIVE_UNDERDOCKS_EVENTS;
            actCount = static_cast<int>(std::size(NATIVE_UNDERDOCKS_EVENTS));
            break;
        default:
            return 0;
    }
    int n = append_named_events(actNames, actCount, out, maxOut, 0);
    n = append_named_events(NATIVE_SHARED_EVENTS,
                            static_cast<int>(std::size(NATIVE_SHARED_EVENTS)),
                            out, maxOut, n);
    return n;
}

int event_ancient_for_act(int act) {
    // Repository-level compatibility accessor; the per-run choice is stored in
    // RunContext::ancientId (see event_pick_ancient).
    return act == 1 ? EV_OROBAS : act == 2 ? EV_NONUPEIPE : EV_NEOW;
}

int event_ancient_for_act(const RunContext &rc) { return rc.ancientId; }

// RunManager.GenerateRooms assigns the shared ancients (Darv) to acts 2/3
// before any act's rooms are generated.
void event_plan_shared_ancients(RunContext &rc) {
    int available = rc.nativeProgress.darvUnlocked ? 1 : 0;
    for (int act = 1; act < MAX_ACTS; ++act) {
        const int count = rc.runRng[RNG_UP_FRONT].next_int(0, available);
        if (count > 0) {
            rc.sharedAncientInAct[act] = true;
            available = 0;
        }
    }
}

// ActModel.GenerateRooms end: NextItem(GetUnlockedAncients + shared subset).
int event_pick_ancient(RunContext &rc) {
    int pool[4];
    int n = 0;
    if (rc.act == 0) {
        if (rc.nativeProgress.neowUnlocked) pool[n++] = EV_NEOW;
    } else if (rc.act == 1) {
        if (rc.nativeProgress.orobasUnlocked) pool[n++] = EV_OROBAS;
        pool[n++] = EV_PAEL;
        pool[n++] = EV_TEZCATARA;
    } else {
        pool[n++] = EV_NONUPEIPE;
        pool[n++] = EV_TANX;
        pool[n++] = EV_VAKUU;
    }
    if (rc.act >= 1 && rc.sharedAncientInAct[rc.act]) pool[n++] = EV_DARV;
    return n ? pool[rc.runRng[RNG_UP_FRONT].next_int(0, n - 1)] : -1;
}

void event_begin(RunContext &rc, int eventId, bool ancient) {
    rc.eventId = static_cast<std::int8_t>(eventId);
    rc.eventPage = 0;
    rc.eventChoiceCount = 0;
    rc.eventCardSelection = 0;
    rc.eventCombat = false;
    rc.eventReturnPage = 0;
    for (int &v : rc.eventData) v = 0;
    for (int &v : rc.eventRelics) v = 0;
    if (eventId < 0 || eventId >= EV_COUNT) {
        finish_event(rc);
        return;
    }
    // Native non-shared events add the player slot; single-player slot is zero.
    rc.eventRng = Rng(rc.seed,
                      EVENTS[eventId].name);
    if (ancient) {
        // Neow starts by setting HP to zero before the Ancient heal.
        if (eventId == EV_NEOW) rc.hp = 0;
        const int missing = std::max(0, rc.maxHp - rc.hp);
        heal(rc, rc.ascension >= 2 ? missing * 4 / 5 : missing);
    }
    switch (eventId) {
        case EV_ABYSSAL_BATHS:
            rc.eventData[0] = 3; // next immersion damage, increases without a cap
            set_page(rc, 0, 2);
            break;
        case EV_SUNKEN_TREASURY:
            rc.eventData[0] = 60 + rc.eventRng.next_int(0, 15) - 8;
            rc.eventData[1] = 333 + rc.eventRng.next_int(0, 60) - 30;
            set_page(rc, 0, 2);
            break;
        case EV_DROWNING_BEACON:
        case EV_SPIRALING_WHIRLPOOL:
        case EV_DOORS_OF_LIGHT_AND_DARK:
            set_page(rc, 0, 2);
            break;
        case EV_WATERLOGGED_SCRIPTORIUM:
            set_page(rc, 0, 3);
            break;
        case EV_NEOW:
        case EV_DARV:
        case EV_OROBAS:
        case EV_PAEL:
        case EV_TEZCATARA:
        case EV_NONUPEIPE:
        case EV_TANX:
        case EV_VAKUU:
            (void)ancient;
            generate_ancient_options(rc, eventId);
            break;
        case EV_AROMA_OF_CHAOS:
        case EV_WELLSPRING:
        case EV_TABLET_OF_TRUTH:
        case EV_UNREST_SITE:
        case EV_SAPPHIRE_SEED:
        case EV_ROOM_FULL_OF_CHEESE:
        case EV_POTION_COURIER:
        case EV_BRAIN_LEECH:
            set_page(rc, 0, 3);
            break;
        case EV_STONE_OF_ALL_TIME:
            // GenerateInitialOptions: NextItem(Player.Potions) — non-null
            // slots in physical order (IsAllowed guarantees one exists).
            rc.eventData[0] =
                rc.potionCount ? rc.eventRng.next_int(0, rc.potionCount - 1) : -1;
            set_page(rc, 0, 3);
            break;
        case EV_HUNGRY_FOR_MUSHROOMS:
        case EV_REFLECTIONS:
        case EV_SPIRIT_GRAFTER:
        case EV_TEA_MASTER:
            set_page(rc, 0, 3);
            break;
        case EV_ROUND_TEA_PARTY:
        case EV_TRASH_HEAP:
        case EV_COLOSSAL_FLOWER:
        case EV_THE_LEGENDS_WERE_TRUE:
            set_page(rc, 0, 2);
            break;
        case EV_WHISPERING_HOLLOW:
            // C#: 35 + base.Rng.NextInt(-9, 10), upper bound exclusive.
            rc.eventData[0] = 35 + rc.eventRng.next_int(-9, 9);
            set_page(rc, 0, 2);
            break;
        case EV_JUNGLE_MAZE_ADVENTURE:
            // CalculateVars: solo 150 +/- 15, join forces 50 +/- 15; gold is
            // the decimal total truncated by PlayerCmd.GainGold.
            rc.eventData[0] = static_cast<int>(150.0f + rc.eventRng.next_float(-15.0f, 15.0f));
            rc.eventData[1] = static_cast<int>(50.0f + rc.eventRng.next_float(-15.0f, 15.0f));
            set_page(rc, 0, 2);
            break;
        case EV_INFESTED_AUTOMATON:
            set_page(rc, 0, 2);
            break;
        case EV_DOLL_ROOM:
            set_page(rc, 0, 3);
            break;
        case EV_ZEN_WEAVER:
            set_page(rc, 0, 3);
            break;
        case EV_AMALGAMATOR:
            set_page(rc, 0, 2);
            break;
        case EV_LUMINOUS_CHOIR:
            // C#: 149 - base.Rng.NextInt(0, 50), upper bound exclusive.
            rc.eventData[0] = 149 - rc.eventRng.next_int(0, 49);
            set_page(rc, 0, 2);
            break;
        case EV_MORPHIC_GROVE:
            set_page(rc, 0, 2);
            break;
        case EV_ENDLESS_CONVEYOR:
            // CalculateVars rolls the first dish before options are built.
            endless_conveyor_roll_dish(rc);
            set_page(rc, 0, 2);
            break;
        case EV_FIELD_OF_MAN_SIZED_HOLES:
            set_page(rc, 0, 2);
            break;
        case EV_GRAVE_OF_THE_FORGOTTEN: {
            bool target = false;
            for (int i = 0; i < rc.deckCount; ++i)
                if (card_can_enchant(rc.deck[i], EnchantmentId::SOULS_POWER))
                    target = true;
            rc.eventData[3] = target ? 1 : 0;
            set_page(rc, 0, 2);
            break;
        }
        case EV_SYMBIOTE: {
            bool target = false;
            for (int i = 0; i < rc.deckCount; ++i)
                if (card_can_enchant(rc.deck[i], EnchantmentId::CORRUPTED))
                    target = true;
            rc.eventData[3] = target ? 1 : 0;
            set_page(rc, 0, 2);
            break;
        }
        case EV_SELF_HELP_BOOK: {
            // GenerateInitialOptions only offers the three enchantments whose
            // type/CanEnchant has a deck target; with none, one SkipBook option.
            bool sharp = false, nimble = false, swift = false;
            for (int i = 0; i < rc.deckCount; ++i) {
                const CardType t = card_def(rc.deck[i].id).type;
                if (t == CardType::ATTACK &&
                    card_can_enchant(rc.deck[i], EnchantmentId::SHARP)) sharp = true;
                if (t == CardType::SKILL &&
                    card_can_enchant(rc.deck[i], EnchantmentId::NIMBLE)) nimble = true;
                if (t == CardType::POWER &&
                    card_can_enchant(rc.deck[i], EnchantmentId::SWIFT)) swift = true;
            }
            rc.eventData[0] = sharp ? 1 : 0;
            rc.eventData[1] = nimble ? 1 : 0;
            rc.eventData[2] = swift ? 1 : 0;
            set_page(rc, 0, (sharp || nimble || swift) ? 3 : 1);
            break;
        }
        case EV_WOOD_CARVINGS: {
            bool slither = false;
            for (int i = 0; i < rc.deckCount; ++i)
                if (card_can_enchant(rc.deck[i], EnchantmentId::SLITHER))
                    slither = true;
            rc.eventData[1] = slither ? 1 : 0;
            set_page(rc, 0, 3);
            break;
        }
        case EV_BATTLEWORN_DUMMY:
            // Three settings start the corresponding BattleFriend encounter.
            set_page(rc, 0, 3);
            break;
        case EV_THE_LANTERN_KEY:
            rc.eventData[0] = 100;  // GoldVar(100)
            set_page(rc, 0, 2);
            break;
        case EV_WAR_HISTORIAN_REPY:
            // eventData[0]: first unlock chosen (0 cage, 1 chest).
            set_page(rc, 0, 2);
            break;
        case EV_RANWID_THE_ELDER: {
            // GenerateInitialOptions picks one potion, then one tradable relic
            // from the event RNG (NextItem over occupied slots / owned order).
            const int occupied =
                potion_occupied_count(rc.potions, rc.potionSlots);
            int k = rc.eventRng.next_int(0, occupied - 1);
            int potionSlot = -1;
            for (int i = 0; i < rc.potionSlots && potionSlot < 0; ++i) {
                if (!rc.potions[i]) continue;
                if (k-- == 0) potionSlot = i;
            }
            rc.eventData[0] = potionSlot;
            int slots[MAX_RELICS];
            int n = 0;
            for (int i = 0; i < rc.relicCount; ++i)
                if (relic_is_tradable(rc, i)) slots[n++] = i;
            rc.eventData[1] =
                n > 0 ? slots[rc.eventRng.next_int(0, n - 1)] : -1;
            set_page(rc, 0, 3);
            break;
        }
        case EV_RELIC_TRADER: {
            int slots[MAX_RELICS];
            int n = 0;
            for (int i = 0; i < rc.relicCount; ++i)
                if (relic_is_tradable(rc, i)) slots[n++] = i;
            // StableShuffle: ModelId ordinal (category is uniform, entry is the
            // relic key) then UnstableShuffle, then take three.
            std::stable_sort(slots, slots + n, [&](int a, int b) {
                return std::strcmp(relic_def(static_cast<RelicId>(rc.relics[a])).key,
                                   relic_def(static_cast<RelicId>(rc.relics[b])).key) < 0;
            });
            shuffle_ints(slots, n, rc.eventRng);
            const int take = std::min(3, n);
            rc.eventData[3] = take;
            for (int j = 0; j < take; ++j) {
                rc.eventData[j] = slots[j];
                rc.eventRelics[j] =
                    static_cast<int>(pull_next_relic_front(rc));
            }
            set_page(rc, 0, take > 0 ? take : 1);
            break;
        }
        case EV_BUGSLAYER:
        case EV_TRIAL:
            set_page(rc, 0, 2);
            break;
        case EV_PUNCH_OFF:
            // CalculateVars rolls flavour gold 91..99 from the event RNG.
            // C#: base.Rng.NextInt(91, 99), upper bound exclusive.
            rc.eventData[0] = rc.eventRng.next_int(91, 98);
            set_page(rc, 0, 2);
            break;
        case EV_COLORFUL_PHILOSOPHERS: {
            // CardPoolColorOrder: Necrobinder, Ironclad, Regent, Silent,
            // Defect; the owner's pool and locked pools are skipped.
            static const CardPool order[5] = {CardPool::NECROBINDER, CardPool::IRONCLAD,
                                              CardPool::REGENT, CardPool::SILENT,
                                              CardPool::DEFECT};
            CardPool list[5];
            int n = 0;
            for (CardPool pool : order) {
                if (pool == rc.character) continue;
                if (!native_card_pool_unlocked(rc, pool)) continue;
                list[n++] = pool;
            }
            // Mathf.Min(3, list.Count) with random removals until it fits.
            while (n > 3) {
                const int k = rc.eventRng.next_int(0, n - 1);
                for (int i = k + 1; i < n; ++i) list[i - 1] = list[i];
                --n;
            }
            for (int i = 0; i < 3; ++i)
                rc.eventData[i] = i < n ? static_cast<int>(list[i]) : 0;
            rc.eventData[3] = n;
            set_page(rc, 0, n);
            break;
        }
        case EV_SLIPPERY_BRIDGE: {
            int idx = -1;
            if (slippery_pick_card(rc, -1, idx))
                rc.eventData[0] = rc.deck[idx].uid;
            else
                rc.eventData[0] = 0;
            rc.eventData[1] = 0;
            rc.eventData[2] = 0;
            rc.eventData[3] = 0;
            set_page(rc, 0, 2);
            break;
        }
        case EV_THE_FUTURE_OF_POTIONS: {
            // PotionToCardType is built lazily over every occupied slot, in
            // slot order: [Attack, Skill, Power], Power removed for Common.
            int occupied[MAX_POTIONS];
            int count = 0;
            int packedTypes = 0;
            int place = 1;
            for (int slot = 0; slot < rc.potionSlots; ++slot) {
                if (rc.potions[slot] == 0) continue;
                const PotionDef &pd = potion_def(static_cast<PotionId>(rc.potions[slot]));
                const int choices = pd.rarity == Rarity::COMMON ? 2 : 3;
                const int type = rc.eventRng.next_int(0, choices - 1);
                if (count < 3) packedTypes += type * place;
                if (count < MAX_POTIONS) occupied[count] = slot;
                ++count;
                place *= 3;
            }
            for (int i = 0; i < 3; ++i)
                rc.eventData[i] = i < count && i < 3 ? occupied[i] : 0;
            rc.eventData[3] = packedTypes;
            set_page(rc, 0, count < 3 ? count : 3);
            break;
        }
        case EV_BYRDONIS_NEST:
            set_page(rc, 0, 2);
            break;
        case EV_WELCOME_TO_WONGOS:
            // GenerateInitialOptions pulls the FeaturedItem immediately with an
            // explicit rarity (no Rewards roll) and a shop-only filter.
            rc.eventData[0] = static_cast<int>(
                rc.pull_relic(Rarity::RARE, false, false, nullptr, 0, true));
            set_page(rc, 0, 4);
            break;
        case EV_FAKE_MERCHANT: {
            // BeforeEventStarted: UnstableShuffle the nine fake relics with the
            // event Rng, take six, and price each from PlayerRng.Shops
            // (MerchantCost 50 * NextFloat(0.85, 1.15), rounded to even).
            static const RelicId stock[9] = {
                RelicId::FAKE_ANCHOR, RelicId::FAKE_BLOOD_VIAL,
                RelicId::FAKE_HAPPY_FLOWER, RelicId::FAKE_LEES_WAFFLE,
                RelicId::FAKE_MANGO, RelicId::FAKE_ORICHALCUM,
                RelicId::FAKE_SNECKO_EYE, RelicId::FAKE_STRIKE_DUMMY,
                RelicId::FAKE_VENERABLE_TEA_SET};
            int ids[9];
            for (int i = 0; i < 9; ++i) ids[i] = static_cast<int>(stock[i]);
            rc.eventRng.shuffle(ids, 9);
            for (int i = 0; i < RunContext::FAKE_MERCHANT_RELICS; ++i) {
                rc.fakeMerchantRelics[i] = ids[i];
                rc.fakeMerchantPrices[i] = static_cast<int>(std::nearbyint(
                    50.0f * rc.playerRng[PRNG_SHOPS].next_float(0.85f, 1.15f)));
                rc.fakeMerchantSold[i] = false;
            }
            set_page(rc, 0, 1);
            break;
        }
        case EV_TINKER_TIME:
            set_page(rc, 0, 1);
            break;
        case EV_CRYSTAL_SPHERE:
            // CalculateVars: UncoverFutureCost = 50 + base.Rng.NextInt(1, 50).
            rc.eventData[0] = 50 + rc.eventRng.next_int(1, 49);
            set_page(rc, 0, 2);
            break;
        case EV_DENSE_VEGETATION:
        case EV_SUNKEN_STATUE:
        case EV_THIS_OR_THAT:
        case EV_LOST_WISP:
            // CalculateVars runs before either option is chosen in native.
            rc.eventData[0] = eventId == EV_DENSE_VEGETATION ? rc.eventRng.next_int(61, 99)
                : eventId == EV_SUNKEN_STATUE ? 111 + rc.eventRng.next_int(-10, 10)
                : eventId == EV_THIS_OR_THAT ? rc.eventRng.next_int(41, 68)
                : 60 + rc.eventRng.next_int(-15, 15);
            set_page(rc, 0, 2);
            break;
        default:
            finish_event(rc);
            break;
    }
    rc.screen = RunScreen::EVENT;
}

int event_option_count(const RunContext &rc) {
    if (rc.screen != RunScreen::EVENT || rc.eventId < 0 || rc.eventCardSelection) return 0;
    return option_count_for(rc);
}

bool event_option_available(const RunContext &rc, int option) {
    if (option < 0 || option >= event_option_count(rc)) return false;
    int additions = 0;
    int removals = 0;
    bool grantsRelic = false;
    switch (rc.eventId) {
        case EV_SUNKEN_TREASURY: additions = option == 1 ? 1 : 0; break;
        case EV_DROWNING_BEACON:
            grantsRelic = option == 1;
            if (option == 0 && rc.pendingPotionCount >= MAX_REWARD_POTIONS) return false;
            break;
        case EV_WATERLOGGED_SCRIPTORIUM:
            if (option > 0 && rc.gold < (option == 1 ? 55 : 99)) return false;
            break;
        case EV_DOORS_OF_LIGHT_AND_DARK:
            if (option == 1 && !can_begin_deck_relic_choice(rc, 6, 1)) return false;
            break;
        case EV_AROMA_OF_CHAOS:
            if (option == 0 && transformable_deck_count(rc) > 0) {
                additions = 1;
                removals = 1;
            }
            break;
        case EV_WELLSPRING:
            if (option == 0 && rc.pendingPotionCount >= MAX_REWARD_POTIONS) return false;
            if (option == 1) { additions = 1; removals = transformable_deck_count(rc) > 0 ? 1 : 0; }
            break;
        case EV_UNREST_SITE:
            additions = option == 0 ? 1 : 0;
            grantsRelic = option == 1;
            break;
        case EV_THIS_OR_THAT:
            if (option == 1) { additions = 1; grantsRelic = true; }
            break;
        case EV_ROOM_FULL_OF_CHEESE:
            additions = option == 0 ? 2 : 0;
            grantsRelic = option == 1;
            break;
        case EV_POTION_COURIER:
            if (rc.pendingPotionCount > MAX_REWARD_POTIONS - (option == 0 ? 3 : 1)) return false;
            break;
        case EV_BRAIN_LEECH: additions = 1; break;
        case EV_REFLECTIONS: additions = option == 1 ? rc.deckCount + 1 : 0; break;
        case EV_SPIRIT_GRAFTER: additions = option == 0 ? 1 : 0; break;
        case EV_LOST_WISP:
            if (option == 0) { additions = 1; grantsRelic = true; }
            break;
        case EV_SUNKEN_STATUE: grantsRelic = option == 0; break;
        case EV_WELCOME_TO_WONGOS: grantsRelic = option <= 2; break;
        case EV_HUNGRY_FOR_MUSHROOMS: grantsRelic = true; break;
        case EV_TEA_MASTER: grantsRelic = true; break;
        case EV_DOLL_ROOM: grantsRelic = true; break;
        case EV_ZEN_WEAVER:
            // Locked options exist in the UI but are not selectable.
            if (option == 1 && rc.gold < 125) return false;
            if (option == 2 && rc.gold < 250) return false;
            break;
        case EV_LUMINOUS_CHOIR:
            if (option == 1) {
                if (rc.relicCount >= MAX_RELICS) return false;
                return rc.gold >= rc.eventData[0];
            }
            additions = 1;  // SporeMind after the two removals
            break;
        case EV_ENDLESS_CONVEYOR:
            // GenerateGrabSomethingOffTheBeltOption locks the option whenever
            // gold < 40, including for the free Golden Fysh dish.
            if (option == 0 && rc.gold < 40) return false;
            break;
        case EV_SELF_HELP_BOOK:
            // A single SkipBook option is always available; otherwise the
            // unavailable enchantment options are locked in place.
            if (rc.eventChoiceCount == 1) break;
            if (rc.eventData[option] == 0) return false;
            break;
        case EV_WOOD_CARVINGS:
            if (option == 1 && rc.eventData[1] == 0) return false;
            break;
        case EV_GRAVE_OF_THE_FORGOTTEN:
        case EV_SYMBIOTE:
            if (option == 0 && rc.eventData[3] == 0) return false;
            break;
        case EV_TINKER_TIME:
            // RiderChosen adds the MadScience card to the deck.
            if (rc.eventPage == 2) additions = 1;
            break;
        case EV_CRYSTAL_SPHERE:
            if (option == 0 && rc.gold < rc.eventData[0]) return false;
            if (option == 1) additions = 1;  // Debt
            break;
        case EV_NEOW: case EV_DARV: case EV_OROBAS: case EV_PAEL:
        case EV_TEZCATARA: case EV_NONUPEIPE: case EV_TANX: case EV_VAKUU:
            // A locked OptionPool_3 entry is a disabled EventOption (null
            // onChosen) in native, not a selectable no-op.
            if (rc.eventRelics[option] == static_cast<int>(RelicId::INVALID))
                return false;
            // Dusty Tome adds an Ancient card to the deck; a full deck cannot
            // hold it, so the bounded engine disables the option instead of
            // obtaining a relic with no effect.
            if (rc.eventRelics[option] == static_cast<int>(RelicId::DUSTY_TOME) &&
                rc.deckCount + (run_has_relic(rc, RelicId::BING_BONG) ? 2 : 1) > MAX_DECK)
                return false;
            if (rc.eventId == EV_NEOW) {
                const RelicId pick = static_cast<RelicId>(rc.eventRelics[option]);
                if (pick == RelicId::DOWSING_ROD || pick == RelicId::NEOWS_SACRIFICE) additions = 1;
                else if (pick == RelicId::HEFTY_TABLET) additions = 2;
                else if (pick == RelicId::NEOWS_BONES) additions = 1;
            }
            grantsRelic = true;
            break;
        default: break;
    }
    const int copies = run_has_relic(rc, RelicId::BING_BONG) ? 2 : 1;
    if (additions * copies > MAX_DECK - rc.deckCount + removals) return false;
    if (grantsRelic && rc.relicCount >= MAX_RELICS) return false;
    if (grantsRelic && rc.eventRelics[option] == static_cast<int>(RelicId::SCROLL_BOXES) &&
        !can_generate_scroll_boxes(rc)) return false;
    if (rc.eventId == EV_WELCOME_TO_WONGOS && option <= 2) {
        return rc.gold >= 100 * (option + 1);
    }
    if (rc.eventId == EV_TEA_MASTER) {
        if (option == 0) return rc.gold >= 50;
        if (option == 1) return rc.gold >= 150;
    }
    if (rc.eventId == EV_STONE_OF_ALL_TIME && option == 0) {
        return rc.eventData[0] >= 0 && rc.eventData[0] < rc.potionCount;
    }
    if (rc.eventId == EV_STONE_OF_ALL_TIME && option == 1) {
        for (int i = 0; i < rc.deckCount; ++i)
            if (card_can_enchant(rc.deck[i], EnchantmentId::VIGOROUS)) return true;
        return false;
    }
    return true;
}

bool event_card_selectable(const RunContext &rc, int index) {
    const bool eventActive = rc.screen == RunScreen::EVENT ||
        (rc.screen == RunScreen::REWARDS && rc.rewardResumeScreen == RunScreen::EVENT);
    if (!eventActive || index < 0 || index >= rc.deckCount) return false;
    if (rc.eventCardSelection == 1) return card_upgradable(rc.deck[index]);
    if (rc.eventCardSelection == 2) return card_can_enchant(rc.deck[index], EnchantmentId::SOWN);
    if (rc.eventCardSelection == 3) return card_can_enchant(rc.deck[index], EnchantmentId::VIGOROUS);
    if (rc.eventCardSelection == 4) {
        if (rc.eventId == EV_WOOD_CARVINGS)
            return card_def(rc.deck[index].id).rarity == Rarity::BASIC &&
                   card_can_transform_from_deck(rc.deck[index]);
        return card_can_transform_from_deck(rc.deck[index]);
    }
    if (rc.eventCardSelection == 7)
        return card_def(rc.deck[index].id).type == CardType::ATTACK &&
               card_can_enchant(rc.deck[index], EnchantmentId::SHARP);
    if (rc.eventCardSelection == 8)
        return card_def(rc.deck[index].id).type == CardType::SKILL &&
               card_can_enchant(rc.deck[index], EnchantmentId::NIMBLE);
    if (rc.eventCardSelection == 9)
        return card_def(rc.deck[index].id).type == CardType::POWER &&
               card_can_enchant(rc.deck[index], EnchantmentId::SWIFT);
    if (rc.eventCardSelection == 10)
        return card_can_enchant(rc.deck[index], EnchantmentId::SLITHER);
    if (rc.eventCardSelection == 11)
        return card_can_enchant(rc.deck[index],
                                static_cast<EnchantmentId>(rc.eventData[2]));
    if (rc.eventCardSelection == 6) {
        const CardDef &d = card_def(rc.deck[index].id);
        if (rc.eventId == EV_AMALGAMATOR) {
            // Native IsValid: Basic rarity and the requested tag.
            if (d.rarity != Rarity::BASIC || (d.flags & CF_ETERNAL)) return false;
            return rc.eventData[0] == 1 ? (d.flags & CF_STRIKE) != 0
                                        : (d.flags & CF_DEFEND) != 0;
        }
        return !(d.flags & CF_ETERNAL);
    }
    if (rc.eventCardSelection == 5) return card_upgradable(rc.deck[index]);
    return false;
}

bool event_card_selection_valid(const RunContext &rc) {
    if (!rc.eventCardSelection) return true;
    if ((rc.screen != RunScreen::EVENT &&
         !(rc.screen == RunScreen::REWARDS && rc.rewardResumeScreen == RunScreen::EVENT)) ||
        (rc.eventCardSelection <= 2 && rc.eventId != EV_SAPPHIRE_SEED &&
         !(rc.eventId == EV_TRIAL && rc.eventCardSelection == 1)) ||
        (rc.eventCardSelection == 3 && rc.eventId != EV_STONE_OF_ALL_TIME) ||
        (rc.eventCardSelection == 4 && rc.eventId != EV_AROMA_OF_CHAOS &&
         rc.eventId != EV_WHISPERING_HOLLOW &&
         rc.eventId != EV_MORPHIC_GROVE &&
         rc.eventId != EV_ENDLESS_CONVEYOR &&
         rc.eventId != EV_WOOD_CARVINGS &&
         rc.eventId != EV_TRIAL) ||
        (rc.eventCardSelection == 5 && rc.eventId != EV_AROMA_OF_CHAOS && rc.eventId != EV_SPIRIT_GRAFTER) ||
        (rc.eventCardSelection == 6 && rc.eventId != EV_WELLSPRING &&
         rc.eventId != EV_ZEN_WEAVER && rc.eventId != EV_AMALGAMATOR &&
         rc.eventId != EV_LUMINOUS_CHOIR) ||
        ((rc.eventCardSelection == 7 || rc.eventCardSelection == 8 ||
          rc.eventCardSelection == 9) && rc.eventId != EV_SELF_HELP_BOOK) ||
        (rc.eventCardSelection == 10 && rc.eventId != EV_WOOD_CARVINGS) ||
        (rc.eventCardSelection == 11 && rc.eventId != EV_FIELD_OF_MAN_SIZED_HOLES &&
         rc.eventId != EV_GRAVE_OF_THE_FORGOTTEN &&
         rc.eventId != EV_SYMBIOTE) ||
        rc.eventCardSelection > 11) return false;
    int count = 0;
    for (int i = 0; i < rc.deckCount; ++i) count += event_card_selectable(rc, i) ? 1 : 0;
    return count > 1;
}

void event_finish_card_grid(RunContext &rc) { finish_event(rc); }

bool event_can_remove_potions(const RunContext &rc) {
    return rc.screen != RunScreen::EVENT ||
           (rc.eventId != EV_STONE_OF_ALL_TIME &&
            rc.eventId != EV_RANWID_THE_ELDER);
}

bool event_select_card(RunContext &rc, int index);

static void finish_event_card_selection(RunContext &rc) {
    if (rc.eventId == EV_FIELD_OF_MAN_SIZED_HOLES &&
        rc.eventCardSelection == 6 && rc.eventData[1] > 0) {
        --rc.eventData[1];
        if (rc.eventData[1] > 0) {
            int count = 0, only = -1;
            for (int i = 0; i < rc.deckCount; ++i)
                if (event_card_selectable(rc, i)) { ++count; only = i; }
            if (count > 1) return;
            if (count == 1) { event_select_card(rc, only); return; }
        }
        add_deck_card(rc, CardId::NORMALITY);
        finish_event(rc);
        return;
    }
    if (rc.eventId == EV_SYMBIOTE && rc.eventCardSelection == 4 &&
        rc.eventData[1] > 0) {
        --rc.eventData[1];
        if (rc.eventData[1] > 0) {
            int count = 0, only = -1;
            for (int i = 0; i < rc.deckCount; ++i)
                if (event_card_selectable(rc, i)) { ++count; only = i; }
            if (count > 1) return;
            if (count == 1) { event_select_card(rc, only); return; }
        }
        finish_event(rc);
        return;
    }
    if (rc.eventId == EV_TRIAL &&
        (rc.eventCardSelection == 1 || rc.eventCardSelection == 4) &&
        rc.eventData[1] > 0) {
        --rc.eventData[1];
        if (rc.eventData[1] > 0) {
            int count = 0, only = -1;
            for (int i = 0; i < rc.deckCount; ++i)
                if (event_card_selectable(rc, i)) { ++count; only = i; }
            if (count > 1) return;
            if (count == 1) { event_select_card(rc, only); return; }
        }
        finish_event(rc);
        return;
    }
    if (rc.eventId == EV_ENDLESS_CONVEYOR && rc.eventCardSelection == 4 &&
        rc.eventData[0] == 1) {
        rc.eventData[0] = 0;
        endless_conveyor_after_grab(rc);
        return;
    }
    if (rc.eventId == EV_AMALGAMATOR && rc.eventCardSelection == 6 && rc.eventData[1] > 0) {
        --rc.eventData[1];
        if (rc.eventData[1] > 0) {
            int count = 0, only = -1;
            for (int i = 0; i < rc.deckCount; ++i)
                if (event_card_selectable(rc, i)) { ++count; only = i; }
            if (count > 1) return;
            if (count == 1) { event_select_card(rc, only); return; }
        }
        add_deck_card(rc, rc.eventData[0] == 1 ? CardId::ULTIMATE_STRIKE
                                               : CardId::ULTIMATE_DEFEND);
        finish_event(rc);
        return;
    }
    if (rc.eventId == EV_MORPHIC_GROVE && rc.eventCardSelection == 4 && rc.eventData[0] > 0) {
        --rc.eventData[0];
        if (rc.eventData[0] > 0) {
            int count = 0, only = -1;
            for (int i = 0; i < rc.deckCount; ++i)
                if (event_card_selectable(rc, i)) { ++count; only = i; }
            if (count > 1) return;
            if (count == 1) { event_select_card(rc, only); return; }
        }
        finish_event(rc);
        return;
    }
    if (rc.eventId == EV_LUMINOUS_CHOIR && rc.eventCardSelection == 6 && rc.eventData[1] > 0) {
        --rc.eventData[1];
        if (rc.eventData[1] > 0) {
            int count = 0, only = -1;
            for (int i = 0; i < rc.deckCount; ++i)
                if (event_card_selectable(rc, i)) { ++count; only = i; }
            if (count > 1) return;
            if (count == 1) { event_select_card(rc, only); return; }
        }
        add_deck_card(rc, CardId::SPORE_MIND);
        finish_event(rc);
        return;
    }
    if (rc.eventId == EV_ZEN_WEAVER && rc.eventCardSelection == 6 && rc.eventData[1] > 0) {
        --rc.eventData[1];
        if (rc.eventData[1] > 0) {
            int count = 0, only = -1;
            for (int i = 0; i < rc.deckCount; ++i)
                if (event_card_selectable(rc, i)) { ++count; only = i; }
            if (count > 1) return;  // keep the open selector
            if (count == 1) { event_select_card(rc, only); return; }
        }
        rc.gold = std::max(0, rc.gold - rc.eventData[0]);
        finish_event(rc);
        return;
    }
    if (rc.eventId == EV_STONE_OF_ALL_TIME) rc.eventRng.next_int(0, 99);
    if (rc.eventId == EV_SPIRIT_GRAFTER) lose_hp(rc, 10);
    if (rc.eventId == EV_WELLSPRING) add_deck_card(rc, CardId::GUILTY);
    if (rc.eventId == EV_WHISPERING_HOLLOW) lose_hp(rc, 9);
    finish_event(rc);
}

bool event_select_card(RunContext &rc, int index) {
    if (rc.screen != RunScreen::EVENT || !event_card_selectable(rc, index)) return false;
    if (rc.eventCardSelection == 1 || rc.eventCardSelection == 5) card_apply_upgrade(rc.deck[index]);
    else if (rc.eventCardSelection == 2) card_apply_enchantment(rc.deck[index], EnchantmentId::SOWN, 1);
    else if (rc.eventCardSelection == 3) card_apply_enchantment(rc.deck[index], EnchantmentId::VIGOROUS, 8);
    else if (rc.eventCardSelection == 4) {
        if (rc.eventId == EV_WOOD_CARVINGS)
            transform_event_card_to(rc, index, static_cast<CardId>(rc.eventData[0]));
        else
            transform_event_card(rc, index, rc.eventRng);
    } else if (rc.eventCardSelection == 7)
        card_apply_enchantment(rc.deck[index], EnchantmentId::SHARP, 2);
    else if (rc.eventCardSelection == 8)
        card_apply_enchantment(rc.deck[index], EnchantmentId::NIMBLE, 2);
    else if (rc.eventCardSelection == 9)
        card_apply_enchantment(rc.deck[index], EnchantmentId::SWIFT, 2);
    else if (rc.eventCardSelection == 10)
        card_apply_enchantment(rc.deck[index], EnchantmentId::SLITHER, 1);
    else if (rc.eventCardSelection == 11)
        card_apply_enchantment(rc.deck[index],
                               static_cast<EnchantmentId>(rc.eventData[2]), 1);
    else if (rc.eventCardSelection == 6) remove_deck_index(rc, index);
    finish_event_card_selection(rc);
    return true;
}

static void begin_event_card_selection(RunContext &rc, int kind) {
    rc.eventCardSelection = static_cast<std::uint8_t>(kind);
    int count = 0, only = -1;
    for (int i = 0; i < rc.deckCount; ++i) {
        if (event_card_selectable(rc, i)) { ++count; only = i; }
    }
    if (count == 1) event_select_card(rc, only);
    else if (count == 0) finish_event_card_selection(rc);
}

// WarHistorianRepy.RemoveFirstLanternKey: mark the quest complete and remove
// one LanternKey from the deck (single-player removal path).
static bool war_historian_remove_lantern_key(RunContext &rc) {
    for (int i = 0; i < rc.deckCount; ++i) {
        if (rc.deck[i].id != CardId::LANTERN_KEY) continue;
        for (int j = i; j + 1 < rc.deckCount; ++j) rc.deck[j] = rc.deck[j + 1];
        rc.deck[--rc.deckCount] = Card{};
        return true;
    }
    return false;
}

static bool war_historian_has_lantern_key(const RunContext &rc) {
    for (int i = 0; i < rc.deckCount; ++i)
        if (rc.deck[i].id == CardId::LANTERN_KEY) return true;
    return false;
}

// UnlockCage: obtain the HistoryCourse relic.
static void war_historian_unlock_cage(RunContext &rc) {
    add_relic(rc, RelicId::HISTORY_COURSE);
}

// UnlockChest: two PotionRewards then two RelicRewards in native order.
static void war_historian_unlock_chest(RunContext &rc) {
    for (int i = 0; i < 2; ++i)
        add_random_potion_event(rc, rc.playerRng[PRNG_REWARDS], false);
    rc.queue_random_relic_reward(rc.playerRng[PRNG_REWARDS]);
    rc.queue_random_relic_reward(rc.playerRng[PRNG_REWARDS]);
}

bool event_choose(RunContext &rc, int option) {
    if (rc.screen != RunScreen::EVENT || rc.eventId < 0) return false;
    if (!event_option_available(rc, option)) return false;
    const int id = rc.eventId;
    Rng &rng = rc.eventRng;
    switch (id) {
        case EV_ABYSSAL_BATHS:
            if (option == 0) {
                gain_max_hp(rc, 2);
                run_take_noncombat_damage(rc, rc.eventData[0]++);
                if (rc.hp > 0) set_page(rc, 1, 2);
            } else {
                if (rc.eventPage == 0) heal(rc, 10);
                finish_event(rc);
            }
            return true;
        case EV_DROWNING_BEACON:
            if (option == 0) {
                // Offer a real reward; a full belt does not silently consume it.
                rc.pendingPotions[rc.pendingPotionCount++] = static_cast<int>(PotionId::GLOWWATER_POTION);
                rc.pendingPotionReward = rc.pendingPotions[0];
                rc.deferredCustomRewards = true;
            } else {
                lose_max_hp(rc, 13);
                rc.add_relic(RelicId::FRESNEL_LENS);
            }
            finish_event(rc);
            return true;
        case EV_SUNKEN_TREASURY:
            run_gain_gold(rc, rc.eventData[option]);
            if (option == 1) add_deck_card(rc, CardId::GREED);
            finish_event(rc);
            return true;
        case EV_DOORS_OF_LIGHT_AND_DARK:
            if (option == 0) {
                int candidates[MAX_DECK], count=0;
                for (int i=0;i<rc.deckCount;++i)
                    if (card_upgradable(rc.deck[i])) candidates[count++]=i;
                native_sort_card_indices(rc,candidates,count);
                rng.shuffle(candidates,count);
                for (int i=0;i<std::min(2,count);++i) card_apply_upgrade(rc.deck[candidates[i]]);
            } else if (!begin_deck_relic_choice(rc, 6, 1)) return false;
            finish_event(rc);
            return true;
        case EV_SPIRALING_WHIRLPOOL:
            if (option == 0) {
                if (!begin_deck_relic_choice(rc, 11, 1)) return false;
            } else heal(rc, rc.maxHp * 33 / 100);
            finish_event(rc);
            return true;
        case EV_WATERLOGGED_SCRIPTORIUM:
            if (option == 0) gain_max_hp(rc, 6);
            else {
                if (!begin_deck_relic_choice(rc, 12, option == 1 ? 1 : 2)) return false;
                rc.gold -= option == 1 ? 55 : 99;
                rc.mawBankPurchased = true;
            }
            finish_event(rc);
            return true;
        case EV_NEOW:
        case EV_DARV:
        case EV_OROBAS:
        case EV_PAEL:
        case EV_TEZCATARA:
        case EV_NONUPEIPE:
        case EV_TANX:
        case EV_VAKUU: {
            const RelicId pick = static_cast<RelicId>(rc.eventRelics[option]);
            if (pick != RelicId::INVALID) add_relic(rc, pick);
            finish_event(rc);
            return true;
        }
        case EV_AROMA_OF_CHAOS: {
            begin_event_card_selection(rc, option == 0 ? 4 : 5);
            return true;
        }
        case EV_DENSE_VEGETATION: {
            if (rc.eventPage == 0 && option == 0) {
                lose_hp(rc, 8);
                run_gain_gold(rc, rc.eventData[0]);
                finish_event(rc);
                return true;
            }
            if (rc.eventPage == 0 && option == 1) {
                int amount = rc.maxHp * 3 / 10;
                if (run_has_relic(rc, RelicId::REGAL_PILLOW)) amount += 15;
                heal(rc, amount);
                if (run_has_relic(rc, RelicId::STONE_HUMIDIFIER)) {
                    rc.maxHp += 5;
                    rc.hp += 5;
                }
                rc.queue_rest_site_rewards();
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
                run_gain_gold(rc, rc.eventData[0]);
                lose_hp(rc, 7);
            }
            finish_event(rc);
            return true;
        }
        case EV_WELLSPRING: {
            if (option == 0) {
                add_random_potion_event(rc, rc.playerRng[PRNG_REWARDS], false);
            } else {
                begin_event_card_selection(rc, 6);
                return true;
            }
            finish_event(rc);
            return true;
        }
        case EV_TABLET_OF_TRUTH: {
            if (option == 1) {
                if (rc.eventPage == 0) heal(rc, 20);
                finish_event(rc);
                return true;
            }
            int count = rc.eventData[0];
            int cost = 3;
            if (count == 1) cost = 6;
            else if (count == 2) cost = 12;
            else if (count == 3) cost = 24;
            else if (count >= 4) cost = std::max(1, rc.maxHp - 1);
            if (cost >= rc.maxHp) {
                // This branch explicitly kills after reducing the maximum to 1.
                lose_max_hp(rc, rc.maxHp - 1);
                // Kill bypasses damage mitigation, but still permits Fairy/Tail.
                run_take_noncombat_damage(rc, rc.hp + (run_has_relic(rc, RelicId::TUNGSTEN_ROD) ? 1 : 0));
                return true;
            }
            lose_max_hp(rc, cost);
            if (rc.screen == RunScreen::RUN_OVER) return true;
            ++rc.eventData[0];
            if (count == 4) {
                for (int i = 0; i < rc.deckCount; ++i) {
                    if (card_upgradable(rc.deck[i])) card_apply_upgrade(rc.deck[i]);
                }
            } else {
                const int idx = random_upgradable_index(rc, rng);
                if (idx >= 0) card_apply_upgrade(rc.deck[idx]);
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
                add_deck_card(rc, CardId::POOR_SLEEP);
            } else {
                lose_max_hp(rc, 8);
                if (rc.screen == RunScreen::RUN_OVER) return true;
                add_random_shared_relic(rc, rng);
            }
            finish_event(rc);
            return true;
        }
        case EV_SAPPHIRE_SEED: {
            if (option == 0) {
                heal(rc, 9);
                begin_event_card_selection(rc, 1);
            } else {
                begin_event_card_selection(rc, 2);
            }
            return true;
        }
        case EV_BYRDONIS_NEST:
            // EAT: GainMaxHp(7). TAKE: add the Byrdonis Egg to the deck.
            if (option == 0) gain_max_hp(rc, 7);
            else add_deck_card(rc, CardId::BYRDONIS_EGG);
            finish_event(rc);
            return true;
        case EV_BUGSLAYER:
            // EXTERMINATION adds Exterminate; SQUASH adds Squash.
            add_deck_card(rc, option == 0 ? CardId::EXTERMINATE
                                          : CardId::SQUASH);
            finish_event(rc);
            return true;
        case EV_ENDLESS_CONVEYOR:
            if (option == 1) {
                // ObserveChef upgrades one random upgradable card; Leave just
                // ends the event.
                if (rc.eventPage == 0) {
                    const int idx = random_upgradable_index(rc, rc.eventRng);
                    if (idx >= 0) card_apply_upgrade(rc.deck[idx]);
                }
                finish_event(rc);
                return true;
            }
            endless_conveyor_grab(rc);
            return true;
        case EV_THE_LANTERN_KEY:
            if (rc.eventPage == 0 && option == 0) {
                run_gain_gold(rc, rc.eventData[0]);
                finish_event(rc);
                return true;
            }
            if (rc.eventPage == 0) {
                set_page(rc, 1, 1);
                return true;
            }
            // Fight: the LanternKey special card is offered after the combat.
            rc.eventCombat = true;
            rc.eventReturnPage = -1;
            rc.combatIsElite = false;
            rc.combatIsBoss = false;
            rc.begin_combat(Encounter::SETUP_MYSTERIOUS_KNIGHT);
            return true;
        case EV_WAR_HISTORIAN_REPY: {
            if (rc.eventPage == 0) {
                const int first = option;  // 0 cage, 1 chest
                rc.eventData[0] = first;
                war_historian_remove_lantern_key(rc);
                if (first == 0) war_historian_unlock_cage(rc);
                else war_historian_unlock_chest(rc);
                if (war_historian_has_lantern_key(rc)) {
                    // ShouldGetSecondReward: a second LanternKey in a
                    // single-player deck unlocks the other side.
                    set_page(rc, 1, 1);
                } else {
                    finish_event(rc);
                }
                return true;
            }
            // Second page: the remaining unlock, then the event finishes.
            if (rc.eventData[0] == 0) war_historian_unlock_chest(rc);
            else war_historian_unlock_cage(rc);
            finish_event(rc);
            return true;
        }
        case EV_BATTLEWORN_DUMMY:
            // Setting1/2/3 enter the V1/V2/V3 encounter without exiting the
            // event; Resume runs after combat.
            rc.eventData[0] = option + 1;
            rc.eventCombat = true;
            rc.eventReturnPage = 0;
            rc.combatIsElite = false;
            rc.combatIsBoss = false;
            rc.begin_combat(static_cast<Encounter>(
                static_cast<int>(Encounter::SETUP_BATTLEWORN_DUMMY_V1) + option));
            return true;
        case EV_PUNCH_OFF:
            if (rc.eventPage == 0 && option == 0) {
                // Nab: Injury curse and a relic reward.
                add_deck_card(rc, CardId::INJURY);
                rc.queue_random_relic_reward(rc.playerRng[PRNG_REWARDS]);
                rc.deferredCustomRewards = true;
                finish_event(rc);
                return true;
            }
            if (rc.eventPage == 0) {
                set_page(rc, 1, 1);
                return true;
            }
            // Fight: reward population is deferred to the post-combat reward
            // screen (eventData[1] relic, [2] potion), matching native
            // RelicReward/PotionReward.Populate timing.
            rc.eventData[1] = 1;
            rc.eventData[2] = 1;
            rc.eventCombat = true;
            rc.eventReturnPage = -1;
            rc.combatIsElite = false;
            rc.combatIsBoss = false;
            rc.begin_combat(Encounter::SETUP_PUNCH_OFF);
            return true;
        case EV_FIELD_OF_MAN_SIZED_HOLES:
            if (option == 0) {
                rc.eventData[1] = 2;  // remove two cards
                begin_event_card_selection(rc, 6);
            } else {
                rc.eventData[2] = static_cast<int>(EnchantmentId::PERFECT_FIT);
                begin_event_card_selection(rc, 11);
            }
            return true;
        case EV_GRAVE_OF_THE_FORGOTTEN:
            if (option == 0) {
                add_deck_card(rc, CardId::DECAY);
                rc.eventData[2] = static_cast<int>(EnchantmentId::SOULS_POWER);
                begin_event_card_selection(rc, 11);
            } else {
                add_relic(rc, RelicId::FORGOTTEN_SOUL);
                finish_event(rc);
            }
            return true;
        case EV_SYMBIOTE:
            if (option == 0) {
                rc.eventData[2] = static_cast<int>(EnchantmentId::CORRUPTED);
                begin_event_card_selection(rc, 11);
            } else {
                rc.eventData[1] = 2;  // transform two cards
                begin_event_card_selection(rc, 4);
            }
            return true;
        case EV_SELF_HELP_BOOK:
            if (rc.eventChoiceCount == 1) {
                finish_event(rc);
                return true;
            }
            begin_event_card_selection(rc, 7 + option);
            return true;
        case EV_WOOD_CARVINGS:
            if (option == 0) {
                rc.eventData[0] = static_cast<int>(CardId::PECK);
                begin_event_card_selection(rc, 4);
            } else if (option == 1) {
                begin_event_card_selection(rc, 10);
            } else {
                rc.eventData[0] = static_cast<int>(CardId::TORIC_TOUGHNESS);
                begin_event_card_selection(rc, 4);
            }
            return true;
        case EV_RANWID_THE_ELDER:
            if (option == 0) {
                potion_remove_at(rc.potions, rc.potionSlots, rc.potionCount,
                                 rc.eventData[0]);
                add_relic(rc, pull_next_relic_front(rc));
            } else if (option == 1) {
                rc.gold = std::max(0, rc.gold - 100);
                add_relic(rc, pull_next_relic_front(rc));
            } else {
                rc.remove_relic(rc.eventData[1]);
                add_relic(rc, pull_next_relic_front(rc));
                add_relic(rc, pull_next_relic_front(rc));
            }
            finish_event(rc);
            return true;
        case EV_RELIC_TRADER:
            if (option >= 0 && option < rc.eventData[3]) {
                rc.remove_relic(rc.eventData[option]);
                add_relic(rc,
                          static_cast<RelicId>(rc.eventRelics[option]));
            }
            finish_event(rc);
            return true;
        case EV_TRIAL: {
            if (rc.eventPage == 0) {
                if (option == 0) {
                    rc.eventData[0] = rc.eventRng.next_int(0, 2);
                    set_page(rc, 1, 2);
                } else {
                    set_page(rc, 2, 2);
                }
                return true;
            }
            if (rc.eventPage == 2) {
                if (option == 0) {
                    rc.eventData[0] = rc.eventRng.next_int(0, 2);
                    set_page(rc, 1, 2);
                } else {
                    // DoubleDown abandons the run.
                    rc.won = false;
                    rc.screen = RunScreen::RUN_OVER;
                }
                return true;
            }
            // Trial page: 0 merchant, 1 noble, 2 nondescript.
            const int trial = rc.eventData[0];
            rc.eventData[1] = 0;
            if (trial == 0) {
                if (option == 0) {
                    add_deck_card(rc, CardId::REGRET);
                    add_relic(rc, pull_next_relic_front(rc));
                    add_relic(rc, pull_next_relic_front(rc));
                    finish_event(rc);
                } else {
                    add_deck_card(rc, CardId::SHAME);
                    rc.eventData[1] = 2;
                    begin_event_card_selection(rc, 1);
                }
                return true;
            }
            if (trial == 1) {
                if (option == 0) {
                    heal(rc, 10);
                } else {
                    add_deck_card(rc, CardId::REGRET);
                    run_gain_gold(rc, 300);
                }
                finish_event(rc);
                return true;
            }
            add_deck_card(rc, CardId::DOUBT);
            if (option == 0) {
                int madeRewards = 0;
                for (int r = 0; r < 2; ++r) {
                    int slot = 0;
                    while (slot < MAX_CARD_REWARDS &&
                           (rc.rewardCardPending[slot] ||
                            slot == rc.activeCardReward))
                        ++slot;
                    if (slot >= MAX_CARD_REWARDS) break;
                    Card cards[3];
                    const int made = make_noncombat_card_candidates(
                        rc, cards, 3, rc.character, false);
                    if (!made) break;
                    for (int i = 0; i < made; ++i)
                        rc.rewardCards[slot][i] = cards[i];
                    rc.rewardCardCounts[slot] = made;
                    rc.rewardCardPending[slot] = true;
                    ++madeRewards;
                }
                if (madeRewards) {
                    rc.pendingCardReward = true;
                    rc.deferredCustomRewards = true;
                }
                finish_event(rc);
            } else {
                rc.eventData[1] = 2;
                begin_event_card_selection(rc, 4);
            }
            return true;
        }
        case EV_ROUND_TEA_PARTY:
            // Glory: Enjoy Tea obtains RoyalPoison and heals to full; Pick
            // Fight leads to 11 unblockable/unpowered damage + a front relic.
            if (rc.eventPage == 0 && option == 0) {
                add_relic(rc, RelicId::ROYAL_POISON);
                heal(rc, rc.maxHp - rc.hp);
                finish_event(rc);
            } else if (rc.eventPage == 0) {
                set_page(rc, 1, 1);
            } else {
                lose_hp(rc, 11);
                const float roll = rc.playerRng[PRNG_REWARDS].next_float();
                const Rarity rarity = roll < 0.5f ? Rarity::COMMON
                    : roll < 0.83f ? Rarity::UNCOMMON : Rarity::RARE;
                const RelicId relic = rc.pull_relic(rarity);
                if (relic != RelicId::INVALID) add_relic(rc, relic);
                finish_event(rc);
            }
            return true;
        case EV_COLOSSAL_FLOWER: {
            // Hive: prize costs 35/75/135; each Reach Deeper deals 5/6/7
            // unblockable/unpowered damage. At depth 2 the second option
            // instead deals 7 and obtains Pollinous Core.
            static const int costs[3] = {35, 75, 135};
            static const int damage[3] = {5, 6, 7};
            const int digs = std::min<int>(rc.eventPage, 2);
            if (option == 0) {
                run_gain_gold(rc, costs[digs]);
                finish_event(rc);
            } else {
                lose_hp(rc, damage[digs]);
                if (digs < 2) {
                    set_page(rc, digs + 1, 2);
                } else {
                    add_relic(rc, RelicId::POLLINOUS_CORE);
                    finish_event(rc);
                }
            }
            return true;
        }
        case EV_TRASH_HEAP:
            // Underdocks: Dive In (8 unblockable/unpowered, random relic from
            // the fixed five) or Grab (100 gold + random card from the fixed
            // ten). One event-RNG NextItem call in either branch.
            if (option == 0) {
                static const RelicId relics[5] = {
                    RelicId::DARKSTONE_PERIAPT, RelicId::DREAM_CATCHER,
                    RelicId::HAND_DRILL, RelicId::MAW_BANK, RelicId::THE_BOOT};
                lose_hp(rc, 8);
                add_relic(rc, relics[rng.next_int(0, 4)]);
            } else {
                static const CardId cards[10] = {
                    CardId::CALTROPS, CardId::CLASH, CardId::DISTRACTION,
                    CardId::DUAL_WIELD, CardId::ENTRENCH, CardId::HELLO_WORLD_CARD,
                    CardId::OUTMANEUVER, CardId::REBOUND, CardId::RIP_AND_TEAR,
                    CardId::STACK};
                run_gain_gold(rc, 100);
                add_deck_card(rc, cards[rng.next_int(0, 9)]);
            }
            finish_event(rc);
            return true;
        case EV_WHISPERING_HOLLOW:
            if (option == 0) {
                rc.gold -= rc.eventData[0];
                add_random_potion_event(rc, rc.playerRng[PRNG_REWARDS], false);
                add_random_potion_event(rc, rc.playerRng[PRNG_REWARDS], false);
                finish_event(rc);
            } else {
                // Hug: transform one card, then 9 unblockable/unpowered damage
                // applied by finish_event_card_selection.
                begin_event_card_selection(rc, 4);
            }
            return true;
        case EV_JUNGLE_MAZE_ADVENTURE:
            if (option == 0) {
                // Solo quest: 18 unblockable/unpowered damage, then gold.
                lose_hp(rc, 18);
                if (rc.screen == RunScreen::RUN_OVER) return true;
                run_gain_gold(rc, rc.eventData[0]);
            } else {
                run_gain_gold(rc, rc.eventData[1]);
            }
            finish_event(rc);
            return true;
        case EV_INFESTED_AUTOMATON: {
            // STUDY: one Power; TOUCH_CORE: one canonical 0-cost non-X card.
            Card card;
            const NoncombatCardFilter filter = option == 0
                ? NoncombatCardFilter::POWER : NoncombatCardFilter::ZERO_COST;
            if (make_noncombat_card_candidates(rc, &card, 1, rc.character,
                                               false, filter) == 1)
                rc.add_card_to_deck(card);
            finish_event(rc);
            return true;
        }
        case EV_DOLL_ROOM: {
            static const RelicId dolls[3] = {
                RelicId::DAUGHTER_OF_THE_WIND, RelicId::MR_STRUGGLES,
                RelicId::BING_BONG};
            if (rc.eventPage == 0) {
                if (option == 0) {
                    // NextItem(_dolls) over the declaration order.
                    add_relic(rc, dolls[rc.eventRng.next_int(0, 2)]);
                    finish_event(rc);
                } else {
                    lose_hp(rc, option == 1 ? 5 : 15);
                    if (rc.screen == RunScreen::RUN_OVER) return true;
                    // StableShuffle sorts by ModelId (BingBong, Daughter,
                    // MrStruggles) before the native Fisher-Yates shuffle.
                    int order[3] = {2, 0, 1};
                    shuffle_ints(order, 3, rc.eventRng);
                    for (int i = 0; i < 3; ++i)
                        rc.eventData[i] = static_cast<int>(dolls[order[i]]);
                    set_page(rc, option == 1 ? 1 : 2, option == 1 ? 2 : 3);
                }
            } else {
                add_relic(rc, static_cast<RelicId>(rc.eventData[option]));
                finish_event(rc);
            }
            return true;
        }
        case EV_SLIPPERY_BRIDGE: {
            if (option == 0) {
                int idx = -1;
                for (int i = 0; i < rc.deckCount; ++i)
                    if (rc.deck[i].uid == rc.eventData[0]) { idx = i; break; }
                if (idx >= 0) remove_deck_index(rc, idx);
                finish_event(rc);
            } else {
                const int hold = rc.eventData[1];
                lose_hp(rc, 3 + hold);
                if (rc.screen == RunScreen::RUN_OVER) return true;
                int cur = -1;
                for (int i = 0; i < rc.deckCount; ++i)
                    if (rc.deck[i].uid == rc.eventData[0]) { cur = i; break; }
                if (cur >= 0) slippery_mark_skipped(rc, cur);
                const int excludeId = cur >= 0 ? static_cast<int>(rc.deck[cur].id) : -1;
                rc.eventData[1] = hold + 1;
                int next = -1;
                rc.eventData[0] = slippery_pick_card(rc, excludeId, next)
                    ? static_cast<int>(rc.deck[next].uid) : 0;
                set_page(rc, rc.eventPage + 1, 2);
            }
            return true;
        }
        case EV_THE_FUTURE_OF_POTIONS: {
            if (option < 0 || option >= 3) return false;
            const int slot = rc.eventData[option];
            if (slot < 0 || slot >= rc.potionSlots || rc.potions[slot] == 0) return false;
            const PotionDef &pd = potion_def(static_cast<PotionId>(rc.potions[slot]));
            // Native GetCardRarity: Rare/Event -> Rare, Uncommon -> Uncommon,
            // Common/Token -> Common. Obtainable special potions are Event.
            const Rarity rarity = pd.rarity == Rarity::COMMON ? Rarity::COMMON
                                : pd.rarity == Rarity::UNCOMMON ? Rarity::UNCOMMON
                                : Rarity::RARE;
            int packed = rc.eventData[3];
            for (int i = 0; i < option; ++i) packed /= 3;
            const int typeIndex = packed % 3;
            const CardType type = typeIndex == 0 ? CardType::ATTACK
                                : typeIndex == 1 ? CardType::SKILL : CardType::POWER;
            potion_remove_at(rc.potions, rc.potionSlots, rc.potionCount, slot);
            Card generated[3];
            const int made = make_uniform_event_reward(
                rc, generated, 3, rarity, type, rc.playerRng[PRNG_REWARDS], rc.character);
            if (made > 0) {
                int reward = 0;
                while (reward < MAX_CARD_REWARDS &&
                       (rc.rewardCardPending[reward] || reward == rc.activeCardReward))
                    ++reward;
                if (reward < MAX_CARD_REWARDS) {
                    for (int i = 0; i < made; ++i)
                        rc.rewardCards[reward][i] = generated[i];
                    rc.rewardCardCounts[reward] = made;
                    rc.rewardCardPending[reward] = true;
                    rc.pendingCardReward = true;
                    rc.deferredCustomRewards = true;
                }
            }
            finish_event(rc);
            return true;
        }
        case EV_COLORFUL_PHILOSOPHERS: {
            const int count = rc.eventData[3];
            if (option < 0 || option >= count) return false;
            const CardPool pool = static_cast<CardPool>(rc.eventData[option]);
            static const Rarity rarities[3] = {Rarity::COMMON, Rarity::UNCOMMON,
                                               Rarity::RARE};
            int madeRewards = 0;
            for (int r = 0; r < 3; ++r) {
                int slot = 0;
                while (slot < MAX_CARD_REWARDS &&
                       (rc.rewardCardPending[slot] || slot == rc.activeCardReward))
                    ++slot;
                if (slot >= MAX_CARD_REWARDS) break;
                Card cards[3];
                const int made = make_uniform_event_reward(
                    rc, cards, 3, rarities[r], CardType::ATTACK,
                    rc.playerRng[PRNG_REWARDS], pool, true);
                if (!made) continue;
                for (int i = 0; i < made; ++i) rc.rewardCards[slot][i] = cards[i];
                rc.rewardCardCounts[slot] = made;
                rc.rewardCardPending[slot] = true;
                ++madeRewards;
            }
            if (madeRewards) {
                rc.pendingCardReward = true;
                rc.deferredCustomRewards = true;
            }
            finish_event(rc);
            return true;
        }
        case EV_MORPHIC_GROVE:
            if (option == 0) {
                rc.gold = 0;
                rc.eventData[0] = 2;  // two transformations
                begin_event_card_selection(rc, 4);
            } else {
                gain_max_hp(rc, 5);
                finish_event(rc);
            }
            return true;
        case EV_LUMINOUS_CHOIR:
            if (option == 0) {
                rc.eventData[1] = 2;  // two removals, then SporeMind
                begin_event_card_selection(rc, 6);
            } else {
                rc.gold -= rc.eventData[0];
                add_relic(rc, pull_next_relic_front(rc));
                finish_event(rc);
            }
            return true;
        case EV_AMALGAMATOR:
            rc.eventData[0] = option == 0 ? 1 : 2;  // 1 Strike, 2 Defend
            rc.eventData[1] = 2;
            begin_event_card_selection(rc, 6);
            return true;
        case EV_ZEN_WEAVER:
            if (option == 0) {
                rc.gold = std::max(0, rc.gold - 50);
                add_deck_card(rc, CardId::ENLIGHTENMENT);
                add_deck_card(rc, CardId::ENLIGHTENMENT);
                finish_event(rc);
            } else {
                // Native removes the cards first, then spends the gold.
                rc.eventData[0] = option == 1 ? 125 : 250;
                rc.eventData[1] = option == 1 ? 1 : 2;
                begin_event_card_selection(rc, 6);
            }
            return true;
        case EV_THE_LEGENDS_WERE_TRUE:
            if (option == 0) {
                add_deck_card(rc, CardId::SPOILS_MAP);
            } else {
                lose_hp(rc, 8);
                add_random_potion_event(rc, rc.playerRng[PRNG_REWARDS], false);
            }
            finish_event(rc);
            return true;
        case EV_TEA_MASTER:
            // Bone Tea 50 gold, Ember Tea 150, Tea of Discourtesy free.
            if (option == 0) {
                rc.gold -= 50;
                add_relic(rc, RelicId::BONE_TEA);
            } else if (option == 1) {
                rc.gold -= 150;
                add_relic(rc, RelicId::EMBER_TEA);
            } else {
                add_relic(rc, RelicId::TEA_OF_DISCOURTESY);
            }
            finish_event(rc);
            return true;
        case EV_THIS_OR_THAT: {
            if (option == 0) {
                lose_hp(rc, 6);
                if (rc.screen == RunScreen::RUN_OVER) return true;
                run_gain_gold(rc, rc.eventData[0]);
            } else {
                add_random_shared_relic(rc, rng);
                add_deck_card(rc, CardId::CLUMSY);
            }
            finish_event(rc);
            return true;
        }
        case EV_ROOM_FULL_OF_CHEESE: {
            if (option == 0) {
                return begin_card_grid(rc, 2);
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
                for (int i = 0; i < 3; ++i) queue_potion_event(rc, PotionId::FOUL_POTION);
            } else {
                add_random_potion_event(rc, rc.playerRng[PRNG_REWARDS], true);
            }
            finish_event(rc);
            return true;
        }
        case EV_BRAIN_LEECH: {
            if (option == 0) {
                return begin_card_grid(rc, 1);
            } else {
                lose_hp(rc, 5);
                if (rc.screen == RunScreen::RUN_OVER) return true;
                rc.queue_card_reward(Rarity::COMMON, true, CardPool::COLORLESS);
            }
            finish_event(rc);
            return true;
        }
        case EV_STONE_OF_ALL_TIME: {
            if (option == 0) {
                if (rc.potionCount > 0) {
                    // eventData[0] indexes Player.Potions (non-null slots in
                    // physical order); PotionCmd.Discard leaves the slot empty.
                    const int idx = rc.eventData[0];
                    int seen = -1, slot = -1;
                    for (int i = 0; i < rc.potionSlots; ++i) {
                        if (!rc.potions[i]) continue;
                        if (++seen == idx) { slot = i; break; }
                    }
                    if (slot >= 0)
                        potion_remove_at(rc.potions, rc.potionSlots, rc.potionCount, slot);
                    gain_max_hp(rc, 10);
                }
                // C#: base.Rng.NextInt(100) after the reward is applied.
                rng.next_int(0, 99);
                finish_event(rc);
            } else {
                lose_hp(rc, 6);
                if (rc.screen == RunScreen::RUN_OVER) return true;
                begin_event_card_selection(rc, 3);
            }
            return true;
        }
        case EV_WELCOME_TO_WONGOS: {
            if (option == 0 && rc.gold >= 100) {
                // BuyBargainBin: explicit Common rarity, shop-only filter.
                rc.gold -= 100;
                add_relic(rc, rc.pull_relic(Rarity::COMMON, false, false,
                                            nullptr, 0, true));
            } else if (option == 1 && rc.gold >= 200) {
                rc.gold -= 200;
                // BuyFeaturedItem obtains the relic pulled when the event
                // started. Older checkpoints lack that pull; obtain a front
                // shop-rare now rather than granting nothing.
                RelicId featured = static_cast<RelicId>(rc.eventData[0]);
                if (featured == RelicId::INVALID)
                    featured = rc.pull_relic(Rarity::RARE, false, false,
                                             nullptr, 0, true);
                add_relic(rc, featured);
            } else if (option == 2 && rc.gold >= 300) {
                rc.gold -= 300;
                add_relic(rc, RelicId::WONGOS_MYSTERY_TICKET);
            } else if (option == 3) {
                const int idx = random_upgraded_index(rc, rng);
                if (idx >= 0) card_apply_downgrade(rc.deck[idx]);
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
            }
            finish_event(rc);
            return true;
        }
        case EV_REFLECTIONS: {
            if (option == 0) {
                for (int i = 0; i < 2; ++i) {
                    const int idx = random_upgraded_index(rc, rng);
                    if (idx >= 0) card_apply_downgrade(rc.deck[idx]);
                }
                for (int i = 0; i < 4; ++i) {
                    const int idx = random_upgradable_index(rc, rng);
                    if (idx >= 0) card_apply_upgrade(rc.deck[idx]);
                }
            } else {
                // Each clone is added through the deck-add hooks (Egg relics,
                // Bing Bong, Lucky Fysh, Book of Five Rings, Darkstone
                // Periapt), exactly like CardPileCmd.Add below the original.
                const int original = rc.deckCount;
                for (int i = 0; i < original; ++i) {
                    Card copy = rc.deck[i];
                    copy.uid = rc.allocate_card_uid();
                    if (!rc.add_card_to_deck(copy))
                        throw std::logic_error("Reflections clone exceeds deck capacity");
                }
                add_deck_card(rc, CardId::BAD_LUCK);
            }
            finish_event(rc);
            return true;
        }
        case EV_SPIRIT_GRAFTER: {
            if (option == 0) {
                heal(rc, 25);
                add_deck_card(rc, CardId::METAMORPHOSIS);
            } else {
                begin_event_card_selection(rc, 5);
                return true;
            }
            if (rc.screen == RunScreen::RUN_OVER) return true;
            finish_event(rc);
            return true;
        }
        case EV_LOST_WISP: {
            if (option == 0) {
                add_deck_card(rc, CardId::DECAY);
                add_relic(rc, RelicId::LOST_WISP);
            } else {
                run_gain_gold(rc, rc.eventData[0]);
            }
            finish_event(rc);
            return true;
        }
        case EV_FAKE_MERCHANT:
            // ProceedButton (and every purchase) only updates the inventory;
            // leaving the event ends the room.
            finish_event(rc);
            return true;
        case EV_CRYSTAL_SPHERE:
            if (rc.eventPage != 0) return false;
            if (option == 0) {
                // UncoverFuture: LoseGold then 3 divinations.
                rc.gold -= rc.eventData[0];
                event_crystal_begin(rc, 3);
            } else {
                // PaymentPlan: AddCurseToDeck<Debt> then 6 divinations.
                add_deck_card(rc, CardId::DEBT);
                event_crystal_begin(rc, 6);
            }
            set_page(rc, 1, 0);
            return true;
        case EV_TINKER_TIME: {
            if (rc.eventPage == 0) {
                // ChooseCardType offers TakeRandom(2) of Attack/Skill/Power.
                int types[3] = {0, 1, 2};
                rng.shuffle(types, 3);
                rc.eventData[0] = types[0];
                rc.eventData[1] = types[1];
                set_page(rc, 1, 2);
                return true;
            }
            if (rc.eventPage == 1) {
                // ChooseRiderEffect offers TakeRandom(2) of the chosen type's
                // three riders (RiderEffect 1..9, three per card type).
                const int type = rc.eventData[option];
                rc.eventData[2] = type;
                int riders[3] = {type == 0 ? 1 : type == 1 ? 4 : 7,
                                 type == 0 ? 2 : type == 1 ? 5 : 8,
                                 type == 0 ? 3 : type == 1 ? 6 : 9};
                rng.shuffle(riders, 3);
                rc.eventData[0] = riders[0];
                rc.eventData[1] = riders[1];
                set_page(rc, 2, 2);
                return true;
            }
            Card mad = rc.make_run_card(CardId::MAD_SCIENCE, false);
            mad.tinkerType = static_cast<std::uint8_t>(rc.eventData[2]);
            mad.tinkerRider = static_cast<std::uint8_t>(rc.eventData[option]);
            rc.add_card_to_deck(mad);
            finish_event(rc);
            return true;
        }
        default:
            return false;
    }
}

bool event_combat_gives_standard_rewards(const RunContext &rc) {
    // EncounterModel.ShouldGiveRewards is true by default; only
    // BattlewornDummyEventEncounter overrides it to false.
    return rc.eventId != EV_BATTLEWORN_DUMMY;
}

void event_combat_extra_rewards(RunContext &rc) {
    if (rc.eventId == EV_THE_LANTERN_KEY) {
        // CombatRoom.ExtraRewards: SpecialCardReward(LanternKey).
        int slot = 0;
        while (slot < MAX_CARD_REWARDS &&
               (rc.rewardCardPending[slot] || slot == rc.activeCardReward)) ++slot;
        if (slot < MAX_CARD_REWARDS) {
            rc.rewardCards[slot][0] = rc.make_run_card(CardId::LANTERN_KEY, false);
            rc.rewardCardCounts[slot] = 1;
            rc.rewardCardPending[slot] = true;
            rc.pendingCardReward = true;
            rc.deferredCustomRewards = true;
        }
    } else if (rc.eventId == EV_PUNCH_OFF) {
        // PunchOff.Fight extraRewards: RelicReward then PotionReward.
        if (rc.eventData[1] > 0) {
            rc.eventData[1] = 0;
            rc.queue_random_relic_reward(rc.playerRng[PRNG_REWARDS]);
        }
        if (rc.eventData[2] > 0) {
            rc.eventData[2] = 0;
            const int potion = static_cast<int>(
                random_potion_out_of_combat(rc.playerRng[PRNG_REWARDS], rc.character));
            int slot = 0;
            while (slot < rc.pendingPotionCount && rc.pendingPotions[slot]) ++slot;
            if (slot >= MAX_REWARD_POTIONS)
                throw std::logic_error("Event potion reward capacity exceeded");
            if (slot == rc.pendingPotionCount) ++rc.pendingPotionCount;
            rc.pendingPotions[slot] = potion;
            rc.pendingPotionReward = rc.pendingPotions[0];
            rc.deferredCustomRewards = true;
        }
    } else if (rc.eventId == EV_FAKE_MERCHANT) {
        // FoulPotionThrown builds the extra reward list as FakeMerchantsRug
        // followed by every still-stocked inventory relic.
        rc.queue_exact_relic_reward(RelicId::FAKE_MERCHANTS_RUG);
        for (int i = 0; i < RunContext::FAKE_MERCHANT_RELICS; ++i) {
            if (rc.fakeMerchantSold[i]) continue;
            rc.queue_exact_relic_reward(
                static_cast<RelicId>(rc.fakeMerchantRelics[i]));
        }
    }
    // These events pass shouldResumeAfterCombat=false: once the combat and
    // its rewards are done the run proceeds to the next map point.
    rc.eventId = -1;
    rc.eventPage = 0;
    rc.eventChoiceCount = 0;
    rc.eventCardSelection = 0;
}

bool event_is_fake_merchant(const RunContext &rc) {
    return rc.eventId == EV_FAKE_MERCHANT;
}

bool event_fake_merchant_buy(RunContext &rc, int index) {
    if (!event_is_fake_merchant(rc) || rc.screen != RunScreen::EVENT) return false;
    if (index < 0 || index >= RunContext::FAKE_MERCHANT_RELICS) return false;
    if (rc.fakeMerchantSold[index] || rc.gold < rc.fakeMerchantPrices[index]) return false;
    if (rc.relicCount >= MAX_RELICS) return false;
    const RelicId acquired = static_cast<RelicId>(rc.fakeMerchantRelics[index]);
    if (!rc.add_relic(acquired)) return false;
    rc.gold -= rc.fakeMerchantPrices[index];
    rc.fakeMerchantSold[index] = true;
    return true;
}

bool event_fake_merchant_throw(RunContext &rc) {
    if (!event_is_fake_merchant(rc) || rc.screen != RunScreen::EVENT) return false;
    rc.eventCombat = true;
    rc.eventReturnPage = -1;
    rc.combatIsElite = false;
    rc.combatIsBoss = false;
    rc.begin_combat(Encounter::SETUP_FAKE_MERCHANT);
    return true;
}

namespace {
// CrystalSphereItem ordering used by RunContext::CrystalItemState::type.
enum CrystalItemKind : int {
    CRYSTAL_RELIC = 0,
    CRYSTAL_POTION_COMMON,
    CRYSTAL_POTION_RARE,
    CRYSTAL_CARD_COMMON,
    CRYSTAL_CARD_UNCOMMON,
    CRYSTAL_CARD_RARE,
    CRYSTAL_CURSE,
    CRYSTAL_GOLD_SMALL,
    CRYSTAL_GOLD_BIG
};

void crystal_size(int type, int &w, int &h) {
    switch (type) {
        case CRYSTAL_RELIC: w = 4; h = 4; break;
        case CRYSTAL_POTION_COMMON: w = 1; h = 3; break;
        case CRYSTAL_POTION_RARE: w = 2; h = 2; break;
        case CRYSTAL_CARD_COMMON:
        case CRYSTAL_CARD_UNCOMMON:
        case CRYSTAL_CARD_RARE:
        case CRYSTAL_CURSE: w = 2; h = 2; break;
        case CRYSTAL_GOLD_SMALL: w = 1; h = 1; break;
        default: w = 2; h = 1; break;  // big gold
    }
}

void crystal_clear_cell(RunContext &rc, int x, int y) {
    if (x < 0 || x >= RunContext::CRYSTAL_GRID_W ||
        y < 0 || y >= RunContext::CRYSTAL_GRID_H) return;
    const int cell = y * RunContext::CRYSTAL_GRID_W + x;
    if (!rc.crystalHidden[cell]) return;
    rc.crystalHidden[cell] = 0;
    const int item = rc.crystalCellItem[cell];
    if (item < 0 || item >= rc.crystalItemCount) return;
    RunContext::CrystalItemState &state = rc.crystalItems[item];
    if (!state.placed || state.revealed) return;
    int w = 0, h = 0;
    crystal_size(state.type, w, h);
    for (int dx = 0; dx < w; ++dx) {
        for (int dy = 0; dy < h; ++dy) {
            const int c = (state.y + dy) * RunContext::CRYSTAL_GRID_W + state.x + dx;
            if (rc.crystalHidden[c]) return;
        }
    }
    state.revealed = true;
    if (rc.crystalRevealedCount < RunContext::CRYSTAL_MAX_ITEMS)
        rc.crystalRevealed[rc.crystalRevealedCount++] =
            static_cast<std::uint8_t>(item);
    // CrystalSphereCurse.RevealItem: AddCurseToDeck<Doubt> immediately.
    if (state.type == CRYSTAL_CURSE) add_deck_card(rc, CardId::DOUBT);
}

bool crystal_place_item(RunContext &rc, int item) {
    RunContext::CrystalItemState &state = rc.crystalItems[item];
    int w = 0, h = 0;
    crystal_size(state.type, w, h);
    int cand[RunContext::CRYSTAL_GRID_W * RunContext::CRYSTAL_GRID_H];
    int n = 0;
    for (int x = 0; x < RunContext::CRYSTAL_GRID_W; ++x) {
        for (int y = 0; y < RunContext::CRYSTAL_GRID_H; ++y) {
            bool ok = true;
            for (int dx = 0; dx < w && ok; ++dx) {
                for (int dy = 0; dy < h && ok; ++dy) {
                    const int cx = x + dx, cy = y + dy;
                    if (cx >= RunContext::CRYSTAL_GRID_W ||
                        cy >= RunContext::CRYSTAL_GRID_H) { ok = false; break; }
                    const int cell = cy * RunContext::CRYSTAL_GRID_W + cx;
                    if (!rc.crystalHidden[cell] || rc.crystalCellItem[cell] >= 0)
                        ok = false;
                }
            }
            if (ok) cand[n++] = y * RunContext::CRYSTAL_GRID_W + x;
        }
    }
    if (n == 0) return false;
    const int chosen = cand[rc.eventRng.next_int(0, n - 1)];
    state.x = static_cast<std::uint8_t>(chosen % RunContext::CRYSTAL_GRID_W);
    state.y = static_cast<std::uint8_t>(chosen / RunContext::CRYSTAL_GRID_W);
    state.placed = true;
    for (int dx = 0; dx < w; ++dx)
        for (int dy = 0; dy < h; ++dy)
            rc.crystalCellItem[(state.y + dy) * RunContext::CRYSTAL_GRID_W + state.x + dx] =
                static_cast<std::int16_t>(item);
    return true;
}

void crystal_start(RunContext &rc, int divinations) {
    for (int i = 0; i < RunContext::CRYSTAL_GRID_W * RunContext::CRYSTAL_GRID_H; ++i) {
        rc.crystalHidden[i] = 1;
        rc.crystalCellItem[i] = -1;
    }
    rc.crystalItemCount = 0;
    rc.crystalRevealedCount = 0;
    rc.crystalDivinations = static_cast<std::uint8_t>(divinations);
    rc.crystalTool = 1;
    // Initial fog: four corners expanded twice through horizontal/vertical
    // neighbours only (CrystalSphereMinigame constructor).
    int listX[256], listY[256];
    int count = 4;
    const int lastX = RunContext::CRYSTAL_GRID_W - 1;
    const int lastY = RunContext::CRYSTAL_GRID_H - 1;
    listX[0] = 0; listY[0] = 0;
    listX[1] = lastX; listY[1] = 0;
    listX[2] = lastX; listY[2] = lastY;
    listX[3] = 0; listY[3] = lastY;
    for (int iteration = 0; iteration < 2; ++iteration) {
        int nextX[256], nextY[256], next = 0;
        for (int i = 0; i < count; ++i) {
            nextX[next] = listX[i]; nextY[next++] = listY[i];
            for (int d = -1; d <= 1; d += 2) {
                const int nx = listX[i] + d;
                if (nx >= 0 && nx <= lastX && next < 256) {
                    nextX[next] = nx; nextY[next++] = listY[i];
                }
                const int ny = listY[i] + d;
                if (ny >= 0 && ny <= lastY && next < 256) {
                    nextX[next] = listX[i]; nextY[next++] = ny;
                }
            }
        }
        count = next;
        for (int i = 0; i < count; ++i) { listX[i] = nextX[i]; listY[i] = nextY[i]; }
    }
    for (int i = 0; i < count; ++i) crystal_clear_cell(rc, listX[i], listY[i]);
    // PopulateItems order: relic, two Common potions, one Rare potion, three
    // card rewards (Common/Uncommon/Rare), curse, five small gold, two big gold.
    static const int spec[] = {
        CRYSTAL_RELIC, CRYSTAL_POTION_COMMON, CRYSTAL_POTION_COMMON,
        CRYSTAL_POTION_RARE, CRYSTAL_CARD_COMMON, CRYSTAL_CARD_UNCOMMON,
        CRYSTAL_CARD_RARE, CRYSTAL_CURSE, CRYSTAL_GOLD_SMALL, CRYSTAL_GOLD_SMALL,
        CRYSTAL_GOLD_SMALL, CRYSTAL_GOLD_SMALL, CRYSTAL_GOLD_SMALL,
        CRYSTAL_GOLD_BIG, CRYSTAL_GOLD_BIG};
    for (const int type : spec) {
        if (rc.crystalItemCount >= RunContext::CRYSTAL_MAX_ITEMS) break;
        const int idx = rc.crystalItemCount++;
        rc.crystalItems[idx] = RunContext::CrystalItemState{};
        rc.crystalItems[idx].type = static_cast<std::uint8_t>(type);
        crystal_place_item(rc, idx);
    }
    // The native retry loop only matters when the 121-cell grid cannot hold
    // the 51 occupied cells; a single complete pass is the observable case.
}

int crystal_draw_cards(RunContext &rc, Rarity rarity, Card *out) {
    CardId pool[static_cast<int>(CardId::COUNT)];
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardId id = static_cast<CardId>(i);
        const CardDef &def = card_def(id);
        if (!card_native_available(id) || def.pool != rc.character ||
            def.rarity != rarity || (def.flags & CF_MULTIPLAYER_ONLY)) continue;
        pool[n++] = id;
    }
    native_sort_card_ids(pool, n);
    int count = 0;
    for (int k = 0; k < 3; ++k) {
        CardId options[static_cast<int>(CardId::COUNT)];
        int m = 0;
        for (int j = 0; j < n; ++j) {
            bool used = false;
            for (int u = 0; u < count; ++u) used = used || out[u].id == pool[j];
            if (!used) options[m++] = pool[j];
        }
        if (m == 0) break;
        CardId picked = options[rc.eventRng.next_int(0, m - 1)];
        out[count] = rc.make_run_card(picked, false);
        // RollForUpgrade always consumes NextFloat.
        const float roll = rc.eventRng.next_float();
        const float odds = rarity == Rarity::RARE ? 0.0f
                            : rc.act * (rc.ascension >= 7 ? 0.125f : 0.25f);
        if (card_upgradable(out[count]) && roll <= odds) card_apply_upgrade(out[count]);
        ++count;
    }
    apply_card_reward_hooks(rc, out, count, true);
    return count;
}

void crystal_finish(RunContext &rc) {
    Rng &rng = rc.eventRng;
    int gold = 0;
    for (int r = 0; r < rc.crystalRevealedCount; ++r) {
        const RunContext::CrystalItemState &item =
            rc.crystalItems[rc.crystalRevealed[r]];
        switch (item.type) {
            case CRYSTAL_RELIC: {
                const float roll = rng.next_float();
                const Rarity rarity = roll < 0.5f ? Rarity::COMMON
                                   : roll < 0.83f ? Rarity::UNCOMMON : Rarity::RARE;
                rc.queue_exact_relic_reward(rc.pull_relic(rarity));
                rc.deferredCustomRewards = true;
                break;
            }
            case CRYSTAL_POTION_COMMON:
            case CRYSTAL_POTION_RARE: {
                const Rarity want = item.type == CRYSTAL_POTION_RARE
                                        ? Rarity::RARE : Rarity::COMMON;
                PotionId pool[static_cast<int>(PotionId::COUNT)];
                int n = 0;
                for (const PotionId id : NATIVE_IRONCLAD_POTIONS)
                    if (potion_def(id).rarity == want) pool[n++] = id;
                if (n == 0) break;
                const PotionId picked = pool[rng.next_int(0, n - 1)];
                int slot = 0;
                while (slot < rc.pendingPotionCount && rc.pendingPotions[slot]) ++slot;
                if (slot >= MAX_REWARD_POTIONS)
                    throw std::logic_error("CrystalSphere potion capacity exceeded");
                if (slot == rc.pendingPotionCount) ++rc.pendingPotionCount;
                rc.pendingPotions[slot] = static_cast<int>(picked);
                rc.pendingPotionReward = rc.pendingPotions[0];
                rc.deferredCustomRewards = true;
                break;
            }
            case CRYSTAL_CARD_COMMON:
            case CRYSTAL_CARD_UNCOMMON:
            case CRYSTAL_CARD_RARE: {
                int slot = 0;
                while (slot < MAX_CARD_REWARDS &&
                       (rc.rewardCardPending[slot] || slot == rc.activeCardReward)) ++slot;
                if (slot >= MAX_CARD_REWARDS)
                    throw std::logic_error("CrystalSphere card capacity exceeded");
                const Rarity rarity = item.type == CRYSTAL_CARD_COMMON ? Rarity::COMMON
                                    : item.type == CRYSTAL_CARD_UNCOMMON ? Rarity::UNCOMMON
                                                                          : Rarity::RARE;
                rc.rewardCardCounts[slot] =
                    crystal_draw_cards(rc, rarity, rc.rewardCards[slot]);
                rc.rewardCardPending[slot] = rc.rewardCardCounts[slot] > 0;
                rc.pendingCardReward = true;
                rc.deferredCustomRewards = true;
                break;
            }
            case CRYSTAL_CURSE:
                break;  // already added on reveal
            case CRYSTAL_GOLD_SMALL:
                gold += 10;
                break;
            case CRYSTAL_GOLD_BIG:
                gold += 30;
                break;
            default:
                break;
        }
    }
    if (gold > 0) {
        rc.pendingGoldReward += gold;
        rc.deferredCustomRewards = true;
    }
    finish_event(rc);
}
}  // namespace

void event_crystal_begin(RunContext &rc, int divinations) {
    crystal_start(rc, divinations);
}

bool event_crystal_active(const RunContext &rc) {
    return rc.screen == RunScreen::EVENT && rc.eventId == EV_CRYSTAL_SPHERE &&
           rc.crystalDivinations > 0;
}

bool event_crystal_divine(RunContext &rc, int index) {
    if (rc.screen != RunScreen::EVENT || rc.eventId != EV_CRYSTAL_SPHERE) return false;
    if (rc.crystalDivinations == 0) return false;
    if (index < 0 || index >= RunContext::CRYSTAL_GRID_W * RunContext::CRYSTAL_GRID_H * 2)
        return false;
    const int cell = index / 2;
    const int tool = index & 1;
    rc.crystalTool = static_cast<std::uint8_t>(tool);
    --rc.crystalDivinations;
    const int x = cell % RunContext::CRYSTAL_GRID_W;
    const int y = cell / RunContext::CRYSTAL_GRID_W;
    if (tool == 0) {
        crystal_clear_cell(rc, x, y);
    } else {
        for (int dy = -1; dy <= 1; ++dy)
            for (int dx = -1; dx <= 1; ++dx)
                crystal_clear_cell(rc, x + dx, y + dy);
    }
    if (rc.crystalDivinations == 0) crystal_finish(rc);
    return true;
}

void event_resume_after_combat(RunContext &rc) {
    if (rc.eventId == EV_BATTLEWORN_DUMMY) {
        const int variant = rc.eventData[0];
        // BattleFriendV*.BattlewornDummyTimeLimitPower sets RanOutOfTime before
        // CreatureCmd.Escape, so the escaped dummy is removed with hp intact.
        bool ranOutOfTime = false;
        for (int i = 0; i < rc.battle.monsterCount; ++i) {
            const Monster &m = rc.battle.monsters[i];
            if ((m.id == MonsterId::BATTLE_FRIEND_V1 ||
                 m.id == MonsterId::BATTLE_FRIEND_V2 ||
                 m.id == MonsterId::BATTLE_FRIEND_V3) && !m.alive && m.hp > 0)
                ranOutOfTime = true;
        }
        // Native SetEventFinished runs before Resume builds its reward list.
        finish_event(rc);
        if (ranOutOfTime) return;
        if (variant == 2) {
            // Two upgradable cards after StableShuffle(base.Rng), then take 2.
            int cand[MAX_DECK];
            int n = 0;
            for (int i = 0; i < rc.deckCount; ++i)
                if (card_upgradable(rc.deck[i])) cand[n++] = i;
            native_sort_card_indices(rc, cand, n);
            shuffle_ints(cand, n, rc.eventRng);
            for (int k = 0; k < 2 && k < n; ++k)
                card_apply_upgrade(rc.deck[cand[k]]);
            return;
        }
        if (variant == 1) {
            // PlayerRng.Rewards.NextItem over the character + shared pool.
            const int n = static_cast<int>(std::size(NATIVE_IRONCLAD_POTIONS));
            const int potion = static_cast<int>(
                NATIVE_IRONCLAD_POTIONS[rc.playerRng[PRNG_REWARDS].next_int(0, n - 1)]);
            rc.pendingPotionCount = 1;
            rc.pendingPotions[0] = potion;
            rc.pendingPotionReward = potion;
            rc.deferredCustomRewards = true;
        } else if (variant == 3) {
            const RelicId relic = pull_next_relic_front(rc);
            if (relic != RelicId::INVALID && rc.pendingRelicCount < MAX_REWARD_RELICS) {
                rc.pendingRelics[rc.pendingRelicCount] = static_cast<int>(relic);
                rc.pendingRelicClaimed[rc.pendingRelicCount] = false;
                rc.pendingRelicWax[rc.pendingRelicCount] = false;
                ++rc.pendingRelicCount;
                rc.deferredCustomRewards = true;
            }
        }
        rc.rewardResumeScreen = RunScreen::MAP;
        rc.screen = RunScreen::REWARDS;
        return;
    }
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
