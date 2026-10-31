// Run event engine. Event effects follow the v0.111.0 decompilation; options
// that need a card/enchantment UI we do not model yet are marked APPROXIMATE in
// the coverage manifest (see docs/a0-ironclad-coverage.md).
#include "sts2/run.h"

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
    EV_COUNT
};

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
    {"ENDLESS_CONVEYOR", EventStatus::UNSUPPORTED, 4},
    {"PUNCH_OFF", EventStatus::UNSUPPORTED, 4},
    {"SPIRALING_WHIRLPOOL", EventStatus::IMPLEMENTED, 4},
    {"SUNKEN_TREASURY", EventStatus::IMPLEMENTED, 4},
    {"DOORS_OF_LIGHT_AND_DARK", EventStatus::IMPLEMENTED, 4},
    {"TRASH_HEAP", EventStatus::UNSUPPORTED, 4},
    {"WATERLOGGED_SCRIPTORIUM", EventStatus::IMPLEMENTED, 4},
};

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
    if (original.rarity == Rarity::EVENT || original.rarity == Rarity::ANCIENT ||
        original.rarity == Rarity::TOKEN) pool = CardPool::COLORLESS;
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
        const CardType t = card_def(rc.deck[i].id).type;
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
        if (d.type != CardType::ATTACK || (d.flags & CF_UNPLAYABLE)) continue;
        const int cost = c.upgraded ? d.costUp : d.cost;
        if (cost > 0) ++n;
    }
    return n;
}

int removable_cards(const RunContext &rc) {
    int n = 0;
    for (int i = 0; i < rc.deckCount; ++i) {
        if (rc.deck[i].id != CardId::INVALID) ++n;
    }
    return n;
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
            int curses[6];
            int cn = 0;
            curses[cn++] = static_cast<int>(RelicId::CURSED_PEARL);
            curses[cn++] = static_cast<int>(RelicId::LARGE_CAPSULE);
            curses[cn++] = static_cast<int>(RelicId::LEAFY_POULTICE);
            curses[cn++] = static_cast<int>(RelicId::PRECARIOUS_SHEARS);
            if (can_generate_bundles()) curses[cn++] = static_cast<int>(RelicId::SCROLL_BOXES);
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
            static const int pool1[3] = {
                static_cast<int>(RelicId::ELECTRIC_SHRYMP),
                static_cast<int>(RelicId::GLASS_EYE),
                static_cast<int>(RelicId::SAND_CASTLE)};
            int list[4];
            for (int i = 0; i < 3; ++i) list[i] = pool1[i];
            list[3] = rng.next_float() < 1.0f / 3.0f
                          ? static_cast<int>(RelicId::PRISMATIC_GEM)
                          : static_cast<int>(RelicId::SEA_GLASS);
            opts[0] = pick_one(list, 4, rng);
            static const int pool2[3] = {
                static_cast<int>(RelicId::ALCHEMICAL_COFFER),
                static_cast<int>(RelicId::DRIFTWOOD),
                static_cast<int>(RelicId::RADIANT_PEARL)};
            opts[1] = pick_one(pool2, 3, rng);
            // Touch of Orobas (Burning Blood -> Black Blood) and Archaic Tooth
            // (Bash -> Break) are both available to the Ironclad at run start.
            static const int pool3[2] = {
                static_cast<int>(RelicId::TOUCH_OF_OROBAS),
                static_cast<int>(RelicId::ARCHAIC_TOOTH)};
            opts[2] = pick_one(pool3, 2, rng);
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
            int list[9];
            int n = 0;
            static const int singles[7] = {
                static_cast<int>(RelicId::ASTROLABE),
                static_cast<int>(RelicId::BLACK_STAR),
                static_cast<int>(RelicId::CALLING_BELL),
                static_cast<int>(RelicId::EMPTY_CAGE),
                static_cast<int>(RelicId::PANDORAS_BOX),
                static_cast<int>(RelicId::RUNIC_PYRAMID),
                static_cast<int>(RelicId::SNECKO_EYE)};
            for (int i = 0; i < 7; ++i) list[n++] = singles[i];
            if (rc.act == 1) {
                static const int act2[2] = {static_cast<int>(RelicId::ECTOPLASM),
                                            static_cast<int>(RelicId::SOZU)};
                list[n++] = pick_one(act2, 2, rng);
            } else if (rc.act == 2) {
                static const int act3[2] = {
                    static_cast<int>(RelicId::PHILOSOPHERS_STONE),
                    static_cast<int>(RelicId::VELVET_CHOKER)};
                list[n++] = pick_one(act3, 2, rng);
            }
            shuffle_ints(list, n, rng);
            if (rng.next_bool()) {
                opts[0] = list[0];
                opts[1] = list[1];
                opts[2] = static_cast<int>(RelicId::DUSTY_TOME);
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

int event_pool_for_act_type(ActType actType, int *out, int maxOut) {
    if (actType != ActType::UNDERDOCKS)
        return event_pool_for_act(static_cast<int>(actType), out, maxOut);
    // ActModel.GenerateRooms concatenates AllEvents then AllSharedEvents in
    // model declaration order. Underdocks is an alternate FIRST act.
    const char *names[] = {
        "ABYSSAL_BATHS", "DROWNING_BEACON", "ENDLESS_CONVEYOR", "PUNCH_OFF",
        "SPIRALING_WHIRLPOOL", "SUNKEN_STATUE", "SUNKEN_TREASURY",
        "DOORS_OF_LIGHT_AND_DARK", "TRASH_HEAP", "WATERLOGGED_SCRIPTORIUM",
        "BRAIN_LEECH", "CRYSTAL_SPHERE", "DOLL_ROOM", "FAKE_MERCHANT",
        "POTION_COURIER", "RANWID_THE_ELDER", "RELIC_TRADER", "ROOM_FULL_OF_CHEESE",
        "SELF_HELP_BOOK", "SLIPPERY_BRIDGE", "STONE_OF_ALL_TIME", "SYMBIOTE",
        "TEA_MASTER", "THE_FUTURE_OF_POTIONS", "THE_LEGENDS_WERE_TRUE",
        "THIS_OR_THAT", "WAR_HISTORIAN_REPY", "WELCOME_TO_WONGOS"
    };
    int n = 0;
    for (const char *name : names) {
        for (int id = 0; id < EV_COUNT; ++id) {
            if (std::strcmp(EVENTS[id].name, name) != 0) continue;
            // Existing unsupported shared events remain an explicit content
            // coverage limitation; never substitute an Overgrowth event.
            if (EVENTS[id].status == EventStatus::UNSUPPORTED) break;
            if (out && n < maxOut) out[n] = id;
            ++n;
            break;
        }
    }
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
        case EV_STONE_OF_ALL_TIME:
        case EV_HUNGRY_FOR_MUSHROOMS:
        case EV_REFLECTIONS:
        case EV_SPIRIT_GRAFTER:
            set_page(rc, 0, 2);
            if (eventId == EV_STONE_OF_ALL_TIME)
                rc.eventData[0] = rc.potionCount ? rc.eventRng.next_int(0, rc.potionCount - 1) : -1;
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
    if (rc.eventCardSelection == 4 || rc.eventCardSelection == 6)
        return card_can_transform_from_deck(rc.deck[index]);
    if (rc.eventCardSelection == 5) return card_upgradable(rc.deck[index]);
    return false;
}

bool event_card_selection_valid(const RunContext &rc) {
    if (!rc.eventCardSelection) return true;
    if ((rc.screen != RunScreen::EVENT &&
         !(rc.screen == RunScreen::REWARDS && rc.rewardResumeScreen == RunScreen::EVENT)) ||
        (rc.eventCardSelection <= 2 && rc.eventId != EV_SAPPHIRE_SEED) ||
        (rc.eventCardSelection == 3 && rc.eventId != EV_STONE_OF_ALL_TIME) ||
        (rc.eventCardSelection == 4 && rc.eventId != EV_AROMA_OF_CHAOS) ||
        (rc.eventCardSelection == 5 && rc.eventId != EV_AROMA_OF_CHAOS && rc.eventId != EV_SPIRIT_GRAFTER) ||
        (rc.eventCardSelection == 6 && rc.eventId != EV_WELLSPRING) ||
        rc.eventCardSelection > 6) return false;
    int count = 0;
    for (int i = 0; i < rc.deckCount; ++i) count += event_card_selectable(rc, i) ? 1 : 0;
    return count > 1;
}

void event_finish_card_grid(RunContext &rc) { finish_event(rc); }

bool event_can_remove_potions(const RunContext &rc) {
    return rc.screen != RunScreen::EVENT || rc.eventId != EV_STONE_OF_ALL_TIME;
}

static void finish_event_card_selection(RunContext &rc) {
    if (rc.eventId == EV_STONE_OF_ALL_TIME) rc.eventRng.next_int(0, 99);
    if (rc.eventId == EV_SPIRIT_GRAFTER) lose_hp(rc, 10);
    if (rc.eventId == EV_WELLSPRING) add_deck_card(rc, CardId::GUILTY);
    finish_event(rc);
}

bool event_select_card(RunContext &rc, int index) {
    if (rc.screen != RunScreen::EVENT || !event_card_selectable(rc, index)) return false;
    if (rc.eventCardSelection == 1 || rc.eventCardSelection == 5) card_apply_upgrade(rc.deck[index]);
    else if (rc.eventCardSelection == 2) card_apply_enchantment(rc.deck[index], EnchantmentId::SOWN, 1);
    else if (rc.eventCardSelection == 3) card_apply_enchantment(rc.deck[index], EnchantmentId::VIGOROUS, 8);
    else if (rc.eventCardSelection == 4) transform_event_card(rc, index, rc.eventRng);
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
                    const int idx = rc.eventData[0];
                    for (int i = idx; i + 1 < rc.potionCount; ++i) rc.potions[i] = rc.potions[i + 1];
                    --rc.potionCount;
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
            if (option == 0 && rc.gold >= 100) {
                rc.gold -= 100;
                add_random_shared_relic(rc, rng, false, true);
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
