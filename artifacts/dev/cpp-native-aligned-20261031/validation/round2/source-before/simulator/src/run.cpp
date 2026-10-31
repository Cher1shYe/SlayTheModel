// Full-run flow: StandardActMap traversal, rooms, rewards, shops, events.
#include "sts2/run.h"

#include <cstring>
#include <stdexcept>

#include "sts2/monsters.h"
#include "sts2/card_candidates.h"
#include "sts2/relic_raw_rarity.h"
#include "sts2/relics.h"

namespace sts2 {

namespace {

const char *RUN_RNG_NAMES[RNG_COUNT] = {
    "up_front", "shuffle", "unknown_map_point", "combat_card_generation",
    "combat_potion_generation", "combat_card_selection", "combat_energy_costs",
    "combat_targets", "monster_ai", "niche", "combat_orbs",
    "treasure_room_relics"};
const char *PLAYER_RNG_NAMES[PRNG_COUNT] = {"rewards", "shops", "transformations"};

bool in_reward_pool(CardId id) {
    const CardDef &d = card_def(id);
    if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY)) return false;
    if (d.rarity != Rarity::COMMON && d.rarity != Rarity::UNCOMMON && d.rarity != Rarity::RARE) {
        return false;
    }
    return d.pool == CardPool::IRONCLAD;
}

bool in_colorless_pool(CardId id) {
    const CardDef &d = card_def(id);
    if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY)) return false;
    if (d.rarity != Rarity::COMMON && d.rarity != Rarity::UNCOMMON && d.rarity != Rarity::RARE) {
        return false;
    }
    return d.pool == CardPool::COLORLESS;
}

bool pool_accepts(CardId id, bool colorless) {
    return colorless ? in_colorless_pool(id) : in_reward_pool(id);
}

CardId random_card_of_rarity(Rng &rng, Rarity want, bool colorless,
                             const CardId *excluded = nullptr, int excludedCount = 0) {
    CardId pool[static_cast<int>(CardId::COUNT)];
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardId id = static_cast<CardId>(i);
        bool alreadyPicked = false;
        for (int j = 0; j < excludedCount; ++j) alreadyPicked |= excluded[j] == id;
        if (!alreadyPicked && pool_accepts(id, colorless) && card_def(id).rarity == want)
            pool[n++] = id;
    }
    if (n == 0) return CardId::INVALID;
    return pool[rng.next_int(0, n - 1)];
}

int shop_price_value(CardId id, bool colorless, Rng &rng) {
    int base = 50;
    switch (card_def(id).rarity) {
        case Rarity::UNCOMMON: base = 75; break;
        case Rarity::RARE: base = 150; break;
        default: break;
    }
    if (colorless) base = static_cast<int>(std::lround(base * 1.15f));
    return static_cast<int>(std::lround(static_cast<float>(base) * rng.next_float(0.95f, 1.05f)));
}

int relic_merchant_cost(Rarity r) {
    switch (r) {
        case Rarity::COMMON: return 200;
        case Rarity::UNCOMMON: return 250;
        case Rarity::RARE: return 300;
        case Rarity::SPECIAL: return 225;
        default: return 999;
    }
}

int apply_merchant_discount(const RunContext &rc, int price) {
    // MerchantEntry.Cost applies decimal multipliers and truncates once.
    // Integer fractions avoid floating point rounding at exact boundaries.
    std::int64_t numerator = std::max(0, price);
    int denominator = 1;
    if (run_has_relic(rc, RelicId::MEMBERSHIP_CARD)) denominator *= 2;
    if (run_has_relic(rc, RelicId::THE_COURIER)) {
        numerator *= 4;
        denominator *= 5;
    }
    return static_cast<int>(numerator / denominator);
}

bool acquire_card(RunContext &rc, Card card) {
    const CardType type = card_def(card.id).type;
    if (!card.upgraded &&
        ((type == CardType::ATTACK && run_has_relic(rc, RelicId::MOLTEN_EGG)) ||
         (type == CardType::SKILL && run_has_relic(rc, RelicId::TOXIC_EGG)) ||
         (type == CardType::POWER && run_has_relic(rc, RelicId::FROZEN_EGG)))) {
        card_apply_upgrade(card);
    }
    return rc.add_card_to_deck(card);
}

// Relic drop: implemented, unowned, shared/Ironclad, matching rarity.
RelicId random_shared_relic(RunContext &rc, Rng &rng, Rarity want, bool merchant = false,
                            const int *excluded = nullptr, int excludedCount = 0) {
    (void)rng;  // Item order was shuffled once when the run's bags were populated.
    return rc.pull_relic(want, merchant, false, excluded, excludedCount);
}

RelicId roll_shared_relic(RunContext &rc, Rng &rng) {
    const float roll = rng.next_float();
    Rarity want = roll < 0.5f ? Rarity::COMMON
                              : (roll < 0.83f ? Rarity::UNCOMMON : Rarity::RARE);
    RelicId id = random_shared_relic(rc, rng, want);
    if (id == RelicId::INVALID) id = random_shared_relic(rc, rng, Rarity::UNCOMMON);
    if (id == RelicId::INVALID) id = random_shared_relic(rc, rng, Rarity::COMMON);
    if (id == RelicId::INVALID) id = random_shared_relic(rc, rng, Rarity::RARE);
    if (id == RelicId::INVALID) id = random_shared_relic(rc, rng, Rarity::SPECIAL);
    return id;
}

RelicId random_event_relic(RunContext &rc, Rng &rng) {
    int pool[static_cast<int>(RelicId::COUNT)];
    int n = 0;
    for (int i = 1; i < static_cast<int>(RelicId::COUNT); ++i) {
        const RelicId id = static_cast<RelicId>(i);
        if (!relic_implemented(id)) continue;
        if (relic_def(id).pool != RelicPool::EVENT) continue;
        if (run_has_relic(rc, id)) continue;
        pool[n++] = i;
    }
    if (n == 0) return RelicId::INVALID;
    return static_cast<RelicId>(pool[rng.next_int(0, n - 1)]);
}

bool visited_node(const RunContext &rc, int idx) {
    if (idx < 0 || idx >= 64) return false;
    return (rc.visitedLo >> idx) & 1u;
}

void mark_visited(RunContext &rc, int idx) {
    if (idx >= 0 && idx < 64) rc.visitedLo |= (1ull << idx);
    else if (idx >= 64 && idx < 128) rc.visitedHi |= (1ull << (idx - 64));
}

void refill_shop_card(RunContext &rc, int index) {
    if (index < 0 || index >= rc.shopCount) return;
    Rng &shops = rc.playerRng[PRNG_SHOPS];
    const CardDef old = card_def(rc.shopCards[index].id);
    const bool colorless = !in_reward_pool(rc.shopCards[index].id);
    Rng &rewards = rc.playerRng[PRNG_REWARDS];
    Rarity rarity = old.rarity;
    if (!colorless) {
        const float roll = rewards.next_float();
        const float threshold = (rc.ascension >= 7 ? 0.045f : 0.09f) + rc.cardRarityOdds;
        rarity = roll < threshold ? Rarity::RARE
                                 : (roll < threshold + 0.37f ? Rarity::UNCOMMON : Rarity::COMMON);
    }
    CardId id = CardId::INVALID;
    while (id == CardId::INVALID) {
        int pool[static_cast<int>(CardId::COUNT)];
        int n = 0;
        for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
            const CardId candidate = static_cast<CardId>(i);
            if (!pool_accepts(candidate, colorless) || card_def(candidate).rarity != rarity ||
                (!colorless && card_def(candidate).type != old.type)) continue;
            bool stocked = false;
            for (int j = 0; j < rc.shopCount; ++j)
                if (j != index && !rc.shopSold[j] && rc.shopCards[j].id == candidate) stocked = true;
            if (!stocked) pool[n++] = i;
        }
        if (n > 0) id = static_cast<CardId>(pool[shops.next_int(0, n - 1)]);
        else if (!colorless && rarity == Rarity::COMMON) rarity = Rarity::UNCOMMON;
        else if (!colorless && rarity == Rarity::UNCOMMON) rarity = Rarity::RARE;
        else return;
    }
    (void)rewards.next_float();  // CardFactory.RollForUpgrade
    rc.shopCards[index] = rc.make_run_card(id, false);
    rc.shopBasePrices[index] = shop_price_value(id, colorless, shops);
    rc.shopPrices[index] = apply_merchant_discount(rc, rc.shopBasePrices[index]);
    rc.shopSold[index] = false;
}

void refill_shop_relic(RunContext &rc, int index) {
    if (index < 0 || index >= rc.shopRelicCount) return;
    Rng &shops = rc.playerRng[PRNG_SHOPS];
    const float roll = rc.playerRng[PRNG_REWARDS].next_float();
    const Rarity rarity = roll < 0.5f ? Rarity::COMMON
                                      : (roll < 0.83f ? Rarity::UNCOMMON : Rarity::RARE);
    const RelicId id = random_shared_relic(rc, shops, rarity, true,
                                          rc.shopRelics, rc.shopRelicCount);
    if (id == RelicId::INVALID) return;
    rc.shopRelics[index] = static_cast<int>(id);
    rc.shopRelicBasePrices[index] = static_cast<int>(std::lround(
        static_cast<float>(relic_merchant_cost(rarity)) * shops.next_float(0.85f, 1.15f)));
    rc.shopRelicPrices[index] = apply_merchant_discount(rc, rc.shopRelicBasePrices[index]);
    rc.shopRelicSold[index] = false;
}

void refill_shop_potion(RunContext &rc, int index) {
    if (index < 0 || index >= rc.shopPotionCount) return;
    Rng &shops = rc.playerRng[PRNG_SHOPS];
    const float roll = shops.next_float();
    const Rarity want = roll <= 0.1f ? Rarity::RARE
                         : (roll <= 0.35f ? Rarity::UNCOMMON : Rarity::COMMON);
    int pool[static_cast<int>(PotionId::COUNT)];
    int n = 0;
    for (int i = 1; i < static_cast<int>(PotionId::COUNT); ++i) {
        const PotionDef &def = potion_def(static_cast<PotionId>(i));
        if (!def.ironclad || def.rarity != want) continue;
        bool stocked = false;
        for (int j = 0; j < rc.shopPotionCount; ++j)
            if (j != index && !rc.shopPotionSold[j] && rc.shopPotions[j] == i) stocked = true;
        if (!stocked) pool[n++] = i;
    }
    if (n == 0) return;
    const PotionId id = static_cast<PotionId>(pool[shops.next_int(0, n - 1)]);
    const Rarity rarity = potion_def(id).rarity;
    int base = 50;
    if (rarity == Rarity::UNCOMMON) base = 75;
    else if (rarity == Rarity::RARE) base = 100;
    rc.shopPotions[index] = static_cast<int>(id);
    rc.shopPotionBasePrices[index] = static_cast<int>(std::lround(
        static_cast<float>(base) * shops.next_float(0.95f, 1.05f)));
    rc.shopPotionPrices[index] = apply_merchant_discount(rc, rc.shopPotionBasePrices[index]);
    rc.shopPotionSold[index] = false;
}

void apply_new_shop_discount(RunContext &rc, RelicId acquired) {
    if (acquired != RelicId::MEMBERSHIP_CARD && acquired != RelicId::THE_COURIER) return;
    for (int i = 0; i < rc.shopCount; ++i) {
        if (!rc.shopSold[i]) {
            rc.shopPrices[i] = apply_merchant_discount(rc, rc.shopBasePrices[i]);
        }
    }
    for (int i = 0; i < rc.shopRelicCount; ++i) {
        if (!rc.shopRelicSold[i]) {
            rc.shopRelicPrices[i] = apply_merchant_discount(rc, rc.shopRelicBasePrices[i]);
        }
    }
    for (int i = 0; i < rc.shopPotionCount; ++i) {
        if (!rc.shopPotionSold[i]) {
            rc.shopPotionPrices[i] = apply_merchant_discount(rc, rc.shopPotionBasePrices[i]);
        }
    }
    if (!rc.removalUsed) {
        rc.removalPrice = apply_merchant_discount(rc, rc.removalBasePrice);
    }
}

// GrabBag.GrabAndRemove samples from the current bag by weight (all
// encounter weights are 1), retries rejected draws, and preserves order when
// removing. Refill occurs only after the bag is exhausted.
int take_encounter(Rng &rng, const int *pool, int poolCount,
                   int *remaining, int &remainingCount, int previous) {
    if (poolCount <= 0) return -1;
    if (remainingCount == 0) {
        for (int i = 0; i < poolCount; ++i) remaining[i] = pool[i];
        remainingCount = poolCount;
    }
    bool hasEligible = false;
    for (int i = 0; i < remainingCount; ++i) {
        if (remaining[i] != previous &&
            !encounters_share_tags(static_cast<Encounter>(remaining[i]),
                                   static_cast<Encounter>(previous))) {
            hasEligible = true;
            break;
        }
    }
    int pick;
    do {
        pick = static_cast<int>(rng.next_double() * remainingCount);
    } while (hasEligible && (remaining[pick] == previous ||
             encounters_share_tags(static_cast<Encounter>(remaining[pick]),
                                   static_cast<Encounter>(previous))));
    const int result = remaining[pick];
    for (int i = pick + 1; i < remainingCount; ++i) remaining[i - 1] = remaining[i];
    --remainingCount;
    return result;
}

void erase_relic_from_bag(RelicBagState &bag, RelicId id) {
    for (int rarity = 0; rarity < RELIC_BAG_SLOTS; ++rarity) {
        for (int i = 0; i < bag.counts[rarity];) {
            if (bag.entries[rarity][i] != static_cast<std::uint16_t>(id)) {
                ++i;
                continue;
            }
            for (int j = i + 1; j < bag.counts[rarity]; ++j)
                bag.entries[rarity][j - 1] = bag.entries[rarity][j];
            --bag.counts[rarity];
        }
    }
}

int relic_bag_slot(Rarity rarity) {
    switch (rarity) {
        case Rarity::COMMON: return 0;
        case Rarity::UNCOMMON: return 1;
        case Rarity::RARE: return 2;
        case Rarity::SPECIAL: return 3;  // merchant Shop rarity
        default: return -1;
    }
}

int free_potion_rewards(const RunContext &r) {
    int free = MAX_REWARD_POTIONS - r.pendingPotionCount;
    for (int i = 0; i < r.pendingPotionCount; ++i) free += r.pendingPotions[i] == 0;
    return free;
}

int free_card_rewards(const RunContext &r) {
    int free = 0;
    for (int i = 0; i < MAX_CARD_REWARDS; ++i)
        if (!r.rewardCardPending[i] && i != r.activeCardReward) ++free;
    return free;
}

int free_relic_rewards(const RunContext &r) {
    int free = MAX_REWARD_RELICS - r.pendingRelicCount;
    for (int i = 0; i < r.pendingRelicCount; ++i) free += r.pendingRelicClaimed[i];
    return free;
}

bool can_obtain_relic(const RunContext &r, RelicId id, int claimCredit = 0) {
    if (id == RelicId::INVALID || !relic_implemented(id) || r.relicCount >= MAX_RELICS ||
        (id != RelicId::CIRCLET && run_has_relic(r, id))) return false;
    if (id == RelicId::CAULDRON && free_potion_rewards(r) < 5) return false;
    if (id == RelicId::LOST_COFFER && (free_potion_rewards(r) < 1 || free_card_rewards(r) < 1)) return false;
    if (id == RelicId::GLASS_EYE && free_card_rewards(r) < 5) return false;
    if (id == RelicId::SCROLL_BOXES && !can_generate_scroll_boxes(r)) return false;
    // Do not acquire a relic then strand its mandatory choice at fixed storage
    // capacity. As elsewhere in this bounded engine, reject before mutation.
    switch (id) {
        case RelicId::ASTROLABE: if (!can_begin_deck_relic_choice(r, 8, 3)) return false; break;
        case RelicId::NEW_LEAF: if (!can_begin_deck_relic_choice(r, 7, 1)) return false; break;
        case RelicId::BIIIG_HUG: if (!can_begin_deck_relic_choice(r, 6, 4)) return false; break;
        case RelicId::EMPTY_CAGE:
        case RelicId::PRECARIOUS_SHEARS: if (!can_begin_deck_relic_choice(r, 6, 2)) return false; break;
        case RelicId::PRECISE_SCISSORS: if (!can_begin_deck_relic_choice(r, 6, 1)) return false; break;
        case RelicId::PRESERVED_FOG:
            if (!can_begin_deck_relic_choice(r, 6, 3, CardId::FOLLY)) return false;
            break;
        default: break;
    }
    if (id == RelicId::CALLING_BELL &&
        (free_relic_rewards(r) + claimCredit < 3 ||
         r.deckCount > MAX_DECK - (run_has_relic(r, RelicId::BING_BONG) ? 2 : 1))) return false;
    return true;
}

void activate_custom_rewards(RunContext &r) {
    if (!r.deferredCustomRewards) return;
    r.deferredCustomRewards = false;
    if (r.screen != RunScreen::REWARDS) {
        r.rewardResumeScreen = r.screen;
        r.screen = RunScreen::REWARDS;
    }
}

void clear_custom_rewards(RunContext &r) {
    r.pendingPotionCount = 0;
    for (int &p : r.pendingPotions) p = 0;
    for (int i = 0; i < MAX_CARD_REWARDS; ++i) {
        r.rewardCardPending[i] = false;
        r.rewardCardCounts[i] = 0;
    }
    r.activeCardReward = -1;
    r.rewardResumeScreen = RunScreen::MAP;
    r.deferredCustomRewards = false;
}

struct ActionRewardGuard {
    RunContext &run;
    bool previous;
    explicit ActionRewardGuard(RunContext &r) : run(r), previous(r.processingAction) {
        run.processingAction = true;
    }
    ~ActionRewardGuard() {
        run.processingAction = previous;
        if (!previous) activate_custom_rewards(run);
    }
};

void finish_card_reward(RunContext &r) {
    if (r.activeCardReward >= 0 && r.activeCardReward < MAX_CARD_REWARDS)
        r.rewardCardPending[r.activeCardReward] = false;
    r.activeCardReward = -1;
    r.pendingCardReward = false;
    for (bool pending : r.rewardCardPending) r.pendingCardReward |= pending;
    r.rewardReturnToRewards = false;
    r.screen = RunScreen::REWARDS;
}

}  // namespace

const char *room_name(RoomType r) {
    switch (r) {
        case RoomType::MONSTER: return "MONSTER";
        case RoomType::ELITE: return "ELITE";
        case RoomType::EVENT: return "EVENT";
        case RoomType::REST: return "REST";
        case RoomType::SHOP: return "SHOP";
        case RoomType::TREASURE: return "TREASURE";
        case RoomType::BOSS: return "BOSS";
    }
    return "?";
}

std::uint16_t RunContext::allocate_card_uid() {
    for (int attempt = 0; attempt < 65536; ++attempt) {
        const std::uint16_t uid = nextUid++;
        if (uid == 0 || uid == 65535) continue;
        bool used = false;
        for (int i = 0; i < deckCount && !used; ++i) used = deck[i].uid == uid;
        for (int i = 0; i < offeredCount && !used; ++i) used = offered[i].uid == uid;
        for (int i = 0; i < shopCount && !used; ++i) used = shopCards[i].uid == uid;
        for (int i = 0; i < stolenSyncCount && !used; ++i)
            used = stolenOriginalPresent[i] && stolenOriginals[i].uid == uid;
        if (cardGrid.kind == 1 || cardGrid.kind == 2 || cardGrid.kind == 5)
            for (int i = 0; i < cardGrid.count && !used; ++i) used = cardGrid.cards[i].uid == uid;
        for (int i = 0; i < MAX_CARD_REWARDS && !used; ++i)
            for (int j = 0; j < 3 && !used; ++j)
                used = rewardCards[i][j].id != CardId::INVALID && rewardCards[i][j].uid == uid;
        if (!used) return uid;
    }
    throw std::overflow_error("run card UID space exhausted");
}

Card RunContext::make_run_card(CardId id, bool upgraded) {
    Card c = make_card(id, upgraded, allocate_card_uid());
    c.bonusDamage = 0;
    return c;
}

bool RunContext::add_card_to_deck(Card c) {
    const bool duplicate = run_has_relic(*this, RelicId::BING_BONG);
    const int required = duplicate ? 2 : 1;
    if (deckCount < 0 || deckCount > MAX_DECK - required) return false;

    auto add_one = [&](const Card &card) {
        deck[deckCount++] = card;
        if (run_has_relic(*this, RelicId::LUCKY_FYSH)) run_gain_gold(*this, 15);
        if (hp > 0 && run_has_relic(*this, RelicId::BOOK_OF_FIVE_RINGS)) {
            ++cardsAdded;
            if (cardsAdded % 5 == 0) hp = std::min(maxHp, hp + 20);
        }
        if (card_def(card.id).type == CardType::CURSE &&
            run_has_relic(*this, RelicId::DARKSTONE_PERIAPT)) {
            maxHp += 6;
            hp = std::min(maxHp, hp + 6);
        }
    };
    add_one(c);
    if (duplicate) {
        Card clone = c;
        // The clone is a separate card entity, even if a caller supplied an
        // explicit UID or the 16-bit allocator wrapped around.
        clone.uid = allocate_card_uid();
        add_one(clone);
    }
    return true;
}

void RunContext::init_relic_bags() {
    playerRelicBag = RelicBagState{};
    sharedRelicBag = RelicBagState{};
    for (int i = 1; i < static_cast<int>(RelicId::COUNT); ++i) {
        const RelicId id = static_cast<RelicId>(i);
        const RelicDef &def = relic_def(id);
        const int slot = relic_raw_rarity(id) - 1;
        if (slot < 0 || slot >= RELIC_BAG_SLOTS || !relic_implemented(id) ||
            (def.pool != RelicPool::SHARED && def.pool != RelicPool::IRONCLAD)) continue;
        playerRelicBag.entries[slot][playerRelicBag.counts[slot]++] = static_cast<std::uint16_t>(i);
        if (def.pool == RelicPool::SHARED)
            sharedRelicBag.entries[slot][sharedRelicBag.counts[slot]++] = static_cast<std::uint16_t>(i);
    }
    // The shared bag is populated before the player bag using UpFront.
    for (RelicBagState *bag : {&sharedRelicBag, &playerRelicBag}) {
        for (int slot = 0; slot < RELIC_BAG_SLOTS; ++slot)
            runRng[RNG_UP_FRONT].shuffle(bag->entries[slot], bag->counts[slot]);
    }
    relicBagsInitialized = true;
}

RelicId RunContext::pull_relic(Rarity rarity, bool fromBack, bool shared,
                               const int *blacklist, int blacklistCount) {
    if (!relicBagsInitialized || blacklistCount < 0 || (blacklistCount > 0 && !blacklist))
        return RelicId::INVALID;
    RelicBagState &bag = shared ? sharedRelicBag : playerRelicBag;
    int slot = relic_bag_slot(rarity);
    while (slot >= 0) {
        // Shared bag may refresh its original pool; the player's bag never does.
        if (shared && bag.counts[slot] == 0) {
            for (int i = 1; i < static_cast<int>(RelicId::COUNT); ++i) {
                const RelicId id = static_cast<RelicId>(i);
                if (relic_def(id).pool == RelicPool::SHARED && relic_implemented(id) &&
                    relic_raw_rarity(id) == slot + 1 && !run_has_relic(*this, id))
                    bag.entries[slot][bag.counts[slot]++] = static_cast<std::uint16_t>(i);
            }
        }
        int pos = fromBack ? bag.counts[slot] - 1 : 0;
        while (pos >= 0 && pos < bag.counts[slot]) {
            const RelicId id = static_cast<RelicId>(bag.entries[slot][pos]);
            bool excluded = fromBack && (id == RelicId::THE_COURIER || id == RelicId::OLD_COIN);
            for (int i = 0; i < blacklistCount; ++i)
                excluded |= blacklist[i] == static_cast<int>(id);
            const bool allowed = !excluded && !run_has_relic(*this, id) && run_relic_allowed(*this, id);
            if (allowed || !fromBack) {
                for (int i = pos + 1; i < bag.counts[slot]; ++i)
                    bag.entries[slot][i - 1] = bag.entries[slot][i];
                --bag.counts[slot];
            }
            if (allowed) {
                if (!shared) erase_relic_from_bag(sharedRelicBag, id);
                return id;
            }
            if (fromBack) --pos;
        }
        // The reference falls back Shop -> Common -> Uncommon -> Rare.
        slot = slot == 3 ? 0 : (slot == 0 ? 1 : (slot == 1 ? 2 : -1));
    }
    // RelicFactory uses a stackable, effect-free Circlet when the bag is empty.
    return RelicId::CIRCLET;
}

void RunContext::init_seed(const std::string &seedText, int ascensionLevel) {
    const auto canonical = Rng::canonicalize_seed(seedText);
    init(Rng::deterministic_hash_code(std::string_view(canonical)), ascensionLevel);
}

void RunContext::init(std::uint64_t seedValue, int ascensionLevel) {
    *this = RunContext();
    seed = seedValue;
    ascension = ascensionLevel;
    for (int i = 0; i < RNG_COUNT; ++i) runRng[i] = Rng(seed, RUN_RNG_NAMES[i]);
    // Current native uses the player SLOT, not NetId. Single-player slot is 0.
    for (int i = 0; i < PRNG_COUNT; ++i) {
        playerRng[i] = Rng(seed, PLAYER_RNG_NAMES[i]);
    }
    init_relic_bags();
    // The shared ancients (Darv) are allocated to acts 2/3 before any act's
    // rooms are generated (C# RunManager.GenerateRooms).
    event_plan_shared_ancients(*this);
    hp = 80;
    maxHp = 80;
    gold = 99;
    if (ascension >= 4) potionSlots = BASE_POTION_SLOTS - 1;
    act = 0;
    actFloor = 0;
    floor = 0;
    screen = RunScreen::MAP;
    add_relic(RelicId::BURNING_BLOOD);
    for (int i = 0; i < 5; ++i) add_card_to_deck(make_run_card(CardId::STRIKE_IRONCLAD, false));
    for (int i = 0; i < 4; ++i) add_card_to_deck(make_run_card(CardId::DEFEND_IRONCLAD, false));
    add_card_to_deck(make_run_card(CardId::BASH, false));
    if (ascension >= 5) add_card_to_deck(make_run_card(CardId::ASCENDERS_BANE, false));
    start_act(0);
}

void RunContext::roll_act_rooms() {
    normalBagN = 0;
    normalBagPos = 0;
    eliteBagN = 0;
    eliteBagPos = 0;
    eventBagN = 0;
    eventBagPos = 0;

    // Events are shuffled first in ActModel.GenerateRooms.
    Rng &rng = runRng[RNG_UP_FRONT];
    int ev[128];
    const int n = event_pool_for_act(act, ev, 128);
    for (int i = 0; i < n && eventBagN < 64; ++i)
        eventBag[eventBagN++] = static_cast<std::uint16_t>(ev[i]);
    for (int i = eventBagN - 1; i > 0; --i) {
        const int j = rng.next_int(0, i);
        std::swap(eventBag[i], eventBag[j]);
    }

    // Encounter bags are consumed without replacement within each cycle.
    int weak[64], weakN = 0;
    int normal[64], normalN = 0;
    int elite[32], eliteN = 0;
    int boss[16], bossN = 0;
    for (int i = 1; i < static_cast<int>(Encounter::COUNT); ++i) {
        const EncounterDef &d = encounter_def(i);
        if (d.act != act + 1 || d.key == nullptr) continue;
        const bool isElite = std::strstr(d.key, "ELITE") != nullptr;
        const bool isBoss = std::strstr(d.key, "BOSS") != nullptr;
        if (isBoss) {
            boss[bossN++] = i;
        } else if (isElite) {
            elite[eliteN++] = i;
        } else if (std::strstr(d.key, "WEAK") != nullptr) {
            weak[weakN++] = i;
        } else {
            normal[normalN++] = i;
        }
    }
    const int rooms = map.rooms;
    const int weakCount = act == 0 ? 3 : 2;
    int remaining[64];
    int remainingCount = 0;
    for (int i = 0; i < weakCount && normalBagN < 32 && weakN > 0; ++i) {
        const int previous = normalBagN > 0 ? normalBag[normalBagN - 1] : -1;
        normalBag[normalBagN++] = static_cast<std::uint16_t>(
            take_encounter(rng, weak, weakN, remaining, remainingCount, previous));
    }
    remainingCount = 0;
    for (int i = weakCount; i < rooms && normalBagN < 32; ++i) {
        if (normalN == 0) break;
        const int previous = normalBagN > 0 ? normalBag[normalBagN - 1] : -1;
        normalBag[normalBagN++] = static_cast<std::uint16_t>(
            take_encounter(rng, normal, normalN, remaining, remainingCount, previous));
    }
    remainingCount = 0;
    for (int i = 0; i < 15 && eliteBagN < 16 && eliteN > 0; ++i) {
        const int previous = eliteBagN > 0 ? eliteBag[eliteBagN - 1] : -1;
        eliteBag[eliteBagN++] = static_cast<std::uint16_t>(
            take_encounter(rng, elite, eliteN, remaining, remainingCount, previous));
    }
    bossEncounter = bossN > 0 ? boss[rng.next_int(0, bossN - 1)] : -1;
    // ActModel.GenerateRooms picks the Ancient last, from the same stream.
    ancientId = static_cast<std::int8_t>(event_pick_ancient(*this));
    secondBossEncounter = -1;
    if (act == MAX_ACTS - 1 && ascension >= 10 && bossN > 1) {
        int alternatives[16];
        int count = 0;
        for (int i = 0; i < bossN; ++i)
            if (boss[i] != bossEncounter) alternatives[count++] = boss[i];
        if (count > 0) secondBossEncounter = alternatives[rng.next_int(0, count - 1)];
    }
}

void RunContext::start_act(int actIndex) {
    act = actIndex;
    actFloor = 0;
    curRow = -1;
    curCol = -1;
    visitedLo = 0;
    visitedHi = 0;
    char mapName[32];
    std::snprintf(mapName, sizeof(mapName), "act_%d_map", actIndex + 1);
    Rng mapRng(seed, mapName);
    generate_act_map(map, mapRng, actIndex, ascension);
    roll_act_rooms();
    screen = RunScreen::MAP;
    // Every act begins at its Ancient node (Neow in act 1, the act 2/3 Ancient
    // otherwise); entering it opens the event.
    enter_map_point(map.startIdx);
}

void RunContext::add_potion(PotionId id) {
    if (id == PotionId::INVALID || potionCount >= potionSlots) return;
    if (run_has_relic(*this, RelicId::SOZU)) return;
    potions[potionCount++] = static_cast<int>(id);
}

void RunContext::sync_potions_from_battle() {
    potionCount = std::min(battle.potionCount, potionSlots);
    for (int i = 0; i < potionCount; ++i) potions[i] = battle.potions[i];
}

bool RunContext::add_relic(RelicId id) {
    if (!can_obtain_relic(*this, id)) return false;
    relics[relicCount++] = static_cast<int>(id);
    if (relicBagsInitialized) {
        erase_relic_from_bag(playerRelicBag, id);
        erase_relic_from_bag(sharedRelicBag, id);
    }
    relics_on_obtain(*this, id);
    if (!processingAction) activate_custom_rewards(*this);
    return true;
}

bool RunContext::queue_random_relic_reward(Rng &rng, bool shared) {
    if (pendingRelicCount >= MAX_REWARD_RELICS) return false;
    const float roll = rng.next_float();
    const Rarity wanted = roll < 0.5f ? Rarity::COMMON
                           : (roll < 0.83f ? Rarity::UNCOMMON : Rarity::RARE);
    const RelicId id = pull_relic(wanted, false, shared, pendingRelics, pendingRelicCount);
    if (id == RelicId::INVALID) return false;
    pendingRelics[pendingRelicCount] = static_cast<int>(id);
    pendingRelicClaimed[pendingRelicCount] = false;
    ++pendingRelicCount;
    return true;
}

bool RunContext::queue_relic_reward(Rarity rarity) {
    int slot = 0;
    while (slot < pendingRelicCount && !pendingRelicClaimed[slot]) ++slot;
    if (slot == MAX_REWARD_RELICS) return false;
    const RelicId id = pull_relic(rarity);
    if (id == RelicId::INVALID) return false;
    if (slot == pendingRelicCount) ++pendingRelicCount;
    pendingRelics[slot] = static_cast<int>(id);
    pendingRelicClaimed[slot] = false;
    deferredCustomRewards = true;
    return true;
}

bool RunContext::queue_potion_rewards(int count) {
    int freeSlots = MAX_REWARD_POTIONS - pendingPotionCount;
    for (int i = 0; i < pendingPotionCount; ++i) freeSlots += pendingPotions[i] == 0;
    if (count < 0 || count > freeSlots) return false;
    for (int k = 0; k < count; ++k) {
        int slot = 0;
        while (slot < pendingPotionCount && pendingPotions[slot] != 0) ++slot;
        if (slot == pendingPotionCount) ++pendingPotionCount;
        pendingPotions[slot] = static_cast<int>(random_potion_out_of_combat(playerRng[PRNG_REWARDS]));
    }
    pendingPotionReward = pendingPotionCount > 0 ? pendingPotions[0] : 0;
    if (count > 0) deferredCustomRewards = true;
    return true;
}

bool RunContext::queue_card_reward(Rarity fixedRarity, bool useBaseOdds, CardPool pool) {
    if (pool != CardPool::IRONCLAD && pool != CardPool::COLORLESS) return false;
    const bool colorless = pool == CardPool::COLORLESS;
    int available = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardId id = static_cast<CardId>(i);
        if (pool_accepts(id, colorless) && (useBaseOdds || card_def(id).rarity == fixedRarity)) ++available;
    }
    if (available < 3) return false;
    int slot = 0;
    while (slot < MAX_CARD_REWARDS && (rewardCardPending[slot] || slot == activeCardReward)) ++slot;
    if (slot >= MAX_CARD_REWARDS) return false;
    Rng &rng = playerRng[PRNG_REWARDS];
    const Rng savedRng = rng;
    const std::uint16_t savedUid = nextUid;
    CardId picked[3]{};
    Card generated[3]{};
    int made = 0;
    for (int i = 0; i < 3; ++i) {
        Rarity rarity = fixedRarity;
        if (useBaseOdds) {
            const float roll = rng.next_float();
            const float rare = ascension >= 7 ? 0.0149f : 0.03f;
            rarity = roll < rare ? Rarity::RARE : (roll < 0.37f ? Rarity::UNCOMMON : Rarity::COMMON);
        }
        CardId id = random_card_of_rarity(rng, rarity, colorless, picked, made);
        // RollForRarity promotes an unavailable rarity; it does not reroll.
        if (useBaseOdds && id == CardId::INVALID && rarity == Rarity::COMMON)
            id = random_card_of_rarity(rng, Rarity::UNCOMMON, colorless, picked, made);
        if (useBaseOdds && id == CardId::INVALID && rarity != Rarity::RARE)
            id = random_card_of_rarity(rng, Rarity::RARE, colorless, picked, made);
        if (id == CardId::INVALID) { rng = savedRng; nextUid = savedUid; return false; }
        picked[made] = id;
        Card card = make_run_card(id, false);
        if (useBaseOdds) {
            const float upgradeRoll = rng.next_float();
            const float odds = card_def(id).rarity == Rarity::RARE ? 0.0f
                : act * (ascension >= 7 ? 0.125f : 0.25f);
            if (card_upgradable(card) && upgradeRoll <= odds) card_apply_upgrade(card);
        }
        generated[made++] = card;
    }
    for (int i = 0; i < made; ++i) rewardCards[slot][i] = generated[i];
    rewardCardCounts[slot] = made;
    rewardCardPending[slot] = true;
    pendingCardReward = true;
    deferredCustomRewards = true;
    return true;
}

void RunContext::sync_relics_from_battle() {
    relicCount = battle.relicCount;
    for (int i = 0; i < relicCount; ++i) {
        relics[i] = battle.relics[i];
        if (relic_aux_persistent(static_cast<RelicId>(relics[i]))) {
            relicAux[i] = battle.relicAux[i];
        }
    }
}

int RunContext::current_point_type() const {
    const int idx = map.at(curRow, curCol);
    if (idx < 0) return static_cast<int>(MapPointType::UNASSIGNED);
    return map.nodes[idx].type;
}

void RunContext::begin_combat(Encounter enc) {
    stolenSyncCount = 0;
    for (int i = 0; i < MAX_PILE; ++i) {
        stolenOriginals[i] = Card{};
        stolenOriginalPresent[i] = stolenRewardPending[i] = false;
    }
    if (enc == Encounter::INVALID) {
        enc = static_cast<Encounter>(random_encounter_for_act(act, runRng[RNG_MONSTER_AI], 0));
    }
    // No stream is consumed merely to manufacture a battle seed: init receives
    // the live RunRngSet below. These derived values only support direct
    // BattleContext callers that do not provide runRngs.
    const std::uint64_t combatSeed =
        seed ^ static_cast<std::uint32_t>((floor + 1) * 0x9E3779B9u + act);
    const std::uint64_t potionSeed =
        seed ^ static_cast<std::uint32_t>((floor + 1) * 0x85EBCA6Bu + act);
    // Pantograph.AfterRoomEntered(Boss): heal 25 when the boss fight begins,
    // before the player's HP is copied into the battle.
    if (combatIsBoss && run_has_relic(*this, RelicId::PANTOGRAPH)) {
        hp = std::min(maxHp, hp + 25);
    }
    battle.init(enc, combatSeed, deck, deckCount, ascension, hp, maxHp, relics, relicCount,
                potions, potionCount, potionSlots, run_turn1_energy(*this),
                3 + run_energy_bonus(*this), gold, potionSeed, relicAux, runRng);
    teaSetPending = false;
    nextCombatEnergy = 0;
    for (int i = 0; i < relicCount; ++i) {
        if (relics[i] == static_cast<int>(RelicId::GIRYA) && relicAux[i] > 0) {
            battle.add_player_power(PowerId::STRENGTH, relicAux[i]);
        }
    }
    if (emberTeaCombats > 0) {
        battle.add_player_power(PowerId::STRENGTH, 2);
        --emberTeaCombats;
    }
    if (nextCombatUpgradeHand) {
        for (int i = 0; i < battle.handCount; ++i) {
            if (!battle.hand[i].upgraded) battle.upgrade_card(battle.hand[i]);
        }
        nextCombatUpgradeHand = false;
    }
    if (nextCombatDazed > 0) {
        for (int i = 0; i < nextCombatDazed; ++i) {
            battle.add_card_to_draw_top(make_card(CardId::DAZED, false, battle.require_card_uid()));
        }
        nextCombatDazed = 0;
    }
    if (furCoatCombats > 0) {
        for (int i = 0; i < battle.monsterCount; ++i) {
            if (battle.monsters[i].alive) battle.monsters[i].hp = 1;
        }
        --furCoatCombats;
    }
    if (run_has_relic(*this, RelicId::GHOST_SEED)) {
        for (int i = 0; i < battle.drawCount; ++i) {
            const CardId id = battle.draw[i].id;
            if (id == CardId::STRIKE_IRONCLAD || id == CardId::DEFEND_IRONCLAD) {
                battle.draw[i].etherealThisCombat = true;
            }
        }
        for (int i = 0; i < battle.handCount; ++i) {
            const CardId id = battle.hand[i].id;
            if (id == CardId::STRIKE_IRONCLAD || id == CardId::DEFEND_IRONCLAD) {
                battle.hand[i].etherealThisCombat = true;
            }
        }
    }
    battle.clear_card_uid_reservations();
    inBattle = true;
    screen = RunScreen::COMBAT;
    // A combat can already be decided on turn 1 (Whispering Earring auto-plays
    // the opening hand, and a relic damage effect can finish the encounter
    // before the player acts). Resolve it now; leaving screen=COMBAT with no
    // legal actions stalls the run.
    if (battle.outcome != Outcome::UNDECIDED) finish_combat();
}

void RunContext::roll_card_reward(bool boss) {
    offeredCount = 0;
    rewardIsBoss = boss;
    Rng &rng = playerRng[PRNG_REWARDS];
    CardId picked[3]{};
    int guard = 0;
    while (offeredCount < 3 && guard++ < 200) {
        const bool colorlessSlot = offeredCount == 2 &&
                                   (run_has_relic(*this, RelicId::DINGY_RUG) ||
                                    run_has_relic(*this, RelicId::PRISMATIC_GEM));
        // Boss rolls consume the rarity RNG too, with 100% rare and no offset.
        const float u = rng.next_float();
        Rarity want = Rarity::RARE;
        if (!boss) {
            const float offset = cardRarityOdds;
            const float baseRare = combatIsElite ? (ascension >= 7 ? 0.05f : 0.10f)
                                                   : (ascension >= 7 ? 0.0149f : 0.03f);
            const float rareThreshold = baseRare + offset;
            const float uncommonThreshold =
                rareThreshold + (combatIsElite ? 0.40f : 0.37f);
            const bool rare = u < rareThreshold;
            const bool uncommon = !rare && u < uncommonThreshold;
            if (rare) {
                want = Rarity::RARE;
                cardRarityOdds = -0.05f;
            } else {
                want = uncommon ? Rarity::UNCOMMON : Rarity::COMMON;
                cardRarityOdds = std::min(0.4f, cardRarityOdds + (ascension >= 7 ? 0.005f : 0.01f));
            }
        } else {
            cardRarityOdds = -0.05f;
        }
        CardId id = random_card_of_rarity(rng, want, colorlessSlot, picked, offeredCount);
        if (id == CardId::INVALID && want == Rarity::COMMON)
            id = random_card_of_rarity(rng, Rarity::UNCOMMON, colorlessSlot, picked, offeredCount);
        if (id == CardId::INVALID && want != Rarity::RARE)
            id = random_card_of_rarity(rng, Rarity::RARE, colorlessSlot, picked, offeredCount);
        if (id == CardId::INVALID) continue;
        picked[offeredCount] = id;
        Card card = make_run_card(id, false);
        // Upgrade roll: chance = actIndex * 0.25 for non-rare cards.
        const float upOdds = card_def(id).rarity == Rarity::RARE
                                 ? 0.0f
                                 : static_cast<float>(act) * (ascension >= 7 ? 0.125f : 0.25f);
        const float upgradeRoll = rng.next_float();
        if (card_upgradable(card) && upgradeRoll <= upOdds) card_apply_upgrade(card);
        offered[offeredCount++] = card;
    }
    if (boss) {
        cardRarityOdds = -0.05f;
    }
    if (run_has_relic(*this, RelicId::SILVER_CRUCIBLE) && silverCrucibleUses > 0) {
        for (int i = 0; i < offeredCount; ++i) {
            if (card_upgradable(offered[i])) card_apply_upgrade(offered[i]);
        }
        --silverCrucibleUses;
    }
}

void RunContext::roll_shop() {
    shopCount = 0;
    shopRelicCount = 0;
    shopPotionCount = 0;
    removalUsed = false;
    removalBasePrice = 75 + 25 * cardShopRemovalsUsed;
    removalPrice = apply_merchant_discount(*this, removalBasePrice);
    Rng &shops = playerRng[PRNG_SHOPS];
    Rng &rewards = playerRng[PRNG_REWARDS];

    static const CardType types[5] = {CardType::ATTACK, CardType::ATTACK, CardType::SKILL,
                                      CardType::SKILL, CardType::POWER};
    const int saleIndex = shops.next_int_exclusive(5);
    CardId used[MAX_SHOP_CARDS]{};
    int usedN = 0;
    for (int i = 0; i < 5; ++i) {
        CardId id = CardId::INVALID;
        const float u = rewards.next_float();
        const float rareThreshold = (ascension >= 7 ? 0.045f : 0.09f) + cardRarityOdds;
        Rarity target = u < rareThreshold ? Rarity::RARE
                         : (u < rareThreshold + 0.37f ? Rarity::UNCOMMON : Rarity::COMMON);
        while (id == CardId::INVALID) {
            int pool[static_cast<int>(CardId::COUNT)];
            int n = 0;
            for (int c = 1; c < static_cast<int>(CardId::COUNT); ++c) {
                const CardId cid = static_cast<CardId>(c);
                if (!in_reward_pool(cid)) continue;
                if (card_def(cid).rarity != target || card_def(cid).type != types[i]) continue;
                bool dup = false;
                for (int j = 0; j < usedN; ++j) dup = dup || used[j] == cid;
                if (!dup) pool[n++] = c;
            }
            if (n > 0) id = static_cast<CardId>(pool[shops.next_int(0, n - 1)]);
            else if (target == Rarity::COMMON) target = Rarity::UNCOMMON;
            else if (target == Rarity::UNCOMMON) target = Rarity::RARE;
            else break;
        }
        if (id == CardId::INVALID) continue;
        used[usedN++] = id;
        (void)rewards.next_float();  // CardFactory.RollForUpgrade, even when not upgradable
        int price = shop_price_value(id, false, shops);
        if (i == saleIndex) price = shop_price_value(id, false, shops) / 2;
        shopCards[shopCount] = make_run_card(id, false);
        shopBasePrices[shopCount] = price;
        shopPrices[shopCount] = apply_merchant_discount(*this, price);
        shopSold[shopCount] = false;
        ++shopCount;
    }
    // Two colorless slots (uncommon, rare).
    const Rarity colorlessRarities[2] = {Rarity::UNCOMMON, Rarity::RARE};
    for (int i = 0; i < 2; ++i) {
        int pool[static_cast<int>(CardId::COUNT)];
        int n = 0;
        for (int c = 1; c < static_cast<int>(CardId::COUNT); ++c) {
            const CardId cid = static_cast<CardId>(c);
            if (!in_colorless_pool(cid)) continue;
            if (card_def(cid).rarity != colorlessRarities[i]) continue;
            bool dup = false;
            for (int j = 0; j < usedN; ++j) dup = dup || used[j] == cid;
            if (!dup) pool[n++] = c;
        }
        if (n == 0) continue;
        const CardId id = static_cast<CardId>(pool[shops.next_int(0, n - 1)]);
        used[usedN++] = id;
        (void)rewards.next_float();
        shopCards[shopCount] = make_run_card(id, false);
        shopBasePrices[shopCount] = shop_price_value(id, true, shops);
        shopPrices[shopCount] = apply_merchant_discount(*this, shopBasePrices[shopCount]);
        shopSold[shopCount] = false;
        ++shopCount;
    }

    // Relics: two rolled rarities + one shop rarity.
    for (int i = 0; i < 3; ++i) {
        Rarity want;
        if (i == 2) {
            want = Rarity::SPECIAL;
        } else {
            const float u = rewards.next_float();
            want = u < 0.5f ? Rarity::COMMON : (u < 0.83f ? Rarity::UNCOMMON : Rarity::RARE);
        }
        RelicId rid = random_shared_relic(*this, shops, want, true, shopRelics, shopRelicCount);
        if (rid == RelicId::INVALID) rid = random_shared_relic(*this, shops, Rarity::UNCOMMON, true, shopRelics, shopRelicCount);
        if (rid == RelicId::INVALID) rid = random_shared_relic(*this, shops, Rarity::COMMON, true, shopRelics, shopRelicCount);
        if (rid == RelicId::INVALID) rid = random_shared_relic(*this, shops, Rarity::RARE, true, shopRelics, shopRelicCount);
        if (rid == RelicId::INVALID) continue;
        shopRelics[shopRelicCount] = static_cast<int>(rid);
        shopRelicBasePrices[shopRelicCount] = static_cast<int>(
            std::lround(static_cast<float>(relic_merchant_cost(relic_def(rid).rarity)) *
                        shops.next_float(0.85f, 1.15f)));
        shopRelicPrices[shopRelicCount] =
            apply_merchant_discount(*this, shopRelicBasePrices[shopRelicCount]);
        shopRelicSold[shopRelicCount] = false;
        ++shopRelicCount;
    }

    // Potions: one distinct batch from the out-of-combat factory.
    PotionId potion_ids[3];
    const int potion_n = random_potions_out_of_combat(shops, potion_ids, 3);
    for (int i = 0; i < potion_n; ++i) {
        const PotionId pid = potion_ids[i];
        if (pid == PotionId::INVALID) continue;
        shopPotions[shopPotionCount] = static_cast<int>(pid);
        int base = 50;
        if (potion_def(pid).rarity == Rarity::UNCOMMON) base = 75;
        else if (potion_def(pid).rarity == Rarity::RARE) base = 100;
        shopPotionBasePrices[shopPotionCount] = static_cast<int>(
            std::lround(static_cast<float>(base) * shops.next_float(0.95f, 1.05f)));
        shopPotionPrices[shopPotionCount] =
            apply_merchant_discount(*this, shopPotionBasePrices[shopPotionCount]);
        shopPotionSold[shopPotionCount] = false;
        ++shopPotionCount;
    }
    (void)rewards;
}

void RunContext::roll_treasure() {
    clear_custom_rewards(*this);
    Rng &rewards = playerRng[PRNG_REWARDS];
    const int rawGold = rewards.next_int(42, 52);
    run_gain_gold(*this, ascension >= 3 ? rawGold * 3 / 4 : rawGold);
    pendingGoldReward = pendingRecoveredGold = pendingPotionReward = 0;
    pendingRelicCount = 0;
    pendingCardReward = rewardReturnToRewards = pendingReturnToEvent = rewardIsBoss = false;
    queue_random_relic_reward(runRng[RNG_TREASURE_ROOM_RELICS], true);
    screen = RunScreen::REWARDS;
}

int RunContext::roll_unknown_room_type() {
    // BuildRoomTypeBlacklist: shops are blacklisted after a shop room or when
    // every child of the current node is a shop (single-player rules).
    bool blacklistShop = lastPointType == static_cast<int>(MapPointType::SHOP);
    if (!blacklistShop) {
        const int idx = map.at(curRow, curCol);
        if (idx >= 0 && map.nodes[idx].childCount > 0) {
            blacklistShop = true;
            for (int i = 0; i < map.nodes[idx].childCount; ++i) {
                if (map.nodes[map.nodes[idx].children[i]].type !=
                    static_cast<int>(MapPointType::SHOP)) {
                    blacklistShop = false;
                    break;
                }
            }
        }
    }
    Rng &rng = runRng[RNG_UNKNOWN_MAP_POINT];
    const float roll = rng.next_float();
    RoomType rolled = RoomType::EVENT;
    float acc = 0.0f;
    bool done = false;
    // Insertion order of the reference dictionary: Monster, Elite, Treasure, Shop.
    const RoomType order[4] = {RoomType::MONSTER, RoomType::ELITE, RoomType::TREASURE,
                               RoomType::SHOP};
    for (const RoomType t : order) {
        float odds = 0.0f;
        switch (t) {
            case RoomType::MONSTER: odds = unknownMonsterOdds; break;
            case RoomType::ELITE: odds = unknownEliteOdds; break;
            case RoomType::TREASURE: odds = unknownTreasureOdds; break;
            case RoomType::SHOP: odds = unknownShopOdds; break;
            default: break;
        }
        if (odds < 0.0f) continue;
        if (t == RoomType::SHOP && blacklistShop) continue;
        acc += odds;
        if (roll <= acc) {
            rolled = t;
            done = true;
            break;
        }
    }
    (void)done;
    // Reset the rolled outcome, grow the others by their base odds.
    const float base[4] = {0.1f, -1.0f, 0.02f, 0.03f};
    float *odds[4] = {&unknownMonsterOdds, &unknownEliteOdds, &unknownTreasureOdds,
                      &unknownShopOdds};
    for (int i = 0; i < 4; ++i) {
        if (order[i] == RoomType::SHOP && blacklistShop) continue;
        if (rolled == order[i]) {
            *odds[i] = base[i];
        } else {
            *odds[i] += base[i];
        }
    }
    return static_cast<int>(rolled);
}

void RunContext::finish_room() {
    screen = hp > 0 ? RunScreen::MAP : RunScreen::RUN_OVER;
}

void RunContext::enter_map_point(int nodeIdx) {
    if (nodeIdx < 0 || nodeIdx >= map.pointCount) return;
    int row = -1;
    int col = -1;
    const int lastRow = map.mapLength + (map.secondBossIdx >= 0 ? 1 : 0);
    for (int r = 0; r <= lastRow && r < MAP_MAX_ROWS && row < 0; ++r) {
        for (int c = 0; c < MAP_WIDTH; ++c) {
            if (map.index[r][c] == nodeIdx) {
                row = r;
                col = c;
                break;
            }
        }
    }
    if (row < 0) return;
    curRow = static_cast<std::int8_t>(row);
    curCol = static_cast<std::int8_t>(col);
    mark_visited(*this, nodeIdx);
    actFloor = row + 1;
    ++floor;
    if (run_has_relic(*this, RelicId::MAW_BANK) && !mawBankPurchased) {
        run_gain_gold(*this, 12);
    }
    const MapPointType point = static_cast<MapPointType>(map.nodes[nodeIdx].type);
    lastPointType = static_cast<std::int8_t>(point);

    RoomType room = RoomType::MONSTER;
    switch (point) {
        case MapPointType::ANCIENT:
            event_begin(*this, event_ancient_for_act(*this), true);
            return;
        case MapPointType::UNKNOWN:
            room = static_cast<RoomType>(roll_unknown_room_type());
            break;
        case MapPointType::SHOP: room = RoomType::SHOP; break;
        case MapPointType::TREASURE: room = RoomType::TREASURE; break;
        case MapPointType::REST: room = RoomType::REST; break;
        case MapPointType::MONSTER: room = RoomType::MONSTER; break;
        case MapPointType::ELITE: room = RoomType::ELITE; break;
        case MapPointType::BOSS: room = RoomType::BOSS; break;
        default: room = RoomType::MONSTER; break;
    }

    if (point == MapPointType::UNKNOWN && run_has_relic(*this, RelicId::PLANISPHERE)) {
        hp = std::min(maxHp, hp + 4);
    }

    switch (room) {
        case RoomType::MONSTER:
            combatIsElite = false;
            combatIsBoss = false;
            ++combatsFought;
            begin_combat(static_cast<Encounter>(
                normalBagN > 0 ? normalBag[normalBagPos % normalBagN]
                               : static_cast<std::uint16_t>(Encounter::INVALID)));
            if (normalBagN > 0) ++normalBagPos;
            break;
        case RoomType::ELITE:
            combatIsElite = true;
            combatIsBoss = false;
            ++combatsFought;
            ++elitesFought;
            begin_combat(static_cast<Encounter>(
                eliteBagN > 0 ? eliteBag[eliteBagPos % eliteBagN]
                              : static_cast<std::uint16_t>(Encounter::INVALID)));
            if (eliteBagN > 0) ++eliteBagPos;
            break;
        case RoomType::BOSS:
            combatIsBoss = true;
            combatIsElite = false;
            ++combatsFought;
            ++bossesFought;
            begin_combat(static_cast<Encounter>(
                nodeIdx == map.secondBossIdx && secondBossEncounter > 0 ? secondBossEncounter
                : (bossEncounter > 0 ? bossEncounter : static_cast<int>(Encounter::INVALID))));
            break;
        case RoomType::EVENT: {
            int evt = -1;
            if (eventBagN > 0) {
                // RoomSet::EnsureNextEventIsValid examines at most one bag
                // cycle; if exhausted, the reference allows repetition.
                for (int i = 0; i < eventBagN; ++i) {
                    const int candidate = eventBag[eventBagPos % eventBagN];
                    const bool seen = candidate < 64 &&
                        ((visitedEvents >> candidate) & 1u) != 0;
                    if (!seen && event_is_allowed(*this, candidate)) break;
                    ++eventBagPos;
                }
                evt = eventBag[eventBagPos % eventBagN];
                ++eventBagPos;
                if (evt >= 0 && evt < 64) visitedEvents |= (std::uint64_t{1} << evt);
            }
            event_begin(*this, evt, false);
            break;
        }
        case RoomType::REST:
            screen = RunScreen::REST;
            break;
        case RoomType::SHOP:
            roll_shop();
            if (run_has_relic(*this, RelicId::LORDS_PARASOL)) {
                for (int i = 0; i < shopRelicCount; ++i) {
                    if (!shopRelicSold[i]) {
                        add_relic(static_cast<RelicId>(shopRelics[i]));
                        shopRelicSold[i] = true;
                    }
                }
            }
            if (run_has_relic(*this, RelicId::MEAL_TICKET)) hp = std::min(maxHp, hp + 15);
            screen = RunScreen::SHOP;
            break;
        case RoomType::TREASURE:
            if (run_has_relic(*this, RelicId::SILVER_CRUCIBLE) && !treasureSkipped) {
                treasureSkipped = true;
                finish_room();
                return;
            }
            screen = RunScreen::TREASURE;
            break;
    }
}

void RunContext::finish_combat() {
    sync_stolen_cards();
    inBattle = false;
    // Combat uses the same long-lived run streams as the reference. Persist
    // their advanced states before the next room/event draw.
    runRng[RNG_SHUFFLE] = battle.shuffleRng;
    runRng[RNG_COMBAT_CARD_GENERATION] = battle.cardGenerationRng;
    runRng[RNG_COMBAT_POTION_GENERATION] = battle.potionRng;
    runRng[RNG_COMBAT_CARD_SELECTION] = battle.cardSelectionRng;
    runRng[RNG_COMBAT_ENERGY_COSTS] = battle.energyCostRng;
    runRng[RNG_COMBAT_TARGETS] = battle.targetRng;
    runRng[RNG_MONSTER_AI] = battle.monsterAiRng;
    runRng[RNG_NICHE] = battle.nicheRng;
    sync_potions_from_battle();
    sync_relics_from_battle();
    // Seal of Gold spends real run gold during combat.
    gold = std::max(0, battle.gold);
    const bool eventFight = eventCombat;
    if (battle.outcome == Outcome::TRUNCATED) {
        hp = battle.player.hp;
        maxHp = battle.player.maxHp;
        truncated = true;
        won = false;
        screen = RunScreen::RUN_OVER;
        return;
    }
    if (battle.outcome == Outcome::PLAYER_VICTORY) {
        clear_custom_rewards(*this);
        bool hasStolenRewards = false;
        for (int i = 0; i < stolenSyncCount; ++i) {
            stolenRewardPending[i] = stolenOriginalPresent[i] && battle.theftReturned[i] &&
                                     !(combatIsBoss && act == MAX_ACTS - 1);
            hasStolenRewards |= stolenRewardPending[i];
        }
        hp = battle.player.hp;
        maxHp = battle.player.maxHp;
        pendingGoldReward = 0;
        pendingRecoveredGold = battle.recoveredStolenGold;
        pendingPotionReward = 0;
        pendingRelicCount = 0;
        for (int i = 0; i < MAX_REWARD_RELICS; ++i) {
            pendingRelics[i] = 0;
            pendingRelicClaimed[i] = false;
        }
        pendingCardReward = false;
        rewardReturnToRewards = false;
        pendingReturnToEvent = false;
        // Guilty belongs to the persistent deck. Each physical copy keeps its
        // own counter and is removed after its fifth completed combat.
        for (int i = 0; i < deckCount;) {
            Card &card = deck[i];
            if (card.id == CardId::GUILTY && ++card.guiltyCombatsSeen >= 5) {
                for (int j = i + 1; j < deckCount; ++j) deck[j - 1] = deck[j];
                --deckCount;
            } else {
                ++i;
            }
        }
        const int wongoBefore = wongoCombats;
        relics_combat_end(*this, true, combatIsBoss);
        const bool wongoDue = run_has_relic(*this, RelicId::WONGOS_MYSTERY_TICKET) &&
                               wongoBefore < 5 && wongoCombats == 5;
        Rng &rewards = playerRng[PRNG_REWARDS];
        if (eventFight) {
            eventCombat = false;
            if (wongoDue)
                for (int i = 0; i < 3; ++i) queue_random_relic_reward(rewards);
            if (pendingRelicCount > 0 || pendingRecoveredGold > 0 || hasStolenRewards) {
                pendingReturnToEvent = true;
                screen = RunScreen::REWARDS;
            } else {
                event_resume_after_combat(*this);
            }
            return;
        }
        if (combatIsBoss && act == MAX_ACTS - 1) {
            // WithRewardsFromRoom returns before appending CombatRoom extra
            // rewards for either final-act boss; modifier rewards still apply.
            pendingRecoveredGold = 0;
            const bool anotherBoss = map.secondBossIdx >= 0 &&
                                     map.at(curRow, curCol) != map.secondBossIdx;
            rewardIsBoss = !anotherBoss;
            if (wongoDue)
                for (int i = 0; i < 3; ++i) queue_random_relic_reward(rewards);
            if (pendingRelicCount > 0 || pendingRecoveredGold > 0) {
                screen = RunScreen::REWARDS;
            } else if (anotherBoss) {
                finish_room();
            } else {
                won = true;
                screen = RunScreen::RUN_OVER;
            }
            return;
        }
        int minGold = 10;
        int maxGold = 20;
        if (combatIsElite) {
            minGold = 35;
            maxGold = 45;
        } else if (combatIsBoss) {
            minGold = 100;
            maxGold = 100;
        }
        if (ascension >= 3) {
            minGold = minGold * 3 / 4;
            maxGold = maxGold * 3 / 4;
        }
        // Potion reward odds (0.4 base, +/-0.1 per roll, elite bonus).
        const bool forcePotion = run_has_relic(*this, RelicId::WHITE_BEAST_STATUE);
        const float before = potionRewardOdds;
        const float roll = rewards.next_float();
        if (roll < before || forcePotion) potionRewardOdds -= 0.1f;
        else potionRewardOdds += 0.1f;
        const float bonus = combatIsElite ? 0.125f : 0.0f;
        const bool potionDropped = forcePotion || roll < before + bonus;
        // RewardsSet rolls potion availability while building the list, then
        // populates gold, potion, cards and relics in that order.
        pendingGoldReward = rewards.next_int(minGold, maxGold);
        if (potionDropped) {
            pendingPotionReward = static_cast<int>(random_potion_out_of_combat(rewards));
            pendingPotions[0] = pendingPotionReward;
            pendingPotionCount = 1;
        }
        roll_card_reward(combatIsBoss);
        pendingCardReward = offeredCount > 0;
        if (combatIsElite) queue_random_relic_reward(rewards);
        // LavaLamp.TryModifyCardRewardOptionsLate: if no qualifying damage was
        // taken this combat, upgrade every upgradable card reward.
        if (run_has_relic(*this, RelicId::LAVA_LAMP) &&
            !battle.lavaLampTookQualifyingDamage) {
            for (int i = 0; i < offeredCount; ++i) {
                if (card_upgradable(offered[i])) card_apply_upgrade(offered[i]);
            }
        }
        if (pendingCardReward) {
            rewardCardCounts[0] = offeredCount;
            rewardCardPending[0] = true;
            for (int i = 0; i < offeredCount; ++i) rewardCards[0][i] = offered[i];
        }
        if (combatIsElite && run_has_relic(*this, RelicId::BLACK_STAR))
            queue_random_relic_reward(rewards);
        if (combatIsBoss && act == 0 && !lavaRockTriggered && run_has_relic(*this, RelicId::LAVA_ROCK)) {
            queue_random_relic_reward(rewards);
            queue_random_relic_reward(rewards);
            lavaRockTriggered = true;
        }
        if (wongoDue)
            for (int i = 0; i < 3; ++i) queue_random_relic_reward(rewards);
        screen = RunScreen::REWARDS;
    } else {
        hp = 0;
        won = false;
        screen = RunScreen::RUN_OVER;
    }
}

std::vector<int> RunContext::available_map_nodes() const {
    std::vector<int> out;
    const int idx = map.at(curRow, curCol);
    if (idx >= 0) {
        const MapNode &n = map.nodes[idx];
        for (int i = 0; i < n.childCount && i < MAP_MAX_EDGES; ++i) {
            out.push_back(n.children[i]);
        }
        std::sort(out.begin(), out.end());
        return out;
    }
    // Act start: any node in row 1.
    for (int c = 0; c < MAP_WIDTH; ++c) {
        const int v = map.at(1, c);
        if (v >= 0) out.push_back(v);
    }
    return out;
}

std::vector<RunAction> RunContext::legal_actions() const {
    std::vector<RunAction> out;
    if (cardGrid.kind) {
        if ((cardGrid.kind == 3 || ((cardGrid.kind == 5 || cardGrid.kind >= 6) && cardGrid.preview)) &&
            cardGrid.selectedCount >= cardGrid.minSelect)
            out.push_back({RunActionType::CONFIRM_GRID_CARDS, 0});
        if (cardGrid.preview) out.push_back({RunActionType::CANCEL_GRID_PREVIEW, 0});
        for (int i = 0; i < cardGrid.count; ++i)
            if (card_grid_can_select(*this, i)) out.push_back({RunActionType::SELECT_GRID_CARD, i});
        return out;
    }
    switch (screen) {
        case RunScreen::MAP:
            for (const int idx : available_map_nodes()) {
                out.push_back({RunActionType::MOVE, idx});
            }
            break;
        case RunScreen::CARD_REWARD:
            if (deckCount <= MAX_DECK - (run_has_relic(*this, RelicId::BING_BONG) ? 2 : 1))
                for (int i = 0; i < offeredCount; ++i) out.push_back({RunActionType::TAKE_CARD, i});
            out.push_back({RunActionType::SKIP_CARD, 0});
            if (run_has_relic(*this, RelicId::PAELS_WING) &&
                ((paelsWingSkips + 1) % 2 != 0 || relicCount < MAX_RELICS))
                out.push_back({RunActionType::SACRIFICE_CARD_REWARD, 0});
            break;
        case RunScreen::REST:
            out.push_back({RunActionType::REST_HEAL, 0});
            for (int i = 0; i < deckCount; ++i) {
                if (card_upgradable(deck[i])) out.push_back({RunActionType::REST_UPGRADE, i});
            }
            if (run_has_relic(*this, RelicId::SHOVEL)) out.push_back({RunActionType::REST_DIG, 0});
            if (run_has_relic(*this, RelicId::PAELS_GROWTH)) {
                int marked = 0;
                for (int i = 0; i < deckCount; ++i)
                    if (deck[i].enchantment == EnchantmentId::CLONE) ++marked;
                const int copies = run_has_relic(*this, RelicId::BING_BONG) ? 2 : 1;
                if (marked * copies <= MAX_DECK - deckCount)
                    out.push_back({RunActionType::REST_CLONE, 0});
            }
            if (run_has_relic(*this, RelicId::GIRYA)) {
                int lifts = 0;
                for (int i = 0; i < relicCount; ++i) {
                    if (relics[i] == static_cast<int>(RelicId::GIRYA)) lifts = relicAux[i];
                }
                if (lifts < 3) out.push_back({RunActionType::REST_LIFT, 0});
            }
            break;
        case RunScreen::SHOP:
            for (int i = 0; i < shopCount; ++i) {
                if (!shopSold[i] && gold >= shopPrices[i] &&
                    deckCount <= MAX_DECK - (run_has_relic(*this, RelicId::BING_BONG) ? 2 : 1)) {
                    out.push_back({RunActionType::BUY_CARD, i});
                }
            }
            for (int i = 0; i < shopRelicCount; ++i) {
                if (!shopRelicSold[i] && gold >= shopRelicPrices[i] &&
                    can_obtain_relic(*this, static_cast<RelicId>(shopRelics[i]))) {
                    out.push_back({RunActionType::BUY_RELIC, i});
                }
            }
            for (int i = 0; i < shopPotionCount; ++i) {
                if (!shopPotionSold[i] && gold >= shopPotionPrices[i] &&
                    potionCount < potionSlots && !run_has_relic(*this, RelicId::SOZU)) {
                    out.push_back({RunActionType::BUY_POTION, i});
                }
            }
            if (!removalUsed && gold >= removalPrice) {
                for (int i = 0; i < deckCount; ++i) {
                    out.push_back({RunActionType::REMOVE_CARD, i});
                }
            }
            out.push_back({RunActionType::LEAVE_SHOP, 0});
            break;
        case RunScreen::EVENT:
            if (eventCardSelection) {
                for (int i = 0; i < deckCount; ++i)
                    if (event_card_selectable(*this, i)) out.push_back({RunActionType::EVENT_SELECT_CARD, i});
            } else {
                for (int i = 0; i < event_option_count(*this); ++i)
                    if (event_option_available(*this, i)) out.push_back({RunActionType::EVENT_CHOICE, i});
            }
            break;
        case RunScreen::TREASURE:
            out.push_back({RunActionType::COLLECT, 0});
            break;
        case RunScreen::REWARDS:
            if (pendingGoldReward > 0) out.push_back({RunActionType::TAKE_GOLD_REWARD, 0});
            if (pendingRecoveredGold > 0) out.push_back({RunActionType::TAKE_GOLD_REWARD, 1});
            if (pendingPotionCount > 0) {
                for (int i = 0; i < pendingPotionCount; ++i)
                    if (pendingPotions[i] && (potionCount < potionSlots || run_has_relic(*this, RelicId::SOZU)))
                        out.push_back({RunActionType::TAKE_POTION_REWARD, i});
                for (int i = 0; i < potionCount; ++i)
                    out.push_back({RunActionType::DISCARD_POTION, i});
            }
            for (int i = 0; i < pendingRelicCount; ++i) {
                const RelicId id = static_cast<RelicId>(pendingRelics[i]);
                if (!pendingRelicClaimed[i] && can_obtain_relic(*this, id, 1))
                    out.push_back({RunActionType::TAKE_RELIC_REWARD, i});
            }
            for (int i = 0; i < MAX_CARD_REWARDS; ++i)
                if (rewardCardPending[i]) out.push_back({RunActionType::OPEN_CARD_REWARD, i});
            for (int i = 0; i < stolenSyncCount; ++i) {
                if (!stolenRewardPending[i]) continue;
                if (deckCount <= MAX_DECK - (run_has_relic(*this, RelicId::BING_BONG) ? 2 : 1))
                    out.push_back({RunActionType::TAKE_STOLEN_CARD_REWARD, i});
                out.push_back({RunActionType::SKIP_STOLEN_CARD_REWARD, i});
            }
            out.push_back({RunActionType::LEAVE_REWARDS, 0});
            break;
        case RunScreen::COMBAT:
        case RunScreen::RUN_OVER:
            break;
    }
    if (screen != RunScreen::COMBAT && screen != RunScreen::RUN_OVER && event_can_remove_potions(*this)) {
        for (int i = 0; i < potionCount; ++i) {
            const PotionDef &d = potion_def(static_cast<PotionId>(potions[i]));
            if (d.usage == PotionUsage::ANY_TIME) {
                out.push_back({RunActionType::USE_POTION, i});
            }
        }
    }
    return out;
}

bool RunContext::use_potion_out_of_combat(int idx) {
    if (!event_can_remove_potions(*this)) return false;
    if (idx < 0 || idx >= potionCount) return false;
    const PotionId id = static_cast<PotionId>(potions[idx]);
    if (potion_def(id).usage != PotionUsage::ANY_TIME) return false;
    for (int j = idx; j + 1 < potionCount; ++j) potions[j] = potions[j + 1];
    --potionCount;
    switch (id) {
        case PotionId::BLOOD_POTION:
            hp = std::min(maxHp, hp + maxHp * 20 / 100);
            break;
        case PotionId::FRUIT_JUICE:
            maxHp += 5;
            hp += 5;
            break;
        case PotionId::ENTROPIC_BREW:
            // EntropicBrew.cs: fill open slots with CreateRandomPotionOutOfCombat
            // rolls from CombatPotionGeneration; TryToProcure failure (Sozu)
            // breaks instead of spinning forever.
            while (potionCount < potionSlots) {
                Rng &prng = runRng[RNG_COMBAT_POTION_GENERATION];
                const float roll = prng.next_float();
                const Rarity want = roll <= 0.1f ? Rarity::RARE
                                    : roll <= 0.35f ? Rarity::UNCOMMON
                                                    : Rarity::COMMON;
                int pool[static_cast<int>(PotionId::COUNT)];
                int n = 0;
                for (int i = 1; i < static_cast<int>(PotionId::COUNT); ++i) {
                    const PotionDef &d = potion_def(static_cast<PotionId>(i));
                    if (!d.ironclad || d.rarity != want) continue;
                    pool[n++] = i;
                }
                if (n == 0) break;
                const PotionId next = static_cast<PotionId>(pool[prng.next_int(0, n - 1)]);
                const int before = potionCount;
                add_potion(next);
                if (potionCount == before) break;
            }
            break;
        case PotionId::FOUL_POTION:
            run_gain_gold(*this, 100);
            break;
        default:
            break;
    }
    return true;
}

void RunContext::sync_stolen_cards() {
    while (stolenSyncCount < battle.theftCount && stolenSyncCount < MAX_PILE) {
        const int slot = stolenSyncCount++;
        for (int i = 0; i < deckCount; ++i) {
            if (deck[i].uid != battle.theftUids[slot]) continue;
            stolenOriginals[slot] = deck[i];
            stolenOriginalPresent[slot] = true;
            for (int j = i + 1; j < deckCount; ++j) deck[j - 1] = deck[j];
            --deckCount;
            break;
        }
    }
}

bool RunContext::step_combat(const Action &action) {
    if (screen != RunScreen::COMBAT) return false;
    sync_stolen_cards();
    if (battle.outcome != Outcome::UNDECIDED) {
        finish_combat();
        return true;
    }
    if (!battle.step(action)) return false;
    sync_stolen_cards();
    if (battle.outcome != Outcome::UNDECIDED) finish_combat();
    return true;
}

bool RunContext::step(const RunAction &action) {
    ActionRewardGuard rewardGuard(*this);
    if (cardGrid.kind) {
        if (action.type == RunActionType::SELECT_GRID_CARD) return select_card_grid(*this, action.index);
        if (action.type == RunActionType::CONFIRM_GRID_CARDS) return confirm_card_grid(*this);
        if (action.type == RunActionType::CANCEL_GRID_PREVIEW) return cancel_card_grid_preview(*this);
        return false;
    }
    switch (action.type) {
        case RunActionType::MOVE:
            if (screen != RunScreen::MAP) return false;
            if (action.index < 0) return false;
            {
                const auto nodes = available_map_nodes();
                bool ok = false;
                for (const int n : nodes) ok = ok || n == action.index;
                if (!ok) return false;
            }
            enter_map_point(action.index);
            return true;
        case RunActionType::TAKE_CARD: {
            if (screen != RunScreen::CARD_REWARD) return false;
            if (action.index < 0 || action.index >= offeredCount) return false;
            if (!acquire_card(*this, offered[action.index])) return false;
            if (rewardReturnToRewards) {
                finish_card_reward(*this);
                return true;
            }
            if (rewardIsBoss) {
                rewardIsBoss = false;
                if (act + 1 < MAX_ACTS) {
                    start_act(act + 1);
                } else {
                    won = true;
                    screen = RunScreen::RUN_OVER;
                }
            } else {
                finish_room();
            }
            return true;
        }
        case RunActionType::SKIP_CARD:
        case RunActionType::SACRIFICE_CARD_REWARD:
            if (screen != RunScreen::CARD_REWARD) return false;
            if (action.type == RunActionType::SACRIFICE_CARD_REWARD) {
                if (!run_has_relic(*this, RelicId::PAELS_WING) ||
                    ((paelsWingSkips + 1) % 2 == 0 && relicCount >= MAX_RELICS)) return false;
                ++paelsWingSkips;
                if (paelsWingSkips % 2 == 0) add_relic(roll_shared_relic(*this, playerRng[PRNG_REWARDS]));
            }
            if (rewardReturnToRewards) {
                finish_card_reward(*this);
                return true;
            }
            if (rewardIsBoss) {
                rewardIsBoss = false;
                if (act + 1 < MAX_ACTS) {
                    start_act(act + 1);
                } else {
                    won = true;
                    screen = RunScreen::RUN_OVER;
                }
            } else {
                finish_room();
            }
            return true;
        case RunActionType::REST_HEAL: {
            if (screen != RunScreen::REST) return false;
            int heal = std::max(1, maxHp * 3 / 10);
            if (run_has_relic(*this, RelicId::REGAL_PILLOW)) heal += 15;
            if (run_has_relic(*this, RelicId::ETERNAL_FEATHER)) heal += 3 * (deckCount / 5);
            hp = std::min(maxHp, hp + heal);
            if (run_has_relic(*this, RelicId::STONE_HUMIDIFIER)) {
                maxHp += 5;
                hp += 5;
            }
            if (run_has_relic(*this, RelicId::TINY_MAILBOX) &&
                !run_has_relic(*this, RelicId::SOZU) && potionCount < potionSlots) {
                add_potion(random_potion_out_of_combat(playerRng[PRNG_REWARDS]));
            }
            if (run_has_relic(*this, RelicId::VENERABLE_TEA_SET)) teaSetPending = true;
            finish_room();
            return true;
        }
        case RunActionType::REST_UPGRADE: {
            if (screen != RunScreen::REST) return false;
            if (action.index < 0 || action.index >= deckCount) return false;
            if (!card_upgradable(deck[action.index])) return false;
            card_apply_upgrade(deck[action.index]);
            if (run_has_relic(*this, RelicId::TINY_MAILBOX) &&
                !run_has_relic(*this, RelicId::SOZU) && potionCount < potionSlots) {
                add_potion(random_potion_out_of_combat(playerRng[PRNG_REWARDS]));
            }
            if (run_has_relic(*this, RelicId::VENERABLE_TEA_SET)) teaSetPending = true;
            finish_room();
            return true;
        }
        case RunActionType::REST_CLONE: {
            if (screen != RunScreen::REST || !run_has_relic(*this, RelicId::PAELS_GROWTH)) return false;
            Card originals[MAX_DECK];
            int count = 0;
            for (int i = 0; i < deckCount; ++i)
                if (deck[i].enchantment == EnchantmentId::CLONE) originals[count++] = deck[i];
            const int copies = run_has_relic(*this, RelicId::BING_BONG) ? 2 : 1;
            if (count * copies > MAX_DECK - deckCount) return false;
            for (int i = 0; i < count; ++i) {
                originals[i].uid = allocate_card_uid();
                if (!add_card_to_deck(originals[i])) return false;
            }
            if (run_has_relic(*this, RelicId::TINY_MAILBOX) &&
                !run_has_relic(*this, RelicId::SOZU) && potionCount < potionSlots)
                add_potion(random_potion_out_of_combat(playerRng[PRNG_REWARDS]));
            if (run_has_relic(*this, RelicId::VENERABLE_TEA_SET)) teaSetPending = true;
            finish_room();
            return true;
        }
        case RunActionType::REST_DIG: {
            if (screen != RunScreen::REST) return false;
            if (!run_has_relic(*this, RelicId::SHOVEL)) return false;
            add_relic(roll_shared_relic(*this, playerRng[PRNG_REWARDS]));
            finish_room();
            return true;
        }
        case RunActionType::REST_LIFT: {
            if (screen != RunScreen::REST) return false;
            for (int i = 0; i < relicCount; ++i) {
                if (relics[i] == static_cast<int>(RelicId::GIRYA)) {
                    if (relicAux[i] >= 3) return false;
                    ++relicAux[i];
                }
            }
            finish_room();
            return true;
        }
        case RunActionType::BUY_CARD: {
            if (screen != RunScreen::SHOP) return false;
            if (action.index < 0 || action.index >= shopCount) return false;
            if (shopSold[action.index] || gold < shopPrices[action.index]) return false;
            if (deckCount > MAX_DECK - (run_has_relic(*this, RelicId::BING_BONG) ? 2 : 1)) return false;
            if (!acquire_card(*this, shopCards[action.index])) return false;
            gold -= shopPrices[action.index];
            mawBankPurchased = true;
            shopSold[action.index] = true;
            if (run_has_relic(*this, RelicId::THE_COURIER)) {
                refill_shop_card(*this, action.index);
            }
            return true;
        }
        case RunActionType::BUY_RELIC: {
            if (screen != RunScreen::SHOP) return false;
            if (action.index < 0 || action.index >= shopRelicCount) return false;
            if (shopRelicSold[action.index] || gold < shopRelicPrices[action.index]) return false;
            const RelicId acquired =
                static_cast<RelicId>(shopRelics[action.index]);
            if (!can_obtain_relic(*this, acquired)) return false;
            gold -= shopRelicPrices[action.index];
            mawBankPurchased = true;
            if (!add_relic(acquired)) return false;
            shopRelicSold[action.index] = true;
            apply_new_shop_discount(*this, acquired);
            if (run_has_relic(*this, RelicId::THE_COURIER)) {
                refill_shop_relic(*this, action.index);
            }
            return true;
        }
        case RunActionType::BUY_POTION: {
            if (screen != RunScreen::SHOP) return false;
            if (action.index < 0 || action.index >= shopPotionCount) return false;
            if (shopPotionSold[action.index] || gold < shopPotionPrices[action.index]) return false;
            if (potionCount >= potionSlots) return false;
            gold -= shopPotionPrices[action.index];
            mawBankPurchased = true;
            add_potion(static_cast<PotionId>(shopPotions[action.index]));
            shopPotionSold[action.index] = true;
            if (run_has_relic(*this, RelicId::THE_COURIER)) {
                refill_shop_potion(*this, action.index);
            }
            return true;
        }
        case RunActionType::REMOVE_CARD: {
            if (screen != RunScreen::SHOP) return false;
            if (removalUsed || gold < removalPrice) return false;
            if (action.index < 0 || action.index >= deckCount) return false;
            for (int i = action.index; i + 1 < deckCount; ++i) deck[i] = deck[i + 1];
            --deckCount;
            gold -= removalPrice;
            mawBankPurchased = true;
            removalUsed = true;
            ++cardShopRemovalsUsed;
            return true;
        }
        case RunActionType::LEAVE_SHOP:
            if (screen != RunScreen::SHOP) return false;
            finish_room();
            return true;
        case RunActionType::EVENT_CHOICE:
            if (screen != RunScreen::EVENT) return false;
            return event_choose(*this, action.index);
        case RunActionType::EVENT_SELECT_CARD:
            return event_select_card(*this, action.index);
        case RunActionType::COLLECT:
            if (screen != RunScreen::TREASURE) return false;
            roll_treasure();
            return true;
        case RunActionType::USE_POTION:
            if (screen == RunScreen::COMBAT || screen == RunScreen::RUN_OVER) return false;
            return use_potion_out_of_combat(action.index);
        case RunActionType::TAKE_GOLD_REWARD: {
            if (screen != RunScreen::REWARDS || (action.index != 0 && action.index != 1)) return false;
            int &amount = action.index == 0 ? pendingGoldReward : pendingRecoveredGold;
            if (amount <= 0) return false;
            run_gain_gold(*this, amount);
            amount = 0;
            return true;
        }
        case RunActionType::TAKE_POTION_REWARD:
            if (screen != RunScreen::REWARDS || action.index < 0 || action.index >= pendingPotionCount ||
                pendingPotions[action.index] == 0) return false;
            if (run_has_relic(*this, RelicId::SOZU)) {
                pendingPotions[action.index] = 0;
                pendingPotionReward = pendingPotions[0];
                return true;
            }
            if (potionCount >= potionSlots) return false;
            add_potion(static_cast<PotionId>(pendingPotions[action.index]));
            pendingPotions[action.index] = 0;
            pendingPotionReward = pendingPotions[0];
            return true;
        case RunActionType::TAKE_RELIC_REWARD: {
            if (screen != RunScreen::REWARDS || action.index < 0 || action.index >= pendingRelicCount ||
                pendingRelicClaimed[action.index]) return false;
            const RelicId id = static_cast<RelicId>(pendingRelics[action.index]);
            if (!can_obtain_relic(*this, id, 1)) return false;
            pendingRelicClaimed[action.index] = true;
            if (!add_relic(id)) { pendingRelicClaimed[action.index] = false; return false; }
            return true;
        }
        case RunActionType::OPEN_CARD_REWARD:
            if (screen != RunScreen::REWARDS || action.index < 0 || action.index >= MAX_CARD_REWARDS ||
                !rewardCardPending[action.index]) return false;
            activeCardReward = action.index;
            offeredCount = rewardCardCounts[action.index];
            for (int i = 0; i < offeredCount; ++i) offered[i] = rewardCards[action.index][i];
            rewardReturnToRewards = true;
            screen = RunScreen::CARD_REWARD;
            return true;
        case RunActionType::DISCARD_POTION:
            if (screen != RunScreen::REWARDS || pendingPotionCount == 0 ||
                action.index < 0 || action.index >= potionCount) return false;
            for (int i = action.index; i + 1 < potionCount; ++i) potions[i] = potions[i + 1];
            --potionCount;
            return true;
        case RunActionType::TAKE_STOLEN_CARD_REWARD:
        case RunActionType::SKIP_STOLEN_CARD_REWARD:
            if (screen != RunScreen::REWARDS || action.index < 0 || action.index >= stolenSyncCount ||
                !stolenRewardPending[action.index]) return false;
            if (action.type == RunActionType::TAKE_STOLEN_CARD_REWARD &&
                !add_card_to_deck(stolenOriginals[action.index])) return false;
            stolenRewardPending[action.index] = false;
            return true;
        case RunActionType::LEAVE_REWARDS:
            if (screen != RunScreen::REWARDS) return false;
            {
            const RunScreen resume = rewardResumeScreen;
            pendingGoldReward = pendingRecoveredGold = pendingPotionReward = 0;
            pendingRelicCount = 0;
            pendingCardReward = rewardReturnToRewards = false;
            for (bool &pending : stolenRewardPending) pending = false;
            clear_custom_rewards(*this);
            if (pendingReturnToEvent) {
                pendingReturnToEvent = false;
                event_resume_after_combat(*this);
            } else if (resume != RunScreen::MAP) {
                screen = resume;
            } else if (rewardIsBoss) {
                rewardIsBoss = false;
                if (act + 1 < MAX_ACTS) start_act(act + 1);
                else { won = true; screen = RunScreen::RUN_OVER; }
            } else {
                finish_room();
            }
            return true;
            }
    }
    return false;
}

namespace {

// Reject extreme externally supplied scalar values before they can overflow
// arithmetic or cause unbounded loops. This is a snapshot input limit, not a
// change to combat rules; values outside it cannot be restored.
constexpr int SNAPSHOT_VALUE_LIMIT = 10000000;
bool snapshot_nonnegative(int value) {
    return value >= 0 && value <= SNAPSHOT_VALUE_LIMIT;
}
bool snapshot_signed(int value) {
    return value >= -SNAPSHOT_VALUE_LIMIT && value <= SNAPSHOT_VALUE_LIMIT;
}

// A snapshot is a raw in-build object image. Inspect bool representations as
// bytes before reading them: a hostile input may contain values other than
// the two representations produced by this build.
bool snapshot_bool(const bool &value) {
    static_assert(sizeof(bool) == 1, "snapshot validation assumes one-byte bool");
    unsigned char byte = 0;
    std::memcpy(&byte, &value, sizeof(byte));
    return byte <= 1;
}

bool snapshot_card(const Card &card, bool active) {
    if (active && (card.uid == 0 || card.uid == 65535)) return false;
    const int id = static_cast<int>(card.id);
    if (id < (active ? 1 : 0) || id >= static_cast<int>(CardId::COUNT) ||
        static_cast<int>(card.enchantment) > static_cast<int>(EnchantmentId::CLONE) ||
        !snapshot_bool(card.enchantmentDisabled) ||
        !std::isfinite(card.bonusDamage) ||
        card.bonusDamage < -SNAPSHOT_VALUE_LIMIT || card.bonusDamage > SNAPSHOT_VALUE_LIMIT) return false;
    if (card.enchantment == EnchantmentId::NONE) {
        if (card.enchantmentAmount != 0 || card.enchantmentDisabled) return false;
    } else {
        if (card.enchantmentAmount <= 0) return false;
        if (active && (!card_is_playable(card) || card_def(card.id).type == CardType::CURSE ||
                       card_def(card.id).type == CardType::STATUS ||
                       (card.enchantment == EnchantmentId::VIGOROUS && !card_is_attack(card))))
            return false;
    }
    return
           (!active || card.id != CardId::GUILTY || card.guiltyCombatsSeen < 5) &&
           snapshot_bool(card.upgraded) && snapshot_bool(card.freeCombat) &&
           snapshot_bool(card.costThisTurn) && snapshot_bool(card.etherealThisCombat) &&
           snapshot_bool(card.retainThisCombat);
}

template <std::size_t N>
bool snapshot_cards(const Card (&cards)[N], int count) {
    if (count < 0 || count > static_cast<int>(N)) return false;
    for (std::size_t i = 0; i < N; ++i)
        if (!snapshot_card(cards[i], static_cast<int>(i) < count)) return false;
    return true;
}

template <std::size_t N>
bool snapshot_bools(const bool (&values)[N]) {
    for (const bool &value : values)
        if (!snapshot_bool(value)) return false;
    return true;
}

template <std::size_t N>
bool snapshot_ids(const int (&values)[N], int count, int limit) {
    if (count < 0 || count > static_cast<int>(N)) return false;
    for (int i = 0; i < count; ++i)
        if (values[i] <= 0 || values[i] >= limit) return false;
    return true;
}

bool snapshot_relic_bag(const RelicBagState &bag, bool shared) {
    bool seen[static_cast<int>(RelicId::COUNT)]{};
    for (int slot = 0; slot < RELIC_BAG_SLOTS; ++slot) {
        if (bag.counts[slot] < 0 || bag.counts[slot] > RELIC_BAG_CAPACITY) return false;
        for (int i = 0; i < bag.counts[slot]; ++i) {
            const int index = bag.entries[slot][i];
            if (index <= 0 || index >= static_cast<int>(RelicId::COUNT) || seen[index]) return false;
            const RelicId id = static_cast<RelicId>(index);
            const RelicPool pool = relic_def(id).pool;
            if (relic_raw_rarity(id) != slot + 1 || !relic_implemented(id) ||
                (shared ? pool != RelicPool::SHARED
                        : (pool != RelicPool::SHARED && pool != RelicPool::IRONCLAD))) return false;
            seen[index] = true;
        }
    }
    return true;
}

bool snapshot_battle(const BattleContext &b) {
    for (auto word : b.uidReservations) if (word != 0) return false;
    if (!snapshot_bool(b.player.surroundedFacingRight) ||
        !snapshot_bool(b.player.tookUnblockedDamageThisTurn) ||
        !snapshot_bool(b.player.tookUnblockedAttackDamageThisCombat) ||
        !snapshot_bool(b.nextPlayIsDupe) || !snapshot_bool(b.vitalSparkTriggeredThisEnemyTurn) ||
        !snapshot_bool(b.lavaLampTookQualifyingDamage) ||
        !snapshot_bool(b.gainedBlockFromCardThisTurn) ||
        !snapshot_bool(b.playedAttackOrSkillThisTurn) || !snapshot_bool(b.jugglingTriggeredThisTurn) ||
        !snapshot_bool(b.returnToHand) || !snapshot_bool(b.reboundPending) ||
        !snapshot_bool(b.skillsLocked) || !snapshot_bool(b.inMonsterTurn) ||
        !snapshot_bool(b.resolvingCard) || !snapshot_bool(b.weakSkipTick) ||
        !snapshot_bool(b.frailSkipTick) || !snapshot_bool(b.vulnerableSkipTick) ||
        !snapshot_bool(b.hasLastPlayed) || !snapshot_bools(b.panachePrimed) ||
        !snapshot_bools(b.theftReturned) ||
        !snapshot_bool(b.pending.optional) ||
        !snapshot_bool(b.pending.hasSource) || !snapshot_bool(b.pending.sourceExhaust) ||
        !snapshot_bool(b.activePlay.active) || !snapshot_bool(b.activePlay.autoPlay) ||
        !snapshot_bool(b.activePlay.forceExhaust) || !snapshot_bool(b.activePlay.dupe) ||
        !snapshot_bool(b.activePlay.resultsToDraw) || !snapshot_bool(b.activePlay.awaitingAfter) ||
        !snapshot_bool(b.activePlay.swiftAwaitingDraw))
        return false;
    if (!b.rng.valid_snapshot_state() || !b.shuffleRng.valid_snapshot_state() ||
        !b.cardGenerationRng.valid_snapshot_state() || !b.potionRng.valid_snapshot_state() ||
        !b.cardSelectionRng.valid_snapshot_state() || !b.energyCostRng.valid_snapshot_state() ||
        !b.targetRng.valid_snapshot_state() || !b.monsterAiRng.valid_snapshot_state() ||
        !b.nicheRng.valid_snapshot_state()) return false;
    if (b.monsterCount < 0 || b.monsterCount > MAX_MONSTERS ||
        b.potionSlots < 0 || b.potionSlots > MAX_POTIONS || b.potionCount > b.potionSlots ||
        !snapshot_ids(b.potions, b.potionCount, static_cast<int>(PotionId::COUNT)) ||
        !snapshot_ids(b.relics, b.relicCount, static_cast<int>(RelicId::COUNT)) ||
        !snapshot_cards(b.hand, b.handCount) || !snapshot_cards(b.draw, b.drawCount) ||
        !snapshot_cards(b.discard, b.discardCount) || !snapshot_cards(b.exhaust, b.exhaustCount) ||
        !snapshot_cards(b.playPile, b.playCount) ||
        !snapshot_cards(b.returnNextTurn, b.returnNextTurnCount) ||
        !snapshot_cards(b.theftCards, b.theftCount) ||
        !snapshot_cards(b.pending.cards, b.pending.count) ||
        !snapshot_card(b.pending.sourceCard, b.pending.hasSource) ||
        !snapshot_card(b.activePlay.card, b.activePlay.active) ||
        !snapshot_card(b.lastPlayedCard, b.hasLastPlayed)) return false;
    if (b.originalDeckCount < 0 || b.originalDeckCount > MAX_PILE ||
        b.theftCount < 0 || b.theftCount > MAX_PILE) return false;
    for (int i = 0; i < b.theftCount; ++i)
        if (b.theftOwners[i] < -1 || b.theftOwners[i] >= MAX_MONSTERS ||
            b.theftCards[i].uid != b.theftUids[i]) return false;
    if (!snapshot_nonnegative(b.player.maxHp) || !snapshot_nonnegative(b.player.hp) ||
        b.player.hp > b.player.maxHp || !snapshot_nonnegative(b.gold) ||
        !snapshot_nonnegative(b.recoveredStolenGold) || !snapshot_nonnegative(b.player.block) ||
        !snapshot_nonnegative(b.player.energy) || !snapshot_nonnegative(b.player.energyPerTurn) ||
        !snapshot_nonnegative(b.player.drawPerTurn) || !snapshot_signed(b.player.strength) ||
        !snapshot_signed(b.player.dexterity) || !snapshot_signed(b.player.tempStrength) ||
        !snapshot_signed(b.player.tempDexterity) || !snapshot_nonnegative(b.player.vulnerable) ||
        !snapshot_nonnegative(b.player.weak) || !snapshot_nonnegative(b.player.frail) ||
        b.turn < 0 || b.turn > 200 || b.ascension < 0 || b.ascension > 10 ||
        !snapshot_nonnegative(b.cardsPlayedThisTurn) || !snapshot_nonnegative(b.hpLostThisTurn) ||
        !snapshot_nonnegative(b.cardsPlayedThisCombat) || b.cardsFinishedThisCombat < 0 ||
        b.cardsFinishedThisCombat > b.cardsPlayedThisCombat ||
        b.knownTopCount < 0 || b.knownTopCount > b.drawCount ||
        b.playedThisTurnCount < 0 || b.playedThisTurnCount > MAX_PILE ||
        b.playedLastTurnCount < 0 || b.playedLastTurnCount > MAX_PILE ||
        b.bombCount < 0 || b.bombCount > BattleContext::MAX_BOMBS ||
        b.automationCount < 0 || b.automationCount > BattleContext::MAX_AUTOMATION ||
        b.toricCount < 0 || b.toricCount > MAX_PILE ||
        b.rollingCount < 0 || b.rollingCount > MAX_PILE ||
        b.panacheCount < 0 || b.panacheCount > MAX_PILE ||
        b.pendingDrawRemainder < 0 || b.pendingDrawRemainder > MAX_PILE ||
        b.pending.remaining < 0 || b.pending.remaining > MAX_PILE ||
        ((b.pending.op == ChoiceOp::DUPLICATE || b.pending.op == ChoiceOp::DISCARD_ANY) &&
         (b.pending.payload < 0 || b.pending.payload > MAX_PILE)) ||
        static_cast<int>(b.pending.op) > static_cast<int>(ChoiceOp::DISCARD_ANY) ||
        static_cast<int>(b.pending.pile) > static_cast<int>(ChoicePile::OFFER) ||
        static_cast<int>(b.outcome) > static_cast<int>(Outcome::TRUNCATED) ||
        static_cast<int>(b.encounter) >= static_cast<int>(Encounter::COUNT)) return false;
    for (int power : b.player.power) if (!snapshot_signed(power)) return false;
    if (b.activePlay.active && (b.activePlay.target < 0 || b.activePlay.target >= MAX_MONSTERS ||
        b.activePlay.playCount < 1 || b.activePlay.playCount > 4096 ||
        b.activePlay.nextPlay < 0 || b.activePlay.nextPlay > b.activePlay.playCount)) return false;
    for (int i = 0; i < b.toricCount; ++i)
        if (b.toricBlock[i] < 0 || b.toricTurns[i] < 0) return false;
    for (int i = 0; i < b.rollingCount; ++i)
        if (b.rollingDamage[i] < 0) return false;
    for (int i = 0; i < b.panacheCount; ++i)
        if (b.panacheDamage[i] < 0 || b.panacheLeft[i] < 0 || b.panacheLeft[i] > 5) return false;
    for (int i = 0; i < MAX_MONSTERS; ++i) {
        const Monster &m = b.monsters[i];
        if (!snapshot_bool(m.alive) || !snapshot_bool(m.offBalance) ||
            !snapshot_bool(m.combatEndBlocker) || !snapshot_bool(m.reviving) ||
            !snapshot_bool(m.stunned) || !snapshot_bool(m.nemesisIntangible) ||
            !snapshot_bool(m.skittishTriggeredThisTurn) ||
            static_cast<int>(m.id) >= static_cast<int>(MonsterId::COUNT) || m.stateLogN > 8 ||
            m.grappleCount < 0 || m.grappleCount > MAX_PILE || !snapshot_nonnegative(m.stolenGold) ||
            !snapshot_nonnegative(m.steamEruptionDamage) || !snapshot_nonnegative(m.block))
            return false;
        for (int j = 0; j < m.grappleCount; ++j)
            if (m.grappleAmounts[j] < 0) return false;
        if (i < b.monsterCount && (m.id == MonsterId::INVALID || m.slot >= MAX_MONSTERS ||
            m.maxHp < 0 || m.hp < 0 || m.hp > m.maxHp)) return false;
        if (i < b.monsterCount) {
            const MonsterDef &def = monster_def(m.id);
            // Waterfall Giant's death phase intentionally uses this exact
            // sentinel as max/current HP in the reference implementation.
            const bool waterfallSentinel = m.id == MonsterId::WATERFALL_GIANT &&
                                           m.maxHp == 999999999 && m.hp <= m.maxHp;
            if (m.move >= def.stateCount ||
                (!waterfallSentinel && (!snapshot_nonnegative(m.maxHp) || !snapshot_nonnegative(m.hp))) ||
                !snapshot_signed(m.strength)) return false;
            for (int power : m.power) if (!snapshot_signed(power)) return false;
            for (int j = 0; j < m.stateLogN; ++j)
                if (m.stateLog[j] >= def.stateCount) return false;
        }
    }
    return true;
}

bool snapshot_run(const RunContext &r) {
    if (!snapshot_bool(r.won) || !snapshot_bool(r.truncated) || !snapshot_bools(r.sharedAncientInAct) ||
        !snapshot_bool(r.inBattle) || !snapshot_bool(r.combatIsElite) ||
        !snapshot_bool(r.combatIsBoss) || !snapshot_bool(r.rewardIsBoss) ||
        !snapshot_bools(r.pendingRelicClaimed) || !snapshot_bool(r.pendingCardReward) ||
        !snapshot_bools(r.rewardCardPending) || !snapshot_bool(r.deferredCustomRewards) ||
        !snapshot_bools(r.stolenOriginalPresent) || !snapshot_bools(r.stolenRewardPending) ||
        !snapshot_bools(r.cardGrid.selected) || !snapshot_bool(r.cardGrid.preview) ||
        !snapshot_bool(r.processingAction) ||
        !snapshot_bool(r.rewardReturnToRewards) || !snapshot_bool(r.pendingReturnToEvent) ||
        !snapshot_bool(r.lavaRockTriggered) ||
        !snapshot_bools(r.shopSold) || !snapshot_bools(r.shopRelicSold) ||
        !snapshot_bools(r.shopPotionSold) || !snapshot_bool(r.removalUsed) ||
        !snapshot_bool(r.eventCombat) || !snapshot_bool(r.teaSetPending) ||
        !snapshot_bool(r.nextCombatUpgradeHand) || !snapshot_bool(r.mawBankPurchased) ||
        !snapshot_bool(r.treasureSkipped) || !snapshot_bool(r.relicBagsInitialized)) return false;
    if (r.ascension < 0 || r.ascension > 10 || r.act < 0 || r.act >= MAX_ACTS ||
        !snapshot_nonnegative(r.maxHp) || !snapshot_nonnegative(r.hp) || r.hp > r.maxHp ||
        !snapshot_nonnegative(r.gold) || r.floor < 0 ||
        r.floor > 1000 || r.cardShopRemovalsUsed < 0 || r.cardShopRemovalsUsed > MAX_DECK ||
        !snapshot_nonnegative(r.removalPrice) || !snapshot_nonnegative(r.removalBasePrice) ||
        !snapshot_nonnegative(r.cardsAdded) || !snapshot_nonnegative(r.combatsFought) ||
        !snapshot_nonnegative(r.elitesFought) || !snapshot_nonnegative(r.bossesFought) ||
        !snapshot_nonnegative(r.nextCombatEnergy) || r.nextCombatDazed < 0 || r.nextCombatDazed > MAX_PILE ||
        r.actFloor < 0 || r.actFloor > MAP_MAX_ROWS ||
        static_cast<int>(r.screen) > static_cast<int>(RunScreen::REWARDS) ||
        !snapshot_nonnegative(r.pendingGoldReward) || !snapshot_nonnegative(r.pendingRecoveredGold) ||
        r.pendingPotionReward < 0 || r.pendingPotionReward >= static_cast<int>(PotionId::COUNT) ||
        r.pendingPotionCount < 0 || r.pendingPotionCount > MAX_REWARD_POTIONS ||
        r.stolenSyncCount < 0 || r.stolenSyncCount > MAX_PILE ||
        r.activeCardReward < -1 || r.activeCardReward >= MAX_CARD_REWARDS ||
        static_cast<int>(r.rewardResumeScreen) > static_cast<int>(RunScreen::REWARDS) ||
        r.processingAction || r.deferredCustomRewards ||
        !snapshot_ids(r.pendingRelics, r.pendingRelicCount, static_cast<int>(RelicId::COUNT)) ||
        !snapshot_cards(r.deck, r.deckCount) || !snapshot_cards(r.offered, r.offeredCount) ||
        !snapshot_cards(r.shopCards, r.shopCount) ||
        !snapshot_ids(r.shopRelics, r.shopRelicCount, static_cast<int>(RelicId::COUNT)) ||
        !snapshot_ids(r.shopPotions, r.shopPotionCount, static_cast<int>(PotionId::COUNT)) ||
        r.potionSlots < 0 || r.potionSlots > MAX_POTIONS || r.potionCount > r.potionSlots ||
        !snapshot_ids(r.potions, r.potionCount, static_cast<int>(PotionId::COUNT)) ||
        !snapshot_ids(r.relics, r.relicCount, static_cast<int>(RelicId::COUNT)) ||
        !r.relicBagsInitialized || !snapshot_relic_bag(r.playerRelicBag, false) ||
        !snapshot_relic_bag(r.sharedRelicBag, true) ||
        r.normalBagN < 0 || r.normalBagN > 32 || r.normalBagPos < 0 || r.normalBagPos > 1000000 ||
        r.eliteBagN < 0 || r.eliteBagN > 16 || r.eliteBagPos < 0 || r.eliteBagPos > 1000000 ||
        r.eventBagN < 0 || r.eventBagN > 64 || r.eventBagPos < 0 || r.eventBagPos > 1000000 ||
        r.eventId < -1 || r.eventId >= event_count() || r.eventPage < 0 ||
        r.eventCardSelection > 3 ||
        (r.eventCardSelection && r.screen != RunScreen::EVENT &&
         !(r.screen == RunScreen::REWARDS && r.rewardResumeScreen == RunScreen::EVENT)) ||
        r.ancientId < 0 || r.ancientId >= event_count() ||
        r.lastPointType < 0 || r.lastPointType > static_cast<int>(MapPointType::ANCIENT) ||
        r.eventChoiceCount < 0 || r.eventChoiceCount > MAX_EVENT_CHOICES ||
        r.bossEncounter < -1 || r.bossEncounter >= static_cast<int>(Encounter::COUNT) ||
        r.secondBossEncounter < -1 || r.secondBossEncounter >= static_cast<int>(Encounter::COUNT)) return false;
    for (int i = 0; i < r.normalBagN; ++i)
        if (r.normalBag[i] == 0 || r.normalBag[i] >= static_cast<int>(Encounter::COUNT)) return false;
    for (int i = 0; i < MAX_REWARD_POTIONS; ++i)
        if (r.pendingPotions[i] < 0 || r.pendingPotions[i] >= static_cast<int>(PotionId::COUNT)) return false;
    for (int i = 0; i < r.deckCount; ++i)
        for (int j = 0; j < i; ++j) if (r.deck[i].uid == r.deck[j].uid) return false;
    for (int i = 0; i < MAX_PILE; ++i) {
        if (!snapshot_card(r.stolenOriginals[i], r.stolenOriginalPresent[i]) ||
            (i >= r.stolenSyncCount && (r.stolenOriginalPresent[i] || r.stolenRewardPending[i])) ||
            (r.stolenRewardPending[i] && !r.stolenOriginalPresent[i]) ||
            (r.stolenOriginalPresent[i] && r.stolenOriginals[i].uid != r.battle.theftUids[i])) return false;
    }
    if (r.pendingPotionReward != (r.pendingPotionCount ? r.pendingPotions[0] : 0)) return false;
    bool cardPending = false;
    for (int i = 0; i < MAX_CARD_REWARDS; ++i) {
        if (!snapshot_cards(r.rewardCards[i], r.rewardCardCounts[i]) ||
            (r.rewardCardPending[i] && !r.rewardCardCounts[i])) return false;
        cardPending |= r.rewardCardPending[i];
    }
    if (cardPending != r.pendingCardReward ||
        (r.rewardReturnToRewards != (r.activeCardReward >= 0)) ||
        (r.activeCardReward >= 0 && !r.rewardCardPending[r.activeCardReward])) return false;
    for (int i = 0; i < r.eliteBagN; ++i)
        if (r.eliteBag[i] == 0 || r.eliteBag[i] >= static_cast<int>(Encounter::COUNT)) return false;
    for (int i = 0; i < r.eventBagN; ++i)
        if (r.eventBag[i] >= event_count()) return false;
    for (int i = 0; i < r.shopCount; ++i)
        if (!snapshot_nonnegative(r.shopPrices[i]) || !snapshot_nonnegative(r.shopBasePrices[i])) return false;
    for (int i = 0; i < r.shopRelicCount; ++i)
        if (!snapshot_nonnegative(r.shopRelicPrices[i]) || !snapshot_nonnegative(r.shopRelicBasePrices[i])) return false;
    for (int i = 0; i < r.shopPotionCount; ++i)
        if (!snapshot_nonnegative(r.shopPotionPrices[i]) || !snapshot_nonnegative(r.shopPotionBasePrices[i])) return false;
    for (int value : r.eventData) if (!snapshot_nonnegative(value)) return false;
    for (int i = 0; i < r.relicCount; ++i) if (!snapshot_signed(r.relicAux[i])) return false;
    for (int i = 0; i < MAX_EVENT_CHOICES; ++i)
        if (r.eventRelics[i] < 0 || r.eventRelics[i] >= static_cast<int>(RelicId::COUNT)) return false;
    for (const Rng &rng : r.runRng) if (!rng.valid_snapshot_state()) return false;
    for (const Rng &rng : r.playerRng) if (!rng.valid_snapshot_state()) return false;
    if (!r.eventRng.valid_snapshot_state()) return false;
    if (!std::isfinite(r.cardRarityOdds) || !std::isfinite(r.potionRewardOdds) ||
        !std::isfinite(r.unknownMonsterOdds) || !std::isfinite(r.unknownEliteOdds) ||
        !std::isfinite(r.unknownTreasureOdds) || !std::isfinite(r.unknownShopOdds)) return false;
    const ActMap &map = r.map;
    if (map.rooms < 0 || map.rooms >= MAP_MAX_ROWS || map.mapLength < 0 ||
        map.mapLength >= MAP_MAX_ROWS || map.pointCount > MAP_MAX_POINTS ||
        map.startIdx < 0 || map.startIdx >= map.pointCount ||
        map.bossIdx < 0 || map.bossIdx >= map.pointCount ||
        map.secondBossIdx < -1 || map.secondBossIdx >= map.pointCount ||
        r.curRow < -1 || r.curRow >= MAP_MAX_ROWS || r.curCol < -1 || r.curCol >= MAP_WIDTH ||
        ((r.curRow == -1) != (r.curCol == -1))) return false;
    if (map.secondBossIdx >= 0) {
        if (r.ascension < 10 || r.act != MAX_ACTS - 1 || map.mapLength + 1 >= MAP_MAX_ROWS ||
            r.secondBossEncounter <= 0 || r.secondBossEncounter == r.bossEncounter ||
            map.at(map.mapLength + 1, MAP_WIDTH / 2) != map.secondBossIdx) return false;
        const MapNode &first = map.nodes[map.bossIdx];
        const MapNode &second = map.nodes[map.secondBossIdx];
        if (first.childCount != 1 || first.children[0] != map.secondBossIdx ||
            second.parentCount != 1 || second.parents[0] != map.bossIdx ||
            second.type != static_cast<int>(MapPointType::BOSS)) return false;
    } else if (r.secondBossEncounter != -1) return false;
    for (int row = 0; row < MAP_MAX_ROWS; ++row)
        for (int col = 0; col < MAP_WIDTH; ++col)
            if (map.index[row][col] < -1 || map.index[row][col] >= map.pointCount) return false;
    for (int i = 0; i < map.pointCount; ++i) {
        const MapNode &node = map.nodes[i];
        if (node.type < 0 || node.type > static_cast<int>(MapPointType::ANCIENT) ||
            node.childCount > MAP_MAX_EDGES || node.parentCount > MAP_MAX_EDGES) return false;
        for (int j = 0; j < node.childCount; ++j) if (node.children[j] >= map.pointCount) return false;
        for (int j = 0; j < node.parentCount; ++j) if (node.parents[j] >= map.pointCount) return false;
    }
    if ((r.screen == RunScreen::COMBAT) != r.inBattle ||
        (r.screen == RunScreen::EVENT && r.eventId < 0) ||
        !event_card_selection_valid(r) || !card_grid_valid(r) ||
        ((r.cardGrid.kind < 3 || r.cardGrid.kind == 5) && r.cardGrid.kind &&
         !snapshot_cards(r.cardGrid.cards, r.cardGrid.count)) ||
        (r.rewardReturnToRewards && r.screen != RunScreen::CARD_REWARD) ||
        (r.truncated && (r.screen != RunScreen::RUN_OVER || r.won))) return false;
    return snapshot_battle(r.battle);
}

}  // namespace

std::string RunContext::serialize() const {
    // In-build snapshot: POD layout behind a magic/version/size header.
    struct Header {
        std::uint32_t magic;
        std::uint16_t version;
        std::uint16_t reserved;
        std::uint32_t size;
    } header{0x53545332u, 5u, 0u, static_cast<std::uint32_t>(sizeof(RunContext))};
    std::string out(sizeof(Header), '\0');
    std::memcpy(&out[0], &header, sizeof(Header));
    const char *bytes = reinterpret_cast<const char *>(this);
    out.append(bytes, sizeof(RunContext));
    return out;
}

bool RunContext::restore(const std::string &blob, RunContext &out) {
    if (blob.size() < 12) return false;
    std::uint32_t magic = 0;
    std::uint16_t version = 0;
    std::uint32_t size = 0;
    std::memcpy(&magic, blob.data(), 4);
    std::memcpy(&version, blob.data() + 4, 2);
    std::memcpy(&size, blob.data() + 8, 4);
    if (magic != 0x53545332u || version != 5u) return false;
    if (size != sizeof(RunContext) || blob.size() != 12 + sizeof(RunContext)) return false;
    // Validate a temporary object and do not mutate the destination on error.
    RunContext candidate;
    std::memcpy(&candidate, blob.data() + 12, sizeof(RunContext));
    if (!snapshot_run(candidate)) return false;
    std::memcpy(&out, &candidate, sizeof(RunContext));
    return true;
}

std::uint64_t RunContext::state_hash() const {
    const std::string blob = serialize();
    std::uint64_t h = 1469598103934665603ull;
    for (const unsigned char c : blob) {
        h ^= c;
        h *= 1099511628211ull;
    }
    return h;
}

double RunContext::terminal_reward() const {
    if (screen != RunScreen::RUN_OVER) return 0.0;
    if (truncated) return 0.0;
    if (won) return 1.0;
    // Partial credit for progress on death (keeps the signal dense).
    return -1.0 + 0.5 * (static_cast<double>(act) * 100 + actFloor) / 340.0;
}

}  // namespace sts2
