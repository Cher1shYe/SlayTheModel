#include "sts2/potion_slots.h"
#include "sts2/relic_card_rewards.h"
#include "sts2/relic_raw_rarity.h"
#include "sts2/relic_persistent.h"
// Run event engine. Event effects follow the v0.111.0 decompilation; options
// that need a card/enchantment UI we do not model yet are marked APPROXIMATE in
// the coverage manifest (see docs/a0-ironclad-coverage.md).
#include "sts2/run.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>

#include "sts2/monsters.h"
#include "sts2/card_candidates.h"
#include "sts2/relics.h"

namespace sts2 {

namespace {

#include "sts2/native_potion_pool.inc"

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
    // Native v0.111.0 events missing from the legacy table (appended; ids are
    // serialized, never reorder).
    EV_WHISPERING_HOLLOW,
    EV_WOOD_CARVINGS,
    EV_ZEN_WEAVER,
    EV_COUNT
};
static_assert(EV_COUNT <= MAX_EVENTS, "visitedEvents capacity");

const EventInfo EVENTS[EV_COUNT] = {
    {"NEOW", EventStatus::APPROXIMATE, 3},
    {"AROMA_OF_CHAOS", EventStatus::APPROXIMATE, 0},
    {"DENSE_VEGETATION", EventStatus::APPROXIMATE, 0},
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
    {"DARV", EventStatus::APPROXIMATE, 3},
    {"OROBAS", EventStatus::APPROXIMATE, 3},
    {"PAEL", EventStatus::APPROXIMATE, 3},
    {"TEZCATARA", EventStatus::APPROXIMATE, 3},
    {"NONUPEIPE", EventStatus::APPROXIMATE, 3},
    {"TANX", EventStatus::APPROXIMATE, 3},
    {"VAKUU", EventStatus::APPROXIMATE, 3},
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

bool player_relic_bag_has_available(const RunContext &rc);
int tradable_relic_count(const RunContext &rc);
bool deck_can_enchant(const RunContext &rc, EnchantmentId enchantment);
int unlocked_character_pool_count(const RunContext &rc);

bool event_allowed_now(const RunContext &rc, int id) {
    switch (id) {
        case EV_ROOM_FULL_OF_CHEESE: return rc.act < 2;
        case EV_BRAIN_LEECH: return rc.act < 2;
        case EV_POTION_COURIER: return rc.act > 0;
        case EV_WELCOME_TO_WONGOS: return rc.act == 1 && rc.gold >= 100;
        case EV_STONE_OF_ALL_TIME: return rc.act == 1 && rc.potionCount > 0;
        case EV_UNREST_SITE: return rc.hp * 10 <= rc.maxHp * 7;
        case EV_WATERLOGGED_SCRIPTORIUM: return rc.gold >= 55;
        case EV_ENDLESS_CONVEYOR: return rc.gold >= 120;
        case EV_TRASH_HEAP: return rc.hp > 5;
        case EV_PUNCH_OFF: return rc.floor >= 6;
        case EV_WHISPERING_HOLLOW: return rc.gold >= 44;
        case EV_ZEN_WEAVER: return rc.gold >= 125;
        case EV_COLORFUL_PHILOSOPHERS: return unlocked_character_pool_count(rc) > 1;
        case EV_ROUND_TEA_PARTY: return rc.hp >= 12;
        case EV_DOLL_ROOM: return rc.act == 1;
        case EV_CRYSTAL_SPHERE: return rc.gold >= 100 && rc.act > 0;
        case EV_FAKE_MERCHANT: {
            bool foul = false;
            for (int i = 0; i < rc.potionSlots; ++i) foul |= rc.potions[i] == static_cast<int>(PotionId::FOUL_POTION);
            return rc.act >= 1 && (rc.gold >= 100 || foul);
        }
        case EV_THE_FUTURE_OF_POTIONS: return rc.potionCount >= 2;
        case EV_THE_LEGENDS_WERE_TRUE: return rc.act == 0 && rc.deckCount > 0 && rc.hp >= 10;
        case EV_BYRDONIS_NEST: return !run_has_event_pet(rc);  // Player.HasEventPet
        case EV_COLOSSAL_FLOWER: return rc.hp >= 19;
        case EV_FIELD_OF_MAN_SIZED_HOLES: return deck_can_enchant(rc, EnchantmentId::PERFECT_FIT);
        case EV_GRAVE_OF_THE_FORGOTTEN: return deck_can_enchant(rc, EnchantmentId::SOULS_POWER);
        case EV_SYMBIOTE: return rc.act > 0;
        case EV_RELIC_TRADER: return rc.act > 0 && tradable_relic_count(rc) >= 5;
        case EV_RANWID_THE_ELDER:
            return rc.act > 0 && tradable_relic_count(rc) > 0 && rc.gold >= 100 && rc.potionCount > 0;
        case EV_SLIPPERY_BRIDGE:
            if (rc.floor <= 6) return false;
            for (int i = 0; i < rc.deckCount; ++i) if (card_can_transform_from_deck(rc.deck[i])) return true;
            return false;
        case EV_AMALGAMATOR: {
            int strikes = 0, defends = 0;
            for (int i = 0; i < rc.deckCount; ++i) {
                strikes += card_eligible_for_deck_choice(rc.deck[i], 6, 1);
                defends += card_eligible_for_deck_choice(rc.deck[i], 6, 2);
            }
            return strikes >= 2 && defends >= 2;
        }
        case EV_TEA_MASTER: return rc.act < 2 && rc.gold >= 150;
        case EV_LUMINOUS_CHOIR: return rc.gold >= 149 && player_relic_bag_has_available(rc);
        case EV_MORPHIC_GROVE: {
            int transformable = 0;
            for (int i = 0; i < rc.deckCount; ++i) transformable += card_can_transform_from_deck(rc.deck[i]);
            return rc.gold >= 100 && transformable >= 2;
        }
        case EV_WOOD_CARVINGS:
            for (int i = 0; i < rc.deckCount; ++i)
                if (card_def(rc.deck[i].id).rarity == Rarity::BASIC &&
                    card_can_transform_from_deck(rc.deck[i])) return true;
            return false;
        // Reached only through Lantern Key's ModifyNextEvent, never the bag.
        case EV_WAR_HISTORIAN_REPY: return false;
        case EV_SPIRALING_WHIRLPOOL:
            for (int i=0;i<rc.deckCount;++i)
                if (card_can_enchant(rc.deck[i],EnchantmentId::SPIRAL)) return true;
            return false;
        default: return true;
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
    if (original.rarity == Rarity::EVENT || original.rarity == Rarity::ANCIENT ||
        original.rarity == Rarity::TOKEN) pool = CardPool::COLORLESS;
    const bool unrestrictedRarity = original.rarity == Rarity::STATUS || original.rarity == Rarity::CURSE;
    CardId candidates[static_cast<int>(CardId::COUNT)];
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardId id = static_cast<CardId>(i);
        if (!card_native_available(id) || !card_epoch_unlocked(rc.nativeProgress.revealedEpochs, id)) continue;
        const CardDef &def = card_def(id);
        if (id == originalId || def.pool != pool || (def.flags & CF_MULTIPLAYER_ONLY)) continue;
        if (!unrestrictedRarity && def.rarity != Rarity::COMMON &&
            def.rarity != Rarity::UNCOMMON && def.rarity != Rarity::RARE) continue;
        candidates[n++] = id;
    }
    if (!n) return;
    native_sort_card_ids(candidates, n);
    Card replacement = rc.make_run_card(candidates[rng.next_int(0, n - 1)], false);
    const auto type = card_type(replacement);
    if ((type == CardType::ATTACK && run_has_relic(rc, RelicId::MOLTEN_EGG)) ||
        (type == CardType::SKILL && run_has_relic(rc, RelicId::TOXIC_EGG)) ||
        (type == CardType::POWER && run_has_relic(rc, RelicId::FROZEN_EGG)))
        card_apply_upgrade(replacement);
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
        if ((!uncommonOnly || potion_def(id).rarity == Rarity::UNCOMMON) &&
            potion_epoch_unlocked(rc.nativeProgress.revealedEpochs, id)) pool[count++] = id;
    if (count) queue_potion_event(rc, pool[rng.next_int(0, count - 1)]);
}

void add_relic(RunContext &rc, RelicId id) { rc.add_relic(id); }

bool add_random_shared_relic(RunContext &rc, Rng &rng, bool rareOnly,
                             bool commonOnly = false) {
    (void)rng;
    Rarity rarity = Rarity::COMMON;
    if (rareOnly) rarity = Rarity::RARE;
    else if (!commonOnly) {
        const float roll = rc.playerRng[PRNG_REWARDS].next_float();
        rarity = roll < 0.5f ? Rarity::COMMON : (roll < 0.83f ? Rarity::UNCOMMON : Rarity::RARE);
    }
    return rc.add_relic(rc.pull_relic(rarity));
}

void finish_event(RunContext &rc) {
    rc.eventId = -1;
    rc.eventPage = 0;
    rc.eventChoiceCount = 0;
    rc.eventCardSelection = 0;
    rc.eventDeckMask[0] = rc.eventDeckMask[1] = 0;
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

// Swift's base enchantability: playable (non-status/curse) cards.
int swift_enchantable(const RunContext &rc) {
    int n = 0;
    for (int i = 0; i < rc.deckCount; ++i) {
        const CardType t = card_type(rc.deck[i]);
        if (t == CardType::ATTACK || t == CardType::SKILL || t == CardType::POWER) ++n;
    }
    return n;
}

// Instinct: playable attacks with a non-X, positive cost.
int instinct_enchantable(const RunContext &rc) {
    int n = 0;
    for (int i = 0; i < rc.deckCount; ++i) {
        const Card &c = rc.deck[i];
        const CardDef &d = card_def(c.id);
        if (card_type(c) != CardType::ATTACK || (d.flags & CF_UNPLAYABLE)) continue;
        const int cost = c.upgraded ? d.costUp : d.cost;
        if (cost > 0) ++n;
    }
    return n;
}

bool basic_transformable(const Card &c) {
    return card_def(c.id).rarity == Rarity::BASIC && card_can_transform_from_deck(c);
}

bool deck_has_basic_transformable(const RunContext &rc) {
    for (int i = 0; i < rc.deckCount; ++i) if (basic_transformable(rc.deck[i])) return true;
    return false;
}

bool deck_can_enchant(const RunContext &rc, EnchantmentId enchantment) {
    for (int i = 0; i < rc.deckCount; ++i) if (card_can_enchant(rc.deck[i], enchantment)) return true;
    return false;
}

int free_event_potion_rewards(const RunContext &rc) {
    int free = MAX_REWARD_POTIONS - rc.pendingPotionCount;
    for (int i = 0; i < rc.pendingPotionCount; ++i) free += rc.pendingPotions[i] == 0;
    return free;
}

// RelicGrabBag.HasAvailableRelics (read-only; native also prunes disallowed
// entries as a side effect, which is not modeled here).
bool player_relic_bag_has_available(const RunContext &rc) {
    if (!rc.relicBagsInitialized) return false;
    for (int slot = 0; slot < RELIC_BAG_SLOTS; ++slot)
        for (int i = 0; i < rc.playerRelicBag.counts[slot]; ++i) {
            const RelicId id = static_cast<RelicId>(rc.playerRelicBag.entries[slot][i]);
            if (!run_has_relic(rc, id) && run_relic_allowed(rc, id)) return true;
        }
    return false;
}

int unlocked_character_pool_count(const RunContext &rc) {
    CardPool pools[5];
    return native_unlocked_character_pools(rc, pools, 5);
}

// base + (decimal)f, where System.Decimal(float) keeps 7 significant digits.
// Returns trunc(value) and trunc(value * 1.25) (Bowler Hat) via out params.
void decimal_gold_from_float(int base, float f, int &plain, int &withBowler) {
    char text[32];
    std::snprintf(text, sizeof text, "%.6e", static_cast<double>(f));
    long long mantissa = 0;
    int exponent = 0;
    bool negative = false;
    const char *p = text;
    if (*p == '-') { negative = true; ++p; }
    for (; *p && *p != 'e'; ++p) if (*p >= '0' && *p <= '9') mantissa = mantissa * 10 + (*p - '0');
    if (*p == 'e') exponent = std::atoi(p + 1);
    // value = mantissa * 10^(exponent - 6)
    int scale = 6 - exponent;
    __int128 m = negative ? -mantissa : mantissa;
    __int128 denom = 1;
    if (scale >= 0) { for (int i = 0; i < scale && i < 36; ++i) denom *= 10; }
    else { for (int i = 0; i < -scale; ++i) m *= 10; }
    const __int128 total = static_cast<__int128>(base) * denom + m;
    plain = static_cast<int>(total / denom);                 // (int) truncates toward zero
    withBowler = static_cast<int>(total * 125 / (denom * 100));
}

bool snapshot_bool_event(const bool &value) {
    return reinterpret_cast<const unsigned char &>(value) <= 1;
}

int occupied_potion_slot(const RunContext &rc, int ordinal) {
    for (int slot = 0, seen = 0; slot < rc.potionSlots; ++slot)
        if (rc.potions[slot] && seen++ == ordinal) return slot;
    return -1;
}

// TheFutureOfPotions.GetCardRarity.
Rarity future_potion_card_rarity(PotionId id) {
    const Rarity r = potion_def(id).rarity;
    if (r == Rarity::RARE || r == Rarity::EVENT) return Rarity::RARE;
    if (r == Rarity::UNCOMMON) return Rarity::UNCOMMON;
    return Rarity::COMMON;
}

bool deck_mask_has(const RunContext &rc, int i) { return (rc.eventDeckMask[i / 64] >> (i % 64)) & 1u; }

// SlipperyBridge.GetNewRandomCard. eventData[1] is the current card (deck index).
void slippery_bridge_pick(RunContext &rc) {
    int list[MAX_DECK], n = 0;
    const int previous = rc.eventData[1];
    if (previous >= 0) rc.eventDeckMask[previous / 64] |= std::uint64_t{1} << (previous % 64);
    for (int i = 0; i < rc.deckCount; ++i) {
        const Card &c = rc.deck[i];
        const bool keep = previous < 0 ? card_def(c.id).rarity != Rarity::BASIC
                                       : c.id != rc.deck[previous].id;
        if (keep && card_can_transform_from_deck(c) && !deck_mask_has(rc, i)) list[n++] = i;
    }
    if (n == 0)
        for (int i = 0; i < rc.deckCount; ++i) if (card_can_transform_from_deck(rc.deck[i])) list[n++] = i;
    rc.eventData[1] = n ? list[rc.eventRng.next_int_range(0, n)] : -1;
}

// SelfHelpBook.DeckFilter: type restriction plus the enchantment's CanEnchant.
bool deck_can_enchant_type(const RunContext &rc, EnchantmentId e, CardType type) {
    for (int i = 0; i < rc.deckCount; ++i)
        if (card_type(rc.deck[i]) == type && card_can_enchant(rc.deck[i], e)) return true;
    return false;
}

bool self_help_book_any(const RunContext &rc) {
    return deck_can_enchant_type(rc, EnchantmentId::SHARP, CardType::ATTACK) ||
           deck_can_enchant_type(rc, EnchantmentId::NIMBLE, CardType::SKILL) ||
           deck_can_enchant_type(rc, EnchantmentId::SWIFT, CardType::POWER);
}

int tradable_relic_count(const RunContext &rc) {
    int n = 0;
    for (int i = 0; i < rc.relicCount; ++i) n += run_relic_tradable(rc, i);
    return n;
}

int relic_slot_of(const RunContext &rc, int id) {
    for (int i = 0; i < rc.relicCount; ++i) if (rc.relics[i] == id) return i;
    return -1;
}

// RelicFactory.PullNextRelicFromFront(player): RollRarity(PlayerRng.Rewards),
// then the player's bag front (falls back to Circlet). Pulling removes it.
RelicId pull_relic_from_front(RunContext &rc) {
    const float roll = rc.playerRng[PRNG_REWARDS].next_float();
    const Rarity rarity = roll < 0.5f ? Rarity::COMMON : roll < 0.83f ? Rarity::UNCOMMON : Rarity::RARE;
    return rc.pull_relic(rarity);
}

// EndlessConveyor dishes. eventData: [0] NumOfGrabs, [1] current dish,
// [2] last dish id (NONE initially), [3] 1 while a dish's reward is pending.
enum ConveyorDish : int {
    DISH_CAVIAR, DISH_SPICY_SNAPPY, DISH_JELLY_LIVER, DISH_FRIED_EEL,
    DISH_SUSPICIOUS_CONDIMENT, DISH_CLAM_ROLL, DISH_GOLDEN_FYSH, DISH_SEAPUNK_SALAD, DISH_NONE
};

// EndlessConveyor.RollDish.
void conveyor_roll_dish(RunContext &rc) {
    ++rc.eventData[0];
    if (rc.eventData[0] % 5 == 0) {
        rc.eventData[1] = rc.eventData[2] = DISH_SEAPUNK_SALAD;
        return;
    }
    int dishes[7], n = 0;
    float weights[7];
    auto add = [&](int dish, float w) { dishes[n] = dish; weights[n++] = w; };
    add(DISH_CAVIAR, 6.0f);
    add(DISH_SPICY_SNAPPY, 3.0f);
    add(DISH_JELLY_LIVER, 3.0f);
    add(DISH_FRIED_EEL, 3.0f);
    if (rc.potionCount < rc.potionSlots) add(DISH_SUSPICIOUS_CONDIMENT, 3.0f);  // HasOpenPotionSlots
    if (rc.hp != rc.maxHp) add(DISH_CLAM_ROLL, 6.0f);
    if (rc.eventData[0] > 1) add(DISH_GOLDEN_FYSH, 1.0f);
    int kept = 0;
    for (int i = 0; i < n; ++i)
        if (dishes[i] != rc.eventData[2]) { dishes[kept] = dishes[i]; weights[kept++] = weights[i]; }
    float total = 0.0f;
    for (int i = 0; i < kept; ++i) total += weights[i];
    const float roll = rc.eventRng.next_float() * total;
    float cumulative = 0.0f;
    for (int i = 0; i < kept; ++i) {
        cumulative += weights[i];
        if (roll < cumulative) {
            rc.eventData[1] = rc.eventData[2] = dishes[i];
            return;
        }
    }
    // No dish chosen (float edge): native keeps the previous dish.
}

void conveyor_after_dish(RunContext &rc) {
    rc.eventData[3] = 0;
    rc.eventCardSelection = 0;
    conveyor_roll_dish(rc);
    set_page(rc, 1, 2);  // Grab / Leave
}

// ---- Crystal Sphere minigame ----------------------------------------------
const int CRYSTAL_ITEM_W[CRYSTAL_SPHERE_ITEM_TYPES] = {4, 1, 2, 2, 2, 2, 2, 1, 2};
const int CRYSTAL_ITEM_H[CRYSTAL_SPHERE_ITEM_TYPES] = {4, 3, 2, 2, 2, 2, 2, 1, 1};

bool crystal_hidden(const CrystalSphereState &g, int x, int y) {
    const int b = x * CRYSTAL_SPHERE_SIZE + y;
    return (g.hidden[b / 64] >> (b % 64)) & 1u;
}

void crystal_set_hidden(CrystalSphereState &g, int x, int y, bool on) {
    const int b = x * CRYSTAL_SPHERE_SIZE + y;
    if (on) g.hidden[b / 64] |= std::uint64_t{1} << (b % 64);
    else g.hidden[b / 64] &= ~(std::uint64_t{1} << (b % 64));
}

// CrystalSphereItem.PlaceItem: NextItem over valid origins (x outer, y inner).
bool crystal_place(CrystalSphereState &g, Rng &rng, int type) {
    if (g.itemCount >= CRYSTAL_SPHERE_MAX_ITEMS) throw std::logic_error("Crystal Sphere item capacity");
    const int index = g.itemCount++;
    g.itemType[index] = static_cast<std::uint8_t>(type);
    g.itemPlaced[index] = false;
    const int w = CRYSTAL_ITEM_W[type], h = CRYSTAL_ITEM_H[type];
    int origins[CRYSTAL_SPHERE_CELLS], n = 0;
    for (int x = 0; x < CRYSTAL_SPHERE_SIZE; ++x)
        for (int y = 0; y < CRYSTAL_SPHERE_SIZE; ++y) {
            bool ok = x + w <= CRYSTAL_SPHERE_SIZE && y + h <= CRYSTAL_SPHERE_SIZE;
            for (int i = 0; ok && i < w; ++i)
                for (int j = 0; ok && j < h; ++j)
                    ok = crystal_hidden(g, x + i, y + j) &&
                         !g.cellItem[(x + i) * CRYSTAL_SPHERE_SIZE + y + j];
            if (ok) origins[n++] = x * CRYSTAL_SPHERE_SIZE + y;
        }
    if (!n) return false;
    const int origin = origins[rng.next_int_range(0, n)];
    g.itemX[index] = static_cast<std::int8_t>(origin / CRYSTAL_SPHERE_SIZE);
    g.itemY[index] = static_cast<std::int8_t>(origin % CRYSTAL_SPHERE_SIZE);
    g.itemPlaced[index] = true;
    for (int i = 0; i < w; ++i)
        for (int j = 0; j < h; ++j)
            g.cellItem[(g.itemX[index] + i) * CRYSTAL_SPHERE_SIZE + g.itemY[index] + j] =
                static_cast<std::int16_t>(index + 1);
    return true;
}

// CrystalSphereMinigame constructor.
void crystal_sphere_begin(RunContext &rc, int divinations) {
    CrystalSphereState &g = rc.crystalSphere;
    g = CrystalSphereState{};
    for (int x = 0; x < CRYSTAL_SPHERE_SIZE; ++x)
        for (int y = 0; y < CRYSTAL_SPHERE_SIZE; ++y) crystal_set_hidden(g, x, y, true);
    // Corners, expanded twice by horizontal/vertical neighbours (Manhattan <= 2).
    const int last = CRYSTAL_SPHERE_SIZE - 1;
    const int corners[4][2] = {{0, 0}, {last, 0}, {last, last}, {0, last}};
    for (const auto &c : corners)
        for (int dx = -2; dx <= 2; ++dx)
            for (int dy = -2; dy <= 2; ++dy) {
                const int x = c[0] + dx, y = c[1] + dy;
                if (std::abs(dx) + std::abs(dy) <= 2 && x >= 0 && x <= last && y >= 0 && y <= last)
                    crystal_set_hidden(g, x, y, false);
            }
    // PopulateItems, retried (without clearing) up to 10 times; `flag && Place`
    // stops placing (and drawing RNG) after the first failure of an attempt.
    static const int order[15] = {0, 1, 1, 2, 3, 4, 5, 6, 7, 7, 7, 7, 7, 8, 8};
    bool placedAll = false;
    for (int attempt = 0; attempt < 10 && !placedAll; ++attempt) {
        placedAll = true;
        for (int type : order) {
            if (placedAll) placedAll = crystal_place(g, rc.eventRng, type);
            else {
                const int index = g.itemCount++;
                g.itemType[index] = static_cast<std::uint8_t>(type);
                g.itemPlaced[index] = false;
            }
        }
    }
    g.divinations = divinations;
    g.active = true;
}

bool crystal_all_clear(const CrystalSphereState &g, int item) {
    for (int i = 0; i < CRYSTAL_ITEM_W[g.itemType[item]]; ++i)
        for (int j = 0; j < CRYSTAL_ITEM_H[g.itemType[item]]; ++j)
            if (crystal_hidden(g, g.itemX[item] + i, g.itemY[item] + j)) return false;
    return true;
}

void crystal_clear_cell(RunContext &rc, int x, int y) {
    CrystalSphereState &g = rc.crystalSphere;
    if (!crystal_hidden(g, x, y)) return;
    crystal_set_hidden(g, x, y, false);
    const int item = g.cellItem[x * CRYSTAL_SPHERE_SIZE + y] - 1;
    if (item < 0 || !crystal_all_clear(g, item)) return;
    g.revealed[g.revealedCount++] = static_cast<std::int16_t>(item);
    if (g.itemType[item] == 6) add_deck_card(rc, CardId::DOUBT);  // CrystalSphereCurse.RevealItem
}

// CompleteMinigame -> OfferCrystalSphereRewards(revealed, event Rng).
void crystal_sphere_rewards(RunContext &rc) {
    CrystalSphereState &g = rc.crystalSphere;
    Rng &rng = rc.eventRng;
    PotionId potions[CRYSTAL_SPHERE_MAX_ITEMS]{};
    // ToReward for every revealed item first (potions are chosen here).
    for (int k = 0; k < g.revealedCount; ++k) {
        const int type = g.itemType[g.revealed[k]];
        if (type != 1 && type != 2) continue;
        const Rarity want = type == 1 ? Rarity::COMMON : Rarity::RARE;
        PotionId pool[static_cast<int>(PotionId::COUNT)];
        int n = 0;
        for (PotionId id : NATIVE_IRONCLAD_POTIONS)
            if (potion_def(id).rarity == want && potion_epoch_unlocked(rc.nativeProgress.revealedEpochs, id)) pool[n++] = id;
        if (n) potions[k] = pool[rng.next_int_range(0, n)];
    }
    // Then OfferCustom populates each reward in order.
    int gold = 0;
    for (int k = 0; k < g.revealedCount; ++k) {
        const int type = g.itemType[g.revealed[k]];
        if (type == 1 || type == 2) {
            if (potions[k] != PotionId::INVALID) queue_potion_event(rc, potions[k]);
        } else if (type >= 3 && type <= 5) {
            Card cards[3];
            const Rarity rarity = type == 3 ? Rarity::COMMON : type == 4 ? Rarity::UNCOMMON : Rarity::RARE;
            if (make_crystal_sphere_card_reward(rc, rarity, rng, cards) != 3 || !rc.queue_prepared_card_reward(cards, 3))
                throw std::logic_error("Crystal Sphere card reward generation failed");
        } else if (type == 7 || type == 8) {
            const int amount = type == 7 ? 10 : 30;
            rng.next_int_range(amount, amount + 1);  // GoldReward.Populate
            if (gold >= MAX_EXTRA_GOLD_REWARDS) throw std::logic_error("Crystal Sphere gold reward capacity");
            rc.extraGoldRewards[gold++] = amount;
            rc.deferredCustomRewards = true;
        } else if (type == 0) {
            const float roll = rng.next_float();  // RelicFactory.RollRarity(rng)
            const Rarity r = roll < 0.5f ? Rarity::COMMON : roll < 0.83f ? Rarity::UNCOMMON : Rarity::RARE;
            const RelicId relic = rc.pull_relic(r);
            int slot = 0;
            while (slot < rc.pendingRelicCount && rc.pendingRelics[slot] && !rc.pendingRelicClaimed[slot]) ++slot;
            if (slot >= MAX_REWARD_RELICS) throw std::logic_error("Crystal Sphere relic reward capacity");
            if (slot == rc.pendingRelicCount) ++rc.pendingRelicCount;
            rc.pendingRelics[slot] = static_cast<int>(relic);
            rc.pendingRelicClaimed[slot] = false;
            rc.pendingRelicWax[slot] = false;
            rc.deferredCustomRewards = true;
        }
    }
}

// PlayerCmd.LoseGold: clamps at zero, no hooks.
void lose_gold(RunContext &rc, int amount) { rc.gold = std::max(0, rc.gold - amount); }

int removable_cards(const RunContext &rc) {
    int n = 0;
    for (int i = 0; i < rc.deckCount; ++i) {
        if (rc.deck[i].id != CardId::INVALID) ++n;
    }
    return n;
}

// ScrollBoxes.CanGenerateBundles: >= 4 unlocked commons and >= 2 uncommons.
bool can_generate_bundles(std::uint64_t epochs) {
    int common = 0;
    int uncommon = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        if (!card_native_available(static_cast<CardId>(i)) || !card_epoch_unlocked(epochs, static_cast<CardId>(i))) continue;
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
            int curses[6];
            int cn = 0;
            curses[cn++] = static_cast<int>(RelicId::CURSED_PEARL);
            curses[cn++] = static_cast<int>(RelicId::LARGE_CAPSULE);
            curses[cn++] = static_cast<int>(RelicId::LEAFY_POULTICE);
            curses[cn++] = static_cast<int>(RelicId::PRECARIOUS_SHEARS);
            if (can_generate_bundles(rc.nativeProgress.revealedEpochs)) curses[cn++] = static_cast<int>(RelicId::SCROLL_BOXES);
            curses[cn++] = static_cast<int>(RelicId::SILVER_CRUCIBLE);  // single player
            const int curse = pick_one(curses, cn, rng);
            static const int positives[9] = {
                static_cast<int>(RelicId::ARCANE_SCROLL),
                static_cast<int>(RelicId::BOOMING_CONCH),
                static_cast<int>(RelicId::POMANDER),
                static_cast<int>(RelicId::GOLDEN_PEARL),
                static_cast<int>(RelicId::LEAD_PAPERWEIGHT),
                static_cast<int>(RelicId::NEW_LEAF),
                static_cast<int>(RelicId::NEOWS_TORMENT),
                static_cast<int>(RelicId::PRECISE_SCISSORS),
                static_cast<int>(RelicId::LOST_COFFER)};
            int list[12];
            int n = 0;
            for (const int r : positives) {
                if (curse == static_cast<int>(RelicId::CURSED_PEARL) &&
                    r == static_cast<int>(RelicId::GOLDEN_PEARL)) continue;
                if (curse == static_cast<int>(RelicId::PRECARIOUS_SHEARS) &&
                    r == static_cast<int>(RelicId::PRECISE_SCISSORS)) continue;
                if (curse == static_cast<int>(RelicId::LEAFY_POULTICE) &&
                    r == static_cast<int>(RelicId::NEW_LEAF)) continue;
                list[n++] = r;
            }
            list[n++] = static_cast<int>(rng.next_bool() ? RelicId::NUTRITIOUS_OYSTER
                                                         : RelicId::STONE_HUMIDIFIER);
            if (curse != static_cast<int>(RelicId::LARGE_CAPSULE)) {
                list[n++] = static_cast<int>(rng.next_bool() ? RelicId::LAVA_ROCK
                                                             : RelicId::SMALL_CAPSULE);
            }
            shuffle_ints(list, n, rng);
            opts[0] = list[0];
            opts[1] = list[1];
            opts[2] = curse;
            break;
        }
        case EV_OROBAS: {
            CardPool unlocked[5], other[5];
            const int unlockedN=native_unlocked_character_pools(rc,unlocked,5);
            int otherN=0;
            for(int i=0;i<unlockedN;++i) if(unlocked[i]!=CardPool::IRONCLAD) other[otherN++]=unlocked[i];
            rc.preparedSeaGlassPool=otherN?other[rng.next_int(0,otherN-1)]:CardPool::IRONCLAD;
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
            for(int i=0;i<rc.deckCount;++i) if(rc.deck[i].id==CardId::BASH || rc.deck[i].id==CardId::BREAK) {
                third[thirdN++]=static_cast<int>(RelicId::ARCHAIC_TOOTH); break;
            }
            opts[2]=thirdN?pick_one(third,thirdN,rng):0;
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
            if (deck_flag_count(rc, CF_DEFEND) >= 3) {
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
            static const int p1[3] = {static_cast<int>(RelicId::NUTRITIOUS_SOUP),
                                      static_cast<int>(RelicId::VERY_HOT_COCOA),
                                      static_cast<int>(RelicId::YUMMY_COOKIE)};
            static const int p2[4] = {static_cast<int>(RelicId::BIIIG_HUG),
                                      static_cast<int>(RelicId::STORYBOOK),
                                      static_cast<int>(RelicId::SEAL_OF_GOLD),
                                      static_cast<int>(RelicId::TOASTY_MITTENS)};
            static const int p3[3] = {static_cast<int>(RelicId::GOLDEN_COMPASS),
                                      static_cast<int>(RelicId::PUMPKIN_CANDLE),
                                      static_cast<int>(RelicId::TOY_BOX)};
            opts[0] = pick_one(p1, 3, rng);
            opts[1] = pick_one(p2, 4, rng);
            opts[2] = pick_one(p3, 3, rng);
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
        case EV_WOOD_CARVINGS:
        case EV_ZEN_WEAVER:
        case EV_TEA_MASTER: return 3;
        case EV_SLIPPERY_BRIDGE:
        case EV_COLOSSAL_FLOWER: return 2;  // two options on every page
        case EV_COLORFUL_PHILOSOPHERS: return rc.eventChoiceCount;
        case EV_DOLL_ROOM:
        case EV_THE_FUTURE_OF_POTIONS:
        case EV_SELF_HELP_BOOK:
        case EV_RELIC_TRADER: return rc.eventChoiceCount;
        case EV_RANWID_THE_ELDER: return 3;
        case EV_THE_LEGENDS_WERE_TRUE:
        case EV_BYRDONIS_NEST: return 2;
        case EV_ENDLESS_CONVEYOR:
        case EV_TRIAL: return 2;
        case EV_CRYSTAL_SPHERE: return rc.crystalSphere.active ? 0 : 2;
        case EV_BATTLEWORN_DUMMY: return 3;
        case EV_FAKE_MERCHANT: return 7;
        case EV_THE_LANTERN_KEY:
        case EV_PUNCH_OFF: return rc.eventPage == 0 ? 2 : 1;
        case EV_WAR_HISTORIAN_REPY: return rc.eventPage == 0 ? 2 : 1;
        case EV_TINKER_TIME: return rc.eventPage == 0 ? 1 : 2;
        default: return rc.eventPage == 0 ? 2 : 1;
    }
}

}  // namespace

const EventInfo *event_info(int id) {
    if (id < 0 || id >= EV_COUNT) return nullptr;
    return &EVENTS[id];
}

int event_count() { return EV_COUNT; }

bool event_is_allowed(const RunContext &rc, int id) {
    return id >= 0 && id < EV_COUNT && event_allowed_now(rc, id);
}

namespace {

// ActModel.AllEvents for each act, then ModelDb.AllSharedEvents, in model
// declaration order (ActModel.GenerateRooms concatenates before shuffling).
const char *const OVERGROWTH_EVENT_ORDER[] = {
    "AROMA_OF_CHAOS", "BYRDONIS_NEST", "DENSE_VEGETATION", "JUNGLE_MAZE_ADVENTURE",
    "LUMINOUS_CHOIR", "MORPHIC_GROVE", "SAPPHIRE_SEED", "SUNKEN_STATUE", "TABLET_OF_TRUTH",
    "UNREST_SITE", "WELLSPRING", "WHISPERING_HOLLOW", "WOOD_CARVINGS"};
const char *const HIVE_EVENT_ORDER[] = {
    "AMALGAMATOR", "BUGSLAYER", "COLORFUL_PHILOSOPHERS", "COLOSSAL_FLOWER",
    "FIELD_OF_MAN_SIZED_HOLES", "INFESTED_AUTOMATON", "LOST_WISP", "SPIRIT_GRAFTER",
    "THE_LANTERN_KEY", "ZEN_WEAVER"};
const char *const GLORY_EVENT_ORDER[] = {
    "BATTLEWORN_DUMMY", "GRAVE_OF_THE_FORGOTTEN", "HUNGRY_FOR_MUSHROOMS", "REFLECTIONS",
    "ROUND_TEA_PARTY", "TRIAL", "TINKER_TIME"};
const char *const UNDERDOCKS_EVENT_ORDER[] = {
    "ABYSSAL_BATHS", "DROWNING_BEACON", "ENDLESS_CONVEYOR", "PUNCH_OFF",
    "SPIRALING_WHIRLPOOL", "SUNKEN_STATUE", "SUNKEN_TREASURY",
    "DOORS_OF_LIGHT_AND_DARK", "TRASH_HEAP", "WATERLOGGED_SCRIPTORIUM"};
const char *const SHARED_EVENT_ORDER[] = {
    "BRAIN_LEECH", "CRYSTAL_SPHERE", "DOLL_ROOM", "FAKE_MERCHANT", "POTION_COURIER",
    "RANWID_THE_ELDER", "RELIC_TRADER", "ROOM_FULL_OF_CHEESE", "SELF_HELP_BOOK",
    "SLIPPERY_BRIDGE", "STONE_OF_ALL_TIME", "SYMBIOTE", "TEA_MASTER",
    "THE_FUTURE_OF_POTIONS", "THE_LEGENDS_WERE_TRUE", "THIS_OR_THAT",
    "WAR_HISTORIAN_REPY", "WELCOME_TO_WONGOS"};

int event_id_by_name(const char *name) {
    for (int id = 0; id < EV_COUNT; ++id)
        if (std::strcmp(EVENTS[id].name, name) == 0) return id;
    throw std::logic_error("Native event order names an unregistered event");
}

bool event_epoch_revealed(int id, const NativeProgressContext *progress) {
    if (!progress) return true;
    if (id == EV_TRASH_HEAP) return progress->event1EpochRevealed;
    if (id == EV_REFLECTIONS) return progress->event2EpochRevealed;
    if (id == EV_COLORFUL_PHILOSOPHERS) return progress->event3EpochRevealed;
    return true;
}

template <std::size_t N>
void append_event_order(const char *const (&names)[N], const NativeProgressContext *progress,
                        int *out, int maxOut, int &n) {
    for (const char *name : names) {
        const int id = event_id_by_name(name);
        if (!event_epoch_revealed(id, progress)) continue;
        // Unsupported events are a recorded coverage limitation: excluding them
        // changes the shuffle, so the bag is native only once all are ported.
        if (EVENTS[id].status == EventStatus::UNSUPPORTED) continue;
        if (out && n < maxOut) out[n] = id;
        ++n;
    }
}

}  // namespace

int event_pool_for_act_type(ActType actType, int *out, int maxOut,
                            const NativeProgressContext *progress) {
    int n = 0;
    switch (actType) {
        case ActType::OVERGROWTH: append_event_order(OVERGROWTH_EVENT_ORDER, progress, out, maxOut, n); break;
        case ActType::HIVE: append_event_order(HIVE_EVENT_ORDER, progress, out, maxOut, n); break;
        case ActType::GLORY: append_event_order(GLORY_EVENT_ORDER, progress, out, maxOut, n); break;
        case ActType::UNDERDOCKS: append_event_order(UNDERDOCKS_EVENT_ORDER, progress, out, maxOut, n); break;
        default: throw std::invalid_argument("Unknown act type");
    }
    append_event_order(SHARED_EVENT_ORDER, progress, out, maxOut, n);
    return n;
}

int event_pool_for_act(int act, int *out, int maxOut) {
    if (act < 0 || act > 2) return 0;
    return event_pool_for_act_type(static_cast<ActType>(act), out, maxOut, nullptr);
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
    rc.eventDeckMask[0] = rc.eventDeckMask[1] = 0;
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
        case EV_BUGSLAYER:
        case EV_INFESTED_AUTOMATON:
        case EV_MORPHIC_GROVE:
        case EV_ROUND_TEA_PARTY:
        case EV_AMALGAMATOR:
        case EV_TRASH_HEAP:
        case EV_THE_LEGENDS_WERE_TRUE:
        case EV_BYRDONIS_NEST:
            set_page(rc, 0, 2);
            break;
        case EV_TEA_MASTER:
        case EV_DOLL_ROOM:
            set_page(rc, 0, 3);
            break;
        case EV_THE_FUTURE_OF_POTIONS: {
            // PotionToCardType: one Rng.NextItem per owned potion (slot order);
            // Common/Token potions exclude Power. Options are the first three.
            int option = 0;
            for (int slot = 0; slot < rc.potionSlots; ++slot) {
                if (!rc.potions[slot]) continue;
                const Rarity r = potion_def(static_cast<PotionId>(rc.potions[slot])).rarity;
                const int types = (r == Rarity::COMMON || r == Rarity::TOKEN) ? 2 : 3;
                const int type = rc.eventRng.next_int_range(0, types);  // Attack, Skill, Power
                if (option < 3) rc.eventData[option] = type;
                ++option;
            }
            set_page(rc, 0, std::min(3, option));
            break;
        }
        case EV_FIELD_OF_MAN_SIZED_HOLES:
        case EV_SYMBIOTE:
        case EV_GRAVE_OF_THE_FORGOTTEN:
            set_page(rc, 0, 2);
            break;
        case EV_TRIAL:
            set_page(rc, 0, 2);  // Accept / Reject; eventData[0] = case once accepted
            break;
        case EV_TINKER_TIME:
            set_page(rc, 0, 1);  // Choose Card Type
            break;
        case EV_BATTLEWORN_DUMMY:
            set_page(rc, 0, 3);  // Setting 1/2/3
            break;
        case EV_FAKE_MERCHANT: {
            // BeforeEventStarted: 9 fake relics UnstableShuffle(event Rng), take 6;
            // each MerchantRelicEntry costs round(50 * Shops.NextFloat(0.85, 1.15)).
            int relics[9] = {static_cast<int>(RelicId::FAKE_ANCHOR), static_cast<int>(RelicId::FAKE_BLOOD_VIAL),
                static_cast<int>(RelicId::FAKE_HAPPY_FLOWER), static_cast<int>(RelicId::FAKE_LEES_WAFFLE),
                static_cast<int>(RelicId::FAKE_MANGO), static_cast<int>(RelicId::FAKE_ORICHALCUM),
                static_cast<int>(RelicId::FAKE_SNECKO_EYE), static_cast<int>(RelicId::FAKE_STRIKE_DUMMY),
                static_cast<int>(RelicId::FAKE_VENERABLE_TEA_SET)};
            shuffle_ints(relics, 9, rc.eventRng);
            for (int i = 0; i < 6; ++i) {
                rc.eventRelics[i] = relics[i];
                const float factor = rc.playerRng[PRNG_SHOPS].next_float(0.85f, 1.15f);
                rc.eventData[i] = static_cast<int>(std::nearbyint(static_cast<double>(50.0f * factor)));
            }
            set_page(rc, 0, 7);  // buy relic 0..5, leave
            break;
        }
        case EV_THE_LANTERN_KEY:
            set_page(rc, 0, 2);  // Return the key / Keep the key
            break;
        case EV_PUNCH_OFF:
            rc.eventData[0] = rc.eventRng.next_int_range(91, 99);  // CalculateVars (display only)
            set_page(rc, 0, 2);  // Nab / I can take them
            break;
        case EV_WAR_HISTORIAN_REPY:
            set_page(rc, 0, 2);  // Unlock cage / Unlock chest
            break;
        case EV_CRYSTAL_SPHERE:
            // CalculateVars: UncoverFutureCost 50 + Rng.NextInt(1, 50).
            rc.eventData[0] = 50 + rc.eventRng.next_int_range(1, 50);
            set_page(rc, 0, 2);
            break;
        case EV_ENDLESS_CONVEYOR:
            rc.eventData[0] = 0;
            rc.eventData[2] = DISH_NONE;
            conveyor_roll_dish(rc);  // CalculateVars
            set_page(rc, 0, 2);      // Grab / Observe Chef
            break;
        case EV_RELIC_TRADER: {
            // CalculateVars: OwnedRelics = tradable relics (inventory order),
            // StableShuffle (ModelId order, then UnstableShuffle), take 3; then
            // NewRelics = three front pulls. eventData = owned ids, eventRelics = new.
            int owned[MAX_RELICS], n = 0;
            for (int i = 0; i < rc.relicCount; ++i) if (run_relic_tradable(rc, i)) owned[n++] = rc.relics[i];
            std::stable_sort(owned, owned + n, [](int a, int b) {
                return std::strcmp(relic_def(static_cast<RelicId>(a)).key,
                                   relic_def(static_cast<RelicId>(b)).key) < 0;
            });
            shuffle_ints(owned, n, rc.eventRng);
            const int shown = std::min(3, n);
            for (int i = 0; i < shown; ++i) rc.eventData[i] = owned[i];
            if (shown > 0)
                for (int i = 0; i < 3; ++i) rc.eventRelics[i] = static_cast<int>(pull_relic_from_front(rc));
            set_page(rc, 0, std::max(1, shown));  // PROCEED when nothing is tradable
            rc.eventData[3] = shown;
            break;
        }
        case EV_RANWID_THE_ELDER: {
            // GenerateInitialOptions: Rng.NextItem(Potions), then Rng.NextItem(tradable relics).
            rc.eventData[0] = rc.potionCount > 0 ? rc.eventRng.next_int_range(0, rc.potionCount) : -1;
            int tradable[MAX_RELICS], n = 0;
            for (int i = 0; i < rc.relicCount; ++i) if (run_relic_tradable(rc, i)) tradable[n++] = rc.relics[i];
            rc.eventData[1] = n > 0 ? tradable[rc.eventRng.next_int_range(0, n)] : -1;
            set_page(rc, 0, 3);
            break;
        }
        case EV_SELF_HELP_BOOK:
            // Three (possibly locked) options, or only NO_OPTIONS.
            set_page(rc, 0, self_help_book_any(rc) ? 3 : 1);
            break;
        case EV_COLOSSAL_FLOWER:
            rc.eventData[0] = 0;  // NumberOfDigs
            set_page(rc, 0, 2);
            break;
        case EV_JUNGLE_MAZE_ADVENTURE: {
            // CalculateVars: SoloGold 150 / JoinForcesGold 50 + (decimal)NextFloat(-15, 15).
            const float solo = rc.eventRng.next_float(-15.0f, 15.0f);
            const float join = rc.eventRng.next_float(-15.0f, 15.0f);
            decimal_gold_from_float(150, solo, rc.eventData[0], rc.eventData[1]);
            decimal_gold_from_float(50, join, rc.eventData[2], rc.eventData[3]);
            set_page(rc, 0, 2);
            break;
        }
        case EV_SLIPPERY_BRIDGE:
            rc.eventData[0] = 0;   // NumberOfHoldOns
            rc.eventData[1] = -1;  // no card yet
            slippery_bridge_pick(rc);
            set_page(rc, 0, 2);
            break;
        case EV_LUMINOUS_CHOIR:
            // CalculateVars: Gold 149 - Rng.NextInt(0, 50).
            rc.eventData[0] = 149 - rc.eventRng.next_int_range(0, 50);
            set_page(rc, 0, 2);
            break;
        case EV_COLORFUL_PHILOSOPHERS: {
            // Other unlocked pools in CardPoolColorOrder, then remove random
            // options (Rng.NextInt(count)) until at most three remain.
            const CardPool order[] = {CardPool::NECROBINDER, CardPool::IRONCLAD, CardPool::REGENT,
                                      CardPool::SILENT, CardPool::DEFECT};
            int options[5], n = 0;
            for (CardPool pool : order)
                if (pool != CardPool::IRONCLAD && native_card_pool_unlocked(rc, pool))
                    options[n++] = static_cast<int>(pool);
            while (n > 3) {
                const int remove = rc.eventRng.next_int_exclusive(n);
                for (int i = remove; i + 1 < n; ++i) options[i] = options[i + 1];
                --n;
            }
            for (int i = 0; i < n; ++i) rc.eventData[i] = options[i];
            set_page(rc, 0, n);
            break;
        }
        case EV_WHISPERING_HOLLOW:
            // CalculateVars: Gold 35 + Rng.NextInt(-9, 10).
            rc.eventData[0] = 35 + rc.eventRng.next_int_range(-9, 10);
            set_page(rc, 0, 2);
            break;
        case EV_WOOD_CARVINGS:
        case EV_ZEN_WEAVER:
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
        case EV_STONE_OF_ALL_TIME:
        case EV_HUNGRY_FOR_MUSHROOMS:
        case EV_REFLECTIONS:
        case EV_SPIRIT_GRAFTER:
            set_page(rc, 0, 2);
            if (eventId == EV_STONE_OF_ALL_TIME)
                rc.eventData[0] = rc.potionCount ? rc.eventRng.next_int(0, rc.potionCount - 1) : -1;
            break;
        case EV_WELCOME_TO_WONGOS:
            // GenerateInitialOptions pulls the featured rare (shop-allowed) from
            // the front of the player's bag whether or not it is bought.
            rc.eventData[0] = static_cast<int>(rc.pull_relic(Rarity::RARE, false, false, nullptr, 0, true));
            set_page(rc, 0, 4);
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
        case EV_WHISPERING_HOLLOW:
            if (option == 0 && free_event_potion_rewards(rc) < 2) return false;
            if (option == 1) { additions = 1; removals = transformable_deck_count(rc) > 0 ? 1 : 0; }
            break;
        case EV_WOOD_CARVINGS:
            // SNAKE is a locked option when no card can take Slither.
            if (option == 1) return deck_can_enchant(rc, EnchantmentId::SLITHER);
            additions = 1;
            removals = deck_has_basic_transformable(rc) ? 1 : 0;
            break;
        case EV_BUGSLAYER:
        case EV_INFESTED_AUTOMATON: additions = 1; break;
        case EV_COLORFUL_PHILOSOPHERS:
            if (rc.free_card_reward_slots() < 3) return false;
            break;
        case EV_ROUND_TEA_PARTY: grantsRelic = true; break;
        case EV_THE_LEGENDS_WERE_TRUE: additions = option == 0 ? 1 : 0; break;
        case EV_BYRDONIS_NEST: additions = option == 1 ? 1 : 0; break;
        case EV_DOLL_ROOM: grantsRelic = rc.eventPage == 0 ? option == 0 : true; break;
        case EV_AMALGAMATOR:
            if (!can_begin_deck_relic_choice(rc, 6, 2, option == 0 ? CardId::ULTIMATE_STRIKE
                                                                  : CardId::ULTIMATE_DEFEND, option + 1))
                return false;
            break;
        case EV_TRASH_HEAP:
            if (option == 0) grantsRelic = true; else additions = 1;
            break;
        case EV_THE_FUTURE_OF_POTIONS:
            if (rc.free_card_reward_slots() < 1 || occupied_potion_slot(rc, option) < 0) return false;
            break;
        case EV_COLOSSAL_FLOWER: grantsRelic = rc.eventData[0] == 2 && option == 1; break;
        case EV_FIELD_OF_MAN_SIZED_HOLES:
            if (option == 0 && !can_begin_deck_relic_choice(rc, 6, 2, CardId::NORMALITY)) return false;
            break;
        case EV_SYMBIOTE:
            if (option == 0) return deck_can_enchant(rc, EnchantmentId::CORRUPTED);  // APPROACH_LOCKED
            additions = 1;
            removals = transformable_deck_count(rc) > 0 ? 1 : 0;
            break;
        case EV_GRAVE_OF_THE_FORGOTTEN:
            if (option == 0) {
                if (!deck_can_enchant(rc, EnchantmentId::SOULS_POWER)) return false;  // CONFRONT_LOCKED
                additions = 1;  // Decay
            } else grantsRelic = true;
            break;
        case EV_ENDLESS_CONVEYOR:
            if (option == 0) {
                if (rc.gold < 40) return false;  // LOCKED (even for the Golden Fysh)
                switch (rc.eventData[1]) {
                    case DISH_JELLY_LIVER: additions = 1; removals = transformable_deck_count(rc) > 0 ? 1 : 0; break;
                    case DISH_FRIED_EEL: case DISH_SEAPUNK_SALAD: additions = 1; break;
                    case DISH_SUSPICIOUS_CONDIMENT: if (free_event_potion_rewards(rc) < 1) return false; break;
                    default: break;
                }
            }
            break;
        case EV_TINKER_TIME: additions = rc.eventPage == 2 ? 1 : 0; break;
        case EV_PUNCH_OFF:
            if (rc.eventPage == 0 && option == 0) { additions = 1; grantsRelic = true; }  // Injury + relic
            break;
        case EV_FAKE_MERCHANT:
            if (option < 6) {
                // A sold slot is empty; no merchant discounts apply in an event room.
                if (!rc.eventRelics[option] || rc.gold < rc.eventData[option]) return false;
                grantsRelic = true;
            }
            break;
        case EV_WAR_HISTORIAN_REPY:
            grantsRelic = true;
            if (free_event_potion_rewards(rc) < 2) return false;
            break;
        case EV_CRYSTAL_SPHERE:
            // Worst case: one Doubt (curse item, plus Debt for the payment plan),
            // three card rewards and the item rewards.
            additions = option == 1 ? 2 : 1;
            if (rc.free_card_reward_slots() < 3 || free_event_potion_rewards(rc) < 3) return false;
            break;
        case EV_TRIAL:
            if (rc.eventPage == 2) {
                // Verdict page: [0] guilty, [1] innocent, per case.
                const int c = rc.eventData[0];
                if (c == 0 && option == 0) { additions = 1; grantsRelic = true; }               // Regret + 2 relics
                if (c == 0 && option == 1 && !can_begin_deck_relic_choice(rc, 9, 2, CardId::INVALID)) return false;
                if (c == 0 && option == 1) additions = 1;                                         // Shame
                if (c == 1 && option == 1) additions = 1;                                         // Regret
                if (c == 2) {
                    additions = 1;                                                                // Doubt
                    if (option == 0 && rc.free_card_reward_slots() < 2) return false;
                    if (option == 1 && !can_begin_deck_relic_choice(rc, 7, 2)) return false;
                }
            }
            break;
        case EV_RELIC_TRADER:
            // A trade is net zero; PROCEED (no tradable relics) grants nothing.
            if (rc.eventData[3] > 0 && relic_slot_of(rc, rc.eventData[option]) < 0) return false;
            break;
        case EV_RANWID_THE_ELDER:
            if (option == 0 && (rc.eventData[0] < 0 || occupied_potion_slot(rc, rc.eventData[0]) < 0)) return false;
            if (option == 2 && (rc.eventData[1] < 0 || relic_slot_of(rc, rc.eventData[1]) < 0)) return false;
            grantsRelic = true;  // option 2 removes one and obtains two: net +1
            break;
        case EV_SELF_HELP_BOOK:
            if (rc.eventChoiceCount == 3) {
                const EnchantmentId e[3] = {EnchantmentId::SHARP, EnchantmentId::NIMBLE, EnchantmentId::SWIFT};
                const CardType t[3] = {CardType::ATTACK, CardType::SKILL, CardType::POWER};
                if (!deck_can_enchant_type(rc, e[option], t[option])) return false;  // *_LOCKED
            }
            break;
        case EV_TEA_MASTER:
            // Bone/Ember Tea are locked below 50/150 gold.
            if ((option == 0 && rc.gold < 50) || (option == 1 && rc.gold < 150)) return false;
            grantsRelic = true;
            break;
        case EV_LUMINOUS_CHOIR:
            if (option == 0 && !can_begin_deck_relic_choice(rc, 6, 2, CardId::SPORE_MIND)) return false;
            if (option == 1 && rc.gold < rc.eventData[0]) return false;  // OFFER_TRIBUTE_LOCKED
            grantsRelic = option == 1;
            break;
        case EV_MORPHIC_GROVE:
            if (option == 0 && !can_begin_deck_relic_choice(rc, 7, 2)) return false;
            break;
        case EV_ZEN_WEAVER:
            // Options 1/2 are locked below their gold cost.
            if (option == 1 && rc.gold < 125) return false;
            if (option == 2 && rc.gold < 250) return false;
            additions = option == 0 ? 2 : 0;
            break;
        case EV_WELCOME_TO_WONGOS: grantsRelic = option <= 2; break;
        case EV_HUNGRY_FOR_MUSHROOMS: grantsRelic = true; break;
        case EV_NEOW: case EV_DARV: case EV_OROBAS: case EV_PAEL:
        case EV_TEZCATARA: case EV_NONUPEIPE: case EV_TANX: case EV_VAKUU:
            grantsRelic = rc.eventRelics[option] != static_cast<int>(RelicId::INVALID);
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
    // FromDeckForTransformation also excludes Quest cards.
    if (rc.eventCardSelection == 4)
        return card_can_transform_from_deck(rc.deck[index]) &&
               card_type(rc.deck[index]) != CardType::QUEST;
    if (rc.eventCardSelection == 6) return card_can_transform_from_deck(rc.deck[index]);
    if (rc.eventCardSelection == 5) return card_upgradable(rc.deck[index]);
    if (rc.eventCardSelection == 7 || rc.eventCardSelection == 8)
        return basic_transformable(rc.deck[index]);
    if (rc.eventCardSelection == 9) return card_can_enchant(rc.deck[index], EnchantmentId::SLITHER);
    const Card &c = rc.deck[index];
    switch (rc.eventCardSelection) {
        case 10: return card_can_enchant(c, EnchantmentId::PERFECT_FIT);
        case 11: return card_can_enchant(c, EnchantmentId::CORRUPTED);
        case 12: return card_can_enchant(c, EnchantmentId::SOULS_POWER);
        case 13: return card_type(c) == CardType::ATTACK && card_can_enchant(c, EnchantmentId::SHARP);
        case 14: return card_type(c) == CardType::SKILL && card_can_enchant(c, EnchantmentId::NIMBLE);
        case 15: return card_type(c) == CardType::POWER && card_can_enchant(c, EnchantmentId::SWIFT);
        default: return false;
    }
}

bool event_card_selection_valid(const RunContext &rc) {
    if (!rc.eventCardSelection) return true;
    if ((rc.screen != RunScreen::EVENT &&
         !(rc.screen == RunScreen::REWARDS && rc.rewardResumeScreen == RunScreen::EVENT)) ||
        (rc.eventCardSelection <= 2 && rc.eventId != EV_SAPPHIRE_SEED) ||
        (rc.eventCardSelection == 3 && rc.eventId != EV_STONE_OF_ALL_TIME) ||
        (rc.eventCardSelection == 4 && rc.eventId != EV_AROMA_OF_CHAOS &&
         rc.eventId != EV_WHISPERING_HOLLOW && rc.eventId != EV_SYMBIOTE &&
         rc.eventId != EV_ENDLESS_CONVEYOR) ||
        (rc.eventCardSelection == 5 && rc.eventId != EV_AROMA_OF_CHAOS && rc.eventId != EV_SPIRIT_GRAFTER) ||
        (rc.eventCardSelection == 6 && rc.eventId != EV_WELLSPRING) ||
        (rc.eventCardSelection >= 7 && rc.eventCardSelection <= 9 && rc.eventId != EV_WOOD_CARVINGS) ||
        (rc.eventCardSelection == 10 && rc.eventId != EV_FIELD_OF_MAN_SIZED_HOLES) ||
        (rc.eventCardSelection == 11 && rc.eventId != EV_SYMBIOTE) ||
        (rc.eventCardSelection == 12 && rc.eventId != EV_GRAVE_OF_THE_FORGOTTEN) ||
        (rc.eventCardSelection >= 13 && rc.eventId != EV_SELF_HELP_BOOK) ||
        rc.eventCardSelection > 15) return false;
    int count = 0;
    for (int i = 0; i < rc.deckCount; ++i) count += event_card_selectable(rc, i) ? 1 : 0;
    return count > 1;
}

void event_finish_card_grid(RunContext &rc) { finish_event(rc); }

bool event_can_remove_potions(const RunContext &rc) {
    // BeforeEventStarted sets CanUseOrRemovePotions = false for these events.
    return rc.screen != RunScreen::EVENT ||
           (rc.eventId != EV_STONE_OF_ALL_TIME && rc.eventId != EV_THE_FUTURE_OF_POTIONS &&
            rc.eventId != EV_RANWID_THE_ELDER);
}

static void finish_event_card_selection(RunContext &rc) {
    if (rc.eventId == EV_STONE_OF_ALL_TIME) rc.eventRng.next_int(0, 99);
    if (rc.eventId == EV_SPIRIT_GRAFTER) lose_hp(rc, 10);
    if (rc.eventId == EV_WELLSPRING) add_deck_card(rc, CardId::GUILTY);
    if (rc.eventId == EV_ENDLESS_CONVEYOR) { conveyor_after_dish(rc); return; }  // Jelly Liver
    // WhisperingHollow.Hug: transform first, then 9 unblockable damage.
    if (rc.eventId == EV_WHISPERING_HOLLOW) lose_hp(rc, 9);
    finish_event(rc);
}

bool event_select_card(RunContext &rc, int index) {
    if (rc.screen != RunScreen::EVENT || !event_card_selectable(rc, index)) return false;
    if (rc.eventCardSelection == 1 || rc.eventCardSelection == 5) card_apply_upgrade(rc.deck[index]);
    else if (rc.eventCardSelection == 2) card_apply_enchantment(rc.deck[index], EnchantmentId::SOWN, 1);
    else if (rc.eventCardSelection == 3) card_apply_enchantment(rc.deck[index], EnchantmentId::VIGOROUS, 8);
    else if (rc.eventCardSelection == 4) transform_event_card(rc, index, rc.eventRng);
    else if (rc.eventCardSelection == 6) remove_deck_index(rc, index);
    else if (rc.eventCardSelection == 7 || rc.eventCardSelection == 8) {
        // CardCmd.TransformTo<T>: a fresh, unupgraded card through add hooks.
        const Card replacement = rc.make_run_card(
            rc.eventCardSelection == 7 ? CardId::PECK : CardId::TORIC_TOUGHNESS, false);
        remove_deck_index(rc, index);
        if (!rc.add_card_to_deck(replacement))
            throw std::logic_error("Wood Carvings transformation exceeded deck capacity");
    } else if (rc.eventCardSelection >= 9 && rc.eventCardSelection <= 15) {
        static const EnchantmentId enchantments[7] = {EnchantmentId::SLITHER, EnchantmentId::PERFECT_FIT,
            EnchantmentId::CORRUPTED, EnchantmentId::SOULS_POWER, EnchantmentId::SHARP,
            EnchantmentId::NIMBLE, EnchantmentId::SWIFT};
        const int k = rc.eventCardSelection - 9;
        card_apply_enchantment(rc.deck[index], enchantments[k], k >= 4 ? 2 : 1);  // Self-Help Book: 2
    }
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
                add_random_shared_relic(rc, rng, false);
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
        case EV_THIS_OR_THAT: {
            if (option == 0) {
                lose_hp(rc, 6);
                if (rc.screen == RunScreen::RUN_OVER) return true;
                run_gain_gold(rc, rc.eventData[0]);
            } else {
                add_random_shared_relic(rc, rng, false);
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
                    // eventData[0] indexes Player.Potions (occupied slots only).
                    int seen = 0;
                    for (int slot = 0; slot < rc.potionSlots; ++slot) {
                        if (!rc.potions[slot] || seen++ != rc.eventData[0]) continue;
                        potion_remove_at(rc.potions, rc.potionSlots, rc.potionCount, slot);
                        break;
                    }
                    gain_max_hp(rc, 10);
                }
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
            // CheckObtainWongoBadge: purchases earn 32 / 16 / 8 account points; a
            // badge when this purchase crosses a multiple of 2000.
            auto wongoPoints = [&](int earned) {
                if (rc.nativeProgress.wongoPoints % 2000 + earned >= 2000)
                    add_relic(rc, RelicId::WONGO_CUSTOMER_APPRECIATION_BADGE);
            };
            if (option == 0 && rc.gold >= 100) {
                lose_gold(rc, 100);
                add_relic(rc, rc.pull_relic(Rarity::COMMON, false, false, nullptr, 0, true));
                wongoPoints(32);
            } else if (option == 1 && rc.gold >= 200) {
                lose_gold(rc, 200);
                add_relic(rc, static_cast<RelicId>(rc.eventData[0]));
                wongoPoints(16);
            } else if (option == 2 && rc.gold >= 300) {
                lose_gold(rc, 300);
                add_relic(rc, RelicId::WONGOS_MYSTERY_TICKET);
                wongoPoints(8);
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
                const int original = rc.deckCount;
                for (int i = 0; i < original && rc.deckCount < MAX_DECK; ++i) {
                    Card copy = rc.deck[i];
                    copy.uid = rc.allocate_card_uid();
                    rc.add_card_to_deck(copy);
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
        case EV_COLORFUL_PHILOSOPHERS: {
            // Three CardRewards (Common, Uncommon, Rare), populated in order.
            const CardPool pool = static_cast<CardPool>(rc.eventData[option]);
            for (Rarity rarity : {Rarity::COMMON, Rarity::UNCOMMON, Rarity::RARE}) {
                Card cards[3];
                const int made = make_uniform_rarity_card_reward(rc, pool, rarity, cards, 3);
                if (made <= 0 || !rc.queue_prepared_card_reward(cards, made))
                    throw std::logic_error("Colorful Philosophers reward generation failed");
            }
            finish_event(rc);
            return true;
        }
        case EV_AMALGAMATOR:
            // Remove two chosen basic Strikes/Defends, then add the Ultimate card.
            if (!begin_deck_relic_choice(rc, 6, 2, 0,
                    option == 0 ? CardId::ULTIMATE_STRIKE : CardId::ULTIMATE_DEFEND, false, option + 1))
                return false;
            finish_event(rc);
            return true;
        case EV_THE_FUTURE_OF_POTIONS: {
            const int slot = occupied_potion_slot(rc, option);
            const Rarity rarity = future_potion_card_rarity(static_cast<PotionId>(rc.potions[slot]));
            potion_remove_at(rc.potions, rc.potionSlots, rc.potionCount, slot);
            Card cards[3];
            const int made = make_uniform_rarity_card_reward(rc, CardPool::IRONCLAD, rarity, cards, 3,
                                                             rc.eventData[option]);
            if (made != 3) throw std::logic_error("The Future of Potions reward pool is too small");
            for (Card &c : cards) if (card_upgradable(c)) card_apply_upgrade(c);  // AfterGenerated
            if (!rc.queue_prepared_card_reward(cards, 3))
                throw std::logic_error("The Future of Potions reward capacity changed");
            finish_event(rc);
            return true;
        }
        case EV_FIELD_OF_MAN_SIZED_HOLES:
            if (option == 0) {
                // Resist: remove 2, then AddCursesToDeck(Normality).
                if (!begin_deck_relic_choice(rc, 6, 2, 0, CardId::NORMALITY)) return false;
                finish_event(rc);
            } else begin_event_card_selection(rc, 10);  // Enter Your Hole: Perfect Fit
            return true;
        case EV_SYMBIOTE:
            begin_event_card_selection(rc, option == 0 ? 11 : 4);  // Corrupted / transform 1
            return true;
        case EV_GRAVE_OF_THE_FORGOTTEN:
            if (option == 0) {
                add_deck_card(rc, CardId::DECAY);  // curse first, then choose
                begin_event_card_selection(rc, 12);
            } else {
                add_relic(rc, RelicId::FORGOTTEN_SOUL);
                finish_event(rc);
            }
            return true;
        case EV_FAKE_MERCHANT:
            if (option == 6) {
                finish_event(rc);
            } else {
                lose_gold(rc, rc.eventData[option]);
                add_relic(rc, static_cast<RelicId>(rc.eventRelics[option]));
                rc.eventRelics[option] = 0;  // no longer stocked
                rc.eventData[option] = 0;
            }
            return true;
        case EV_BATTLEWORN_DUMMY: {
            // EnterCombatWithoutExitingEvent(V1/V2/V3, no rewards, resume afterwards).
            static const Encounter dummies[3] = {Encounter::SETUP_BATTLEWORN_DUMMY_V1,
                Encounter::SETUP_BATTLEWORN_DUMMY_V2, Encounter::SETUP_BATTLEWORN_DUMMY_V3};
            rc.eventData[0] = option;
            rc.eventCombat = true;
            rc.eventReturnPage = 1;
            rc.combatIsElite = rc.combatIsBoss = false;
            rc.begin_combat(dummies[option]);
            return true;
        }
        case EV_THE_LANTERN_KEY:
            if (rc.eventPage == 0 && option == 0) {
                run_gain_gold(rc, 100);  // Return the key
                finish_event(rc);
            } else if (rc.eventPage == 0) {
                set_page(rc, 1, 1);      // Keep the key -> Fight
            } else {
                rc.eventCombat = true;
                rc.eventReturnPage = -1;  // shouldResumeAfterCombat: false
                rc.combatIsElite = rc.combatIsBoss = false;
                rc.begin_combat(Encounter::SETUP_MYSTERIOUS_KNIGHT);
            }
            return true;
        case EV_PUNCH_OFF:
            if (rc.eventPage == 0 && option == 0) {
                add_deck_card(rc, CardId::INJURY);  // Nab: Injury, then a relic reward
                rc.queue_random_relic_reward(rc.playerRng[PRNG_REWARDS]);
                rc.deferredCustomRewards = true;
                finish_event(rc);
            } else if (rc.eventPage == 0) {
                set_page(rc, 1, 1);  // I can take them -> Fight
            } else {
                rc.eventCombat = true;
                rc.eventReturnPage = -1;
                rc.combatIsElite = rc.combatIsBoss = false;
                rc.begin_combat(Encounter::SETUP_PUNCH_OFF);
            }
            return true;
        case EV_WAR_HISTORIAN_REPY: {
            // Page 0: cage/chest; single player with a Lantern Key gets the other
            // one as a second page. Each choice completes and removes the key(s).
            const bool cage = rc.eventPage == 0 ? option == 0 : rc.eventData[0] == 0;
            const bool firstChoice = rc.eventPage == 0;
            auto remove_keys = [&](bool all) {
                for (int i = 0; i < rc.deckCount;)
                    if (rc.deck[i].id == CardId::LANTERN_KEY) { remove_deck_index(rc, i); if (!all) break; }
                    else ++i;
            };
            remove_keys(!firstChoice);  // first choice: the first key; second: all keys
            if (cage) {
                add_relic(rc, RelicId::HISTORY_COURSE);  // FreedRepy has no other effect here
            } else {
                rc.queue_potion_rewards(2);
                for (int i = 0; i < 2; ++i) rc.queue_random_relic_reward(rc.playerRng[PRNG_REWARDS]);
                rc.deferredCustomRewards = true;
            }
            bool keyLeft = false;
            for (int i = 0; i < rc.deckCount; ++i) keyLeft |= rc.deck[i].id == CardId::LANTERN_KEY;
            if (firstChoice && keyLeft) {
                rc.eventData[0] = cage ? 1 : 0;  // the other reward
                set_page(rc, 1, 1);
            } else {
                finish_event(rc);
            }
            return true;
        }
        case EV_CRYSTAL_SPHERE:
            if (option == 0) lose_gold(rc, rc.eventData[0]);            // Uncover Future: 3 divinations
            else add_deck_card(rc, CardId::DEBT);                         // Payment Plan: 6 divinations
            crystal_sphere_begin(rc, option == 0 ? 3 : 6);
            set_page(rc, 1, 0);
            return true;
        case EV_TINKER_TIME: {
            // eventData: [0],[1] offered types (1 Attack, 2 Skill, 3 Power), then
            // [0] chosen type; [2],[3] offered riders (TinkerTime.RiderEffect).
            if (rc.eventPage == 0) {
                int types[3] = {1, 2, 3};
                shuffle_ints(types, 3, rng);  // TakeRandom(2): UnstableShuffle, Take
                rc.eventData[0] = types[0];
                rc.eventData[1] = types[1];
                set_page(rc, 1, 2);
            } else if (rc.eventPage == 1) {
                const int type = rc.eventData[option];
                static const int riders[3][3] = {{1, 2, 3}, {4, 5, 6}, {7, 8, 9}};
                int offered[3] = {riders[type - 1][0], riders[type - 1][1], riders[type - 1][2]};
                shuffle_ints(offered, 3, rng);
                rc.eventData[0] = type;
                rc.eventData[1] = 0;
                rc.eventData[2] = offered[0];
                rc.eventData[3] = offered[1];
                set_page(rc, 2, 2);
            } else {
                Card card = rc.make_run_card(CardId::MAD_SCIENCE, false);
                card.tinkerType = static_cast<std::uint8_t>(rc.eventData[0]);
                card.tinkerRider = static_cast<std::uint8_t>(rc.eventData[2 + option]);
                if (!rc.add_card_to_deck(card)) throw std::logic_error("Tinker Time exceeded deck capacity");
                finish_event(rc);
            }
            return true;
        }
        case EV_TRIAL: {
            if (rc.eventPage != 2 && option == 0) {
                // Accept (initial or after Reject): Rng.NextInt(3) picks the case.
                rc.eventData[0] = rng.next_int_exclusive(3);
                set_page(rc, 2, 2);
                return true;
            }
            if (rc.eventPage == 0) { set_page(rc, 1, 2); return true; }  // Reject
            if (rc.eventPage == 1) {
                // Double Down opens the abandon-run confirmation: the run ends.
                rc.hp = 0;
                rc.screen = RunScreen::RUN_OVER;
                rc.eventId = -1;
                return true;
            }
            const int c = rc.eventData[0];
            if (c == 0 && option == 0) {        // Merchant guilty
                add_deck_card(rc, CardId::REGRET);
                for (int i = 0; i < 2; ++i) add_relic(rc, pull_relic_from_front(rc));
            } else if (c == 0) {                // Merchant innocent: Shame, upgrade 2
                add_deck_card(rc, CardId::SHAME);
                if (!begin_deck_relic_choice(rc, 9, 2)) return false;
            } else if (c == 1 && option == 0) { // Noble guilty
                heal(rc, 10);
            } else if (c == 1) {                // Noble innocent
                add_deck_card(rc, CardId::REGRET);
                run_gain_gold(rc, 300);
            } else if (option == 0) {           // Nondescript guilty: Doubt, two card rewards
                add_deck_card(rc, CardId::DOUBT);
                for (int i = 0; i < 2; ++i) {
                    Card cards[3];
                    if (make_default_odds_card_reward(rc, cards, 3) != 3 || !rc.queue_prepared_card_reward(cards, 3))
                        throw std::logic_error("Trial card reward generation failed");
                }
            } else {                            // Nondescript innocent: Doubt, transform 2
                add_deck_card(rc, CardId::DOUBT);
                if (!begin_deck_relic_choice(rc, 7, 2, 0, CardId::INVALID, true)) return false;
            }
            finish_event(rc);
            return true;
        }
        case EV_ENDLESS_CONVEYOR: {
            if (option == 1) {
                // Observe Chef (first page) upgrades a random card; Leave does nothing.
                if (rc.eventPage == 0) {
                    const int idx = random_upgradable_index(rc, rng);
                    if (idx >= 0) card_apply_upgrade(rc.deck[idx]);
                }
                finish_event(rc);
                return true;
            }
            const int dish = rc.eventData[1];
            if (dish != DISH_GOLDEN_FYSH) lose_gold(rc, 40);
            switch (dish) {
                case DISH_CAVIAR: gain_max_hp(rc, 4); break;
                case DISH_CLAM_ROLL: heal(rc, 10); break;
                case DISH_GOLDEN_FYSH: run_gain_gold(rc, 75); break;
                case DISH_SEAPUNK_SALAD: add_deck_card(rc, CardId::FEEDING_FRENZY_CARD); break;
                case DISH_SPICY_SNAPPY: {
                    const int idx = random_upgradable_index(rc, rng);
                    if (idx >= 0) card_apply_upgrade(rc.deck[idx]);
                    break;
                }
                case DISH_FRIED_EEL: {
                    Card card;
                    if (make_default_odds_event_cards(rc, CardPool::COLORLESS, EventCardFilter::ANY, &card, 1) == 1 &&
                        !rc.add_card_to_deck(card)) throw std::logic_error("Fried Eel exceeded deck capacity");
                    break;
                }
                case DISH_SUSPICIOUS_CONDIMENT:
                    // Offered and resolved (awaited) before the next dish is rolled.
                    add_random_potion_event(rc, rc.playerRng[PRNG_REWARDS], false);
                    rc.eventData[3] = 1;
                    return true;
                case DISH_JELLY_LIVER:
                    rc.eventData[3] = 1;
                    begin_event_card_selection(rc, 4);  // transform with the event Rng
                    return true;
                default: break;
            }
            conveyor_after_dish(rc);
            return true;
        }
        case EV_RELIC_TRADER:
            if (rc.eventData[3] > 0) {
                run_remove_relic_at(rc, relic_slot_of(rc, rc.eventData[option]));
                add_relic(rc, static_cast<RelicId>(rc.eventRelics[option]));
            }
            finish_event(rc);
            return true;
        case EV_RANWID_THE_ELDER:
            if (option == 0) {
                potion_remove_at(rc.potions, rc.potionSlots, rc.potionCount,
                                 occupied_potion_slot(rc, rc.eventData[0]));  // PotionCmd.Discard
                add_relic(rc, pull_relic_from_front(rc));
            } else if (option == 1) {
                lose_gold(rc, 100);
                add_relic(rc, pull_relic_from_front(rc));
            } else {
                run_remove_relic_at(rc, relic_slot_of(rc, rc.eventData[1]));
                for (int i = 0; i < 2; ++i) add_relic(rc, pull_relic_from_front(rc));
            }
            finish_event(rc);
            return true;
        case EV_SELF_HELP_BOOK:
            if (rc.eventChoiceCount == 1) finish_event(rc);  // NO_OPTIONS
            else begin_event_card_selection(rc, 13 + option);
            return true;
        case EV_COLOSSAL_FLOWER: {
            static const int prizes[3] = {35, 75, 135};
            static const int damage[3] = {5, 6, 7};
            const int digs = rc.eventData[0];
            if (option == 0) {
                run_gain_gold(rc, prizes[digs]);  // Extract (or Extract Instead at depth 2)
                finish_event(rc);
                return true;
            }
            lose_hp(rc, damage[digs]);
            if (rc.screen == RunScreen::RUN_OVER) return true;
            if (digs == 2) {
                add_relic(rc, RelicId::POLLINOUS_CORE);
                finish_event(rc);
            } else {
                rc.eventData[0] = digs + 1;
                set_page(rc, digs + 1, 2);
            }
            return true;
        }
        case EV_JUNGLE_MAZE_ADVENTURE:
            if (option == 0) {
                // Solo Quest: StableShuffle of the three VFX entries (RNG only), 18 damage, gold.
                int fx[3] = {0, 1, 2};
                rng.shuffle(fx, 3);
                lose_hp(rc, 18);
                if (rc.screen == RunScreen::RUN_OVER) return true;
                run_gain_gold_precomputed(rc, rc.eventData[0], rc.eventData[1], true);
            } else {
                run_gain_gold_precomputed(rc, rc.eventData[2], rc.eventData[3], true);
            }
            finish_event(rc);
            return true;
        case EV_SLIPPERY_BRIDGE:
            if (option == 0) {
                remove_deck_index(rc, rc.eventData[1]);  // Overcome
                finish_event(rc);
            } else {
                lose_hp(rc, 3 + rc.eventData[0]);  // Hold On
                if (rc.screen == RunScreen::RUN_OVER) return true;
                ++rc.eventData[0];
                slippery_bridge_pick(rc);
                set_page(rc, 1, 2);
            }
            return true;
        case EV_TRASH_HEAP: {
            if (option == 0) {
                lose_hp(rc, 8);
                if (rc.screen == RunScreen::RUN_OVER) return true;
                const RelicId relics[5] = {RelicId::DARKSTONE_PERIAPT, RelicId::DREAM_CATCHER,
                    RelicId::HAND_DRILL, RelicId::MAW_BANK, RelicId::THE_BOOT};
                add_relic(rc, relics[rng.next_int_range(0, 5)]);
            } else {
                run_gain_gold(rc, 100);
                const CardId cards[10] = {CardId::CALTROPS, CardId::CLASH, CardId::DISTRACTION,
                    CardId::DUAL_WIELD, CardId::ENTRENCH, CardId::HELLO_WORLD_CARD, CardId::OUTMANEUVER,
                    CardId::REBOUND, CardId::RIP_AND_TEAR, CardId::STACK};
                add_deck_card(rc, cards[rng.next_int_range(0, 10)]);
            }
            finish_event(rc);
            return true;
        }
        case EV_DOLL_ROOM: {
            // _dolls declaration order; StableShuffle sorts by ModelId first.
            const RelicId declared[3] = {RelicId::DAUGHTER_OF_THE_WIND, RelicId::MR_STRUGGLES, RelicId::BING_BONG};
            RelicId sorted[3] = {RelicId::BING_BONG, RelicId::DAUGHTER_OF_THE_WIND, RelicId::MR_STRUGGLES};
            if (rc.eventPage == 1) {
                add_relic(rc, static_cast<RelicId>(rc.eventRelics[option]));
                finish_event(rc);
            } else if (option == 0) {
                add_relic(rc, declared[rng.next_int_range(0, 3)]);  // NextItem
                finish_event(rc);
            } else {
                lose_hp(rc, option == 1 ? 5 : 15);
                if (rc.screen == RunScreen::RUN_OVER) return true;
                rng.shuffle(sorted, 3);
                const int shown = option == 1 ? 2 : 3;
                for (int i = 0; i < shown; ++i) rc.eventRelics[i] = static_cast<int>(sorted[i]);
                set_page(rc, 1, shown);
            }
            return true;
        }
        case EV_ROUND_TEA_PARTY:
            if (rc.eventPage == 0 && option == 0) {
                // Enjoy Tea: obtain Royal Poison, then heal to full.
                add_relic(rc, RelicId::ROYAL_POISON);
                heal(rc, rc.maxHp - rc.hp);
                finish_event(rc);
            } else if (rc.eventPage == 0) {
                set_page(rc, 1, 1);  // Pick Fight -> Continue Fight
            } else {
                lose_hp(rc, 11);
                if (rc.screen == RunScreen::RUN_OVER) return true;
                add_random_shared_relic(rc, rc.playerRng[PRNG_REWARDS], false);  // PullNextRelicFromFront
                finish_event(rc);
            }
            return true;
        case EV_BYRDONIS_NEST:
            // Eat: +7 max HP. Take: Byrdonis Egg (hatched at a rest site into Byrdpip).
            if (option == 0) gain_max_hp(rc, 7);
            else add_deck_card(rc, CardId::BYRDONIS_EGG);
            finish_event(rc);
            return true;
        case EV_THE_LEGENDS_WERE_TRUE:
            if (option == 0) {
                // Nab the Map: the Spoils Map quest reshapes act 2's map.
                add_deck_card(rc, CardId::SPOILS_MAP);
            } else {
                // Slowly Find an Exit: 8 unblockable damage, then a custom
                // potion reward drawn from Ironclad + shared pools (Rewards RNG).
                lose_hp(rc, 8);
                if (rc.screen == RunScreen::RUN_OVER) return true;
                add_random_potion_event(rc, rc.playerRng[PRNG_REWARDS], false);
            }
            finish_event(rc);
            return true;
        case EV_TEA_MASTER:
            if (option == 0) { lose_gold(rc, 50); add_relic(rc, RelicId::BONE_TEA); }
            else if (option == 1) { lose_gold(rc, 150); add_relic(rc, RelicId::EMBER_TEA); }
            else add_relic(rc, RelicId::TEA_OF_DISCOURTESY);
            finish_event(rc);
            return true;
        case EV_LUMINOUS_CHOIR:
            if (option == 0) {
                // Remove two, then AddCurseToDeck<SporeMind>.
                if (!begin_deck_relic_choice(rc, 6, 2, 0, CardId::SPORE_MIND)) return false;
            } else {
                lose_gold(rc, rc.eventData[0]);
                add_random_shared_relic(rc, rc.playerRng[PRNG_REWARDS], false);  // PullNextRelicFromFront
            }
            finish_event(rc);
            return true;
        case EV_BUGSLAYER:
            add_deck_card(rc, option == 0 ? CardId::EXTERMINATE : CardId::SQUASH);
            finish_event(rc);
            return true;
        case EV_INFESTED_AUTOMATON: {
            // Study: a Power; Touch Core: canonical 0-cost, non-X. Character
            // pool, default odds, no upgrade roll; an empty pool adds nothing.
            Card card;
            if (make_default_odds_event_cards(rc, CardPool::IRONCLAD,
                    option == 0 ? EventCardFilter::POWER : EventCardFilter::CANONICAL_ZERO_COST,
                    &card, 1) == 1 && !rc.add_card_to_deck(card))
                throw std::logic_error("Infested Automaton card exceeded deck capacity");
            finish_event(rc);
            return true;
        }
        case EV_MORPHIC_GROVE:
            if (option == 0) {
                // Group: all gold is stolen, then transform 2 with the event Rng.
                lose_gold(rc, rc.gold);
                if (!begin_deck_relic_choice(rc, 7, 2, 0, CardId::INVALID, true)) return false;
            } else {
                gain_max_hp(rc, 5);
            }
            finish_event(rc);
            return true;
        case EV_WHISPERING_HOLLOW: {
            if (option == 0) {
                lose_gold(rc, rc.eventData[0]);
                if (!rc.queue_potion_rewards(2)) throw std::logic_error("Whispering Hollow potion capacity changed");
                finish_event(rc);
            } else {
                begin_event_card_selection(rc, 4);
            }
            return true;
        }
        case EV_WOOD_CARVINGS: {
            begin_event_card_selection(rc, option == 0 ? 7 : option == 1 ? 9 : 8);
            return true;
        }
        case EV_ZEN_WEAVER: {
            if (option == 0) {
                lose_gold(rc, 50);
                for (int i = 0; i < 2; ++i) add_deck_card(rc, CardId::ENLIGHTENMENT);
            } else {
                // RemoveCardsAndProceed: remove 1/2 chosen cards, then pay.
                if (!begin_deck_relic_choice(rc, 6, option)) return false;
                lose_gold(rc, option == 1 ? 125 : 250);
            }
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
        default:
            return false;
    }
}

bool crystal_sphere_cell_clickable(const RunContext &rc, int cell) {
    const CrystalSphereState &g = rc.crystalSphere;
    return rc.screen == RunScreen::EVENT && rc.eventId == EV_CRYSTAL_SPHERE && g.active &&
           g.divinations > 0 && cell >= 0 && cell < CRYSTAL_SPHERE_CELLS &&
           crystal_hidden(g, cell / CRYSTAL_SPHERE_SIZE, cell % CRYSTAL_SPHERE_SIZE);
}

// CrystalSphereMinigame.CellClicked: Big clears horizontal, vertical, diagonal
// neighbours then the cell; Small clears only the cell.
bool crystal_sphere_click(RunContext &rc, bool big, int cell) {
    if (!crystal_sphere_cell_clickable(rc, cell)) return false;
    CrystalSphereState &g = rc.crystalSphere;
    --g.divinations;
    const int x = cell / CRYSTAL_SPHERE_SIZE, y = cell % CRYSTAL_SPHERE_SIZE, last = CRYSTAL_SPHERE_SIZE - 1;
    if (big) {
        const int offsets[9][2] = {{-1, 0}, {1, 0}, {0, -1}, {0, 1}, {-1, -1}, {-1, 1}, {1, -1}, {1, 1}, {0, 0}};
        for (const auto &o : offsets) {
            const int cx = x + o[0], cy = y + o[1];
            if (cx >= 0 && cx <= last && cy >= 0 && cy <= last) crystal_clear_cell(rc, cx, cy);
        }
    } else crystal_clear_cell(rc, x, y);
    if (g.divinations == 0) {
        crystal_sphere_rewards(rc);
        g.active = false;
        finish_event(rc);
    }
    return true;
}

bool crystal_sphere_snapshot_valid(const RunContext &rc) {
    const CrystalSphereState &g = rc.crystalSphere;
    if (!snapshot_bool_event(g.active) || g.itemCount < 0 || g.itemCount > CRYSTAL_SPHERE_MAX_ITEMS ||
        g.revealedCount < 0 || g.revealedCount > g.itemCount || g.divinations < 0 || g.divinations > 6 ||
        (g.active && (rc.eventId != EV_CRYSTAL_SPHERE || g.divinations == 0)) ||
        (g.hidden[1] >> (CRYSTAL_SPHERE_CELLS - 64)) != 0) return false;
    for (int i = 0; i < g.itemCount; ++i)
        if (g.itemType[i] >= CRYSTAL_SPHERE_ITEM_TYPES || !snapshot_bool_event(g.itemPlaced[i])) return false;
    for (int c = 0; c < CRYSTAL_SPHERE_CELLS; ++c) if (g.cellItem[c] < 0 || g.cellItem[c] > g.itemCount) return false;
    for (int i = 0; i < g.revealedCount; ++i) if (g.revealed[i] < 0 || g.revealed[i] >= g.itemCount) return false;
    for (int i = 0; i < MAX_EXTRA_GOLD_REWARDS; ++i) if (rc.extraGoldRewards[i] < 0) return false;
    return true;
}

void event_resume_after_rewards(RunContext &rc) {
    if (rc.eventId == EV_ENDLESS_CONVEYOR && rc.eventData[3] == 1 && !rc.eventCardSelection)
        conveyor_after_dish(rc);  // Suspicious Condiment's potion reward closed
}

bool run_lantern_key_active(const RunContext &rc) {
    if (rc.act != 2) return false;
    for (int i = 0; i < rc.deckCount; ++i) if (rc.deck[i].id == CardId::LANTERN_KEY) return true;
    return false;
}

int event_modify_next(const RunContext &rc, int eventId) {
    return run_lantern_key_active(rc) ? EV_WAR_HISTORIAN_REPY : eventId;
}

bool foul_potion_usable_out_of_combat(const RunContext &rc) {
    if (rc.screen == RunScreen::SHOP) return true;
    return rc.screen == RunScreen::EVENT && rc.eventId == EV_FAKE_MERCHANT && !rc.eventCardSelection &&
           !rc.cardGrid.kind;
}

void event_fake_merchant_foul_potion(RunContext &rc) {
    rc.eventCombat = true;
    rc.eventReturnPage = -1;  // shouldResumeAfterCombat: false
    rc.combatIsElite = rc.combatIsBoss = false;
    rc.begin_combat(Encounter::SETUP_FAKE_MERCHANT);
}

void queue_specific_relic_reward(RunContext &rc, RelicId relic) {
    if (rc.pendingRelicCount >= MAX_REWARD_RELICS) throw std::logic_error("Relic reward capacity");
    rc.pendingRelics[rc.pendingRelicCount] = static_cast<int>(relic);
    rc.pendingRelicClaimed[rc.pendingRelicCount] = false;
    rc.pendingRelicWax[rc.pendingRelicCount] = false;
    ++rc.pendingRelicCount;
}

bool event_fight_room_rewards(const RunContext &rc) {
    return rc.eventId != EV_BATTLEWORN_DUMMY;  // BattlewornDummy encounters: ShouldGiveRewards false
}

int event_fight_gold(const RunContext &rc) {
    return rc.eventId == EV_FAKE_MERCHANT ? 300 : -1;
}

void event_fight_extra_rewards(RunContext &rc) {
    if (rc.eventId == EV_THE_LANTERN_KEY) {
        // SpecialCardReward(Lantern Key).
        const Card key = rc.make_run_card(CardId::LANTERN_KEY, false);
        if (!rc.queue_prepared_card_reward(&key, 1)) throw std::logic_error("Lantern Key reward capacity");
    } else if (rc.eventId == EV_PUNCH_OFF) {
        rc.queue_random_relic_reward(rc.playerRng[PRNG_REWARDS]);
        rc.queue_potion_rewards(1);
    } else if (rc.eventId == EV_FAKE_MERCHANT) {
        // Fake Merchant's Rug, then every relic still stocked (inventory order).
        queue_specific_relic_reward(rc, RelicId::FAKE_MERCHANTS_RUG);
        for (int i = 0; i < 6; ++i)
            if (rc.eventRelics[i]) queue_specific_relic_reward(rc, static_cast<RelicId>(rc.eventRelics[i]));
    }
}

void event_resume_after_combat(RunContext &rc) {
    if (rc.eventId == EV_BATTLEWORN_DUMMY) {
        // BattlewornDummy.Resume: nothing if the dummy escaped; otherwise V1 a
        // random potion, V2 upgrade two (StableShuffle), V3 a front-pulled relic.
        if (!rc.battle.battlewornRanOutOfTime) {
            if (rc.eventData[0] == 0) {
                add_random_potion_event(rc, rc.playerRng[PRNG_REWARDS], false);
            } else if (rc.eventData[0] == 1) {
                int candidates[MAX_DECK], n = 0;
                for (int i = 0; i < rc.deckCount; ++i) if (card_upgradable(rc.deck[i])) candidates[n++] = i;
                native_sort_card_indices(rc, candidates, n);
                rc.eventRng.shuffle(candidates, n);
                for (int i = 0; i < std::min(2, n); ++i) card_apply_upgrade(rc.deck[candidates[i]]);
            } else {
                rc.queue_random_relic_reward(rc.playerRng[PRNG_REWARDS]);
                rc.deferredCustomRewards = true;
            }
        }
        rc.eventReturnPage = -1;
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
