// Full-run flow: StandardActMap traversal, rooms, rewards, shops, events.
#include "sts2/run.h"

#include <cstring>

#include "sts2/monsters.h"
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
    const int i = static_cast<int>(id);
    return i > 0 && i <= static_cast<int>(CardId::WHIRLWIND);  // Ironclad pool
}

bool in_colorless_pool(CardId id) {
    const CardDef &d = card_def(id);
    if (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY)) return false;
    if (d.rarity != Rarity::COMMON && d.rarity != Rarity::UNCOMMON && d.rarity != Rarity::RARE) {
        return false;
    }
    const int i = static_cast<int>(id);
    return i > static_cast<int>(CardId::WHIRLWIND) && i < static_cast<int>(CardId::BECKON);
}

bool pool_accepts(CardId id, bool colorless) {
    return colorless ? in_colorless_pool(id) : in_reward_pool(id);
}

CardId random_card_of_rarity(Rng &rng, Rarity want, bool colorless) {
    CardId pool[128];
    int n = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardId id = static_cast<CardId>(i);
        if (pool_accepts(id, colorless) && card_def(id).rarity == want) pool[n++] = id;
    }
    if (n == 0) return CardId::INVALID;
    return pool[rng.next_int(0, n - 1)];
}

PotionId random_potion_from(Rng &rng, bool ironcladOnly = true) {
    int pool[64];
    int n = 0;
    for (int i = 1; i < static_cast<int>(PotionId::COUNT); ++i) {
        const PotionDef &d = potion_def(static_cast<PotionId>(i));
        if (ironcladOnly && !d.ironclad) continue;
        pool[n++] = i;
    }
    if (n == 0) return PotionId::INVALID;
    return static_cast<PotionId>(pool[rng.next_int(0, n - 1)]);
}

PotionId random_potion_of_rarity(Rng &rng, Rarity want) {
    int pool[64];
    int n = 0;
    for (int i = 1; i < static_cast<int>(PotionId::COUNT); ++i) {
        const PotionDef &d = potion_def(static_cast<PotionId>(i));
        if (!d.ironclad || d.rarity != want) continue;
        pool[n++] = i;
    }
    if (n == 0) return PotionId::INVALID;
    return static_cast<PotionId>(pool[rng.next_int(0, n - 1)]);
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

void acquire_card(RunContext &rc, Card card) {
    const CardType type = card_def(card.id).type;
    if (!card.upgraded &&
        ((type == CardType::ATTACK && run_has_relic(rc, RelicId::MOLTEN_EGG)) ||
         (type == CardType::SKILL && run_has_relic(rc, RelicId::TOXIC_EGG)) ||
         (type == CardType::POWER && run_has_relic(rc, RelicId::FROZEN_EGG)))) {
        card.upgraded = true;
    }
    rc.add_card_to_deck(card);
    if (run_has_relic(rc, RelicId::BING_BONG)) rc.add_card_to_deck(card);
    ++rc.cardsAdded;
    if (run_has_relic(rc, RelicId::LUCKY_FYSH)) run_gain_gold(rc, 15);
    if (run_has_relic(rc, RelicId::BOOK_OF_FIVE_RINGS) && rc.cardsAdded % 5 == 0) {
        rc.hp = std::min(rc.maxHp, rc.hp + 15);
    }
}

// Relic drop: implemented, unowned, shared/Ironclad, matching rarity.
RelicId random_shared_relic(RunContext &rc, Rng &rng, Rarity want) {
    int pool[256];
    int n = 0;
    for (int i = 1; i < static_cast<int>(RelicId::COUNT); ++i) {
        const RelicId id = static_cast<RelicId>(i);
        const RelicDef &d = relic_def(id);
        if (d.pool != RelicPool::SHARED && d.pool != RelicPool::IRONCLAD) continue;
        if (!relic_implemented(id)) continue;
        if (d.rarity != want) continue;
        if (run_has_relic(rc, id)) continue;
        pool[n++] = i;
    }
    if (n == 0) return RelicId::INVALID;
    return static_cast<RelicId>(pool[rng.next_int(0, n - 1)]);
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
    int pool[256];
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

}  // namespace

bool card_upgradable(const Card &c) {
    if (c.upgraded) return false;
    const CardDef &d = card_def(c.id);
    if (d.damageUp != 0 || d.blockUp != 0) return true;
    for (int i = 0; i < static_cast<int>(VarId::COUNT); ++i) {
        if (d.varUp[i] != 0) return true;
    }
    return false;
}

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

Card RunContext::make_run_card(CardId id, bool upgraded) {
    Card c = make_card(id, upgraded, nextUid++);
    c.bonusDamage = 0;
    return c;
}

void RunContext::add_card_to_deck(Card c) {
    if (deckCount < MAX_DECK) deck[deckCount++] = c;
}

void RunContext::init(std::uint32_t seedValue, int ascensionLevel) {
    *this = RunContext();
    seed = seedValue;
    ascension = ascensionLevel;
    for (int i = 0; i < RNG_COUNT; ++i) runRng[i] = Rng(seed, RUN_RNG_NAMES[i]);
    // Player-level streams derive from run seed + player id (single player id = 1).
    for (int i = 0; i < PRNG_COUNT; ++i) {
        playerRng[i] = Rng(seed + 1u, PLAYER_RNG_NAMES[i]);
    }
    // The shared ancients (Darv) are allocated to acts 2/3 before any act's
    // rooms are generated (C# RunManager.GenerateRooms).
    event_plan_shared_ancients(*this);
    hp = 80;
    maxHp = 80;
    gold = 99;
    act = 0;
    actFloor = 0;
    floor = 0;
    screen = RunScreen::MAP;
    add_relic(RelicId::BURNING_BLOOD);
    for (int i = 0; i < 5; ++i) add_card_to_deck(make_run_card(CardId::STRIKE_IRONCLAD, false));
    for (int i = 0; i < 4; ++i) add_card_to_deck(make_run_card(CardId::DEFEND_IRONCLAD, false));
    add_card_to_deck(make_run_card(CardId::BASH, false));
    start_act(0);
}

void RunContext::roll_act_rooms() {
    normalBagN = 0;
    normalBagPos = 0;
    eliteBagN = 0;
    eliteBagPos = 0;
    eventBagN = 0;
    eventBagPos = 0;

    // Encounter bags (approximation of RoomSet's tagged grab bags).
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
    Rng &rng = runRng[RNG_UP_FRONT];
    const int rooms = map.rooms;
    for (int i = 0; i < 3 && normalBagN < 32 && weakN > 0; ++i) {
        normalBag[normalBagN++] = static_cast<std::uint16_t>(weak[rng.next_int(0, weakN - 1)]);
    }
    for (int i = 3; i < rooms && normalBagN < 32; ++i) {
        if (normalN == 0) break;
        normalBag[normalBagN++] = static_cast<std::uint16_t>(normal[rng.next_int(0, normalN - 1)]);
    }
    for (int i = 0; i < 15 && eliteBagN < 16 && eliteN > 0; ++i) {
        eliteBag[eliteBagN++] = static_cast<std::uint16_t>(elite[rng.next_int(0, eliteN - 1)]);
    }
    // Normal encounters are consumed in list order (weak first) as in RoomSet.
    for (int i = eliteBagN - 1; i > 0; --i) {
        const int j = rng.next_int(0, i);
        std::swap(eliteBag[i], eliteBag[j]);
    }
    bossEncounter = bossN > 0 ? boss[rng.next_int(0, bossN - 1)] : -1;

    // Event bag: implemented act events + implemented shared events.
    int ev[128];
    const int n = event_pool_for_act(act, ev, 128);
    for (int i = 0; i < n && eventBagN < 64; ++i) {
        eventBag[eventBagN++] = static_cast<std::uint16_t>(ev[i]);
    }
    for (int i = eventBagN - 1; i > 0; --i) {
        const int j = rng.next_int(0, i);
        std::swap(eventBag[i], eventBag[j]);
    }
    // ActModel.GenerateRooms picks the Ancient last, from the same stream.
    ancientId = static_cast<std::int8_t>(event_pick_ancient(*this));
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
    generate_act_map(map, mapRng, actIndex);
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
    if (id == RelicId::INVALID || !relic_implemented(id)) return false;
    if (run_has_relic(*this, id)) return false;
    if (relicCount >= MAX_RELICS) return false;
    relics[relicCount++] = static_cast<int>(id);
    relics_on_obtain(*this, id);
    return true;
}

void RunContext::sync_relics_from_battle() {
    relicCount = battle.relicCount;
    for (int i = 0; i < relicCount; ++i) relics[i] = battle.relics[i];
}

int RunContext::current_point_type() const {
    const int idx = map.at(curRow, curCol);
    if (idx < 0) return static_cast<int>(MapPointType::UNASSIGNED);
    return map.nodes[idx].type;
}

void RunContext::begin_combat(Encounter enc) {
    if (enc == Encounter::INVALID) {
        enc = static_cast<Encounter>(random_encounter_for_act(act, runRng[RNG_MONSTER_AI], 0));
    }
    const std::uint32_t combatSeed =
        static_cast<std::uint32_t>(runRng[RNG_MONSTER_AI].next_int(0, 1000000000));
    const std::uint32_t potionSeed = static_cast<std::uint32_t>(
        runRng[RNG_COMBAT_POTION_GENERATION].next_int(0, 1000000000));
    battle.init(enc, combatSeed, deck, deckCount, ascension, hp, maxHp, relics, relicCount,
                potions, potionCount, potionSlots, run_turn1_energy(*this),
                3 + run_energy_bonus(*this), gold, potionSeed);
    teaSetPending = false;
    nextCombatEnergy = 0;
    for (int i = 0; i < relicCount; ++i) {
        if (relics[i] == static_cast<int>(RelicId::GIRYA) && relicAux[i] > 0) {
            battle.player.strength += relicAux[i];
        }
    }
    if (emberTeaCombats > 0) {
        battle.player.strength += 2;
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
            battle.add_card_to_draw_top(make_card(CardId::DAZED, false, battle.nextUid++));
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
        // Rarity: grows across rolls; boss rewards are always rare.
        Rarity want = Rarity::RARE;
        if (!boss) {
            const float u = rng.next_float();
            float offset = cardRarityOdds;
            const bool rare = u < 0.03f + offset;
            const bool uncommon = !rare && u < 0.03f + offset + 0.37f;
            if (rare) {
                want = Rarity::RARE;
                cardRarityOdds = -0.05f;
            } else {
                want = uncommon ? Rarity::UNCOMMON : Rarity::COMMON;
                cardRarityOdds = std::min(0.4f, cardRarityOdds + 0.01f);
            }
        }
        CardId id = random_card_of_rarity(rng, want, colorlessSlot);
        if (id == CardId::INVALID) id = random_card_of_rarity(rng, Rarity::COMMON, colorlessSlot);
        if (id == CardId::INVALID) continue;
        bool dup = false;
        for (int i = 0; i < offeredCount; ++i) dup = dup || picked[i] == id;
        if (dup) continue;
        picked[offeredCount] = id;
        Card card = make_run_card(id, false);
        // Upgrade roll: chance = actIndex * 0.25 for non-rare cards.
        const float upOdds = (boss || card_def(id).rarity == Rarity::RARE)
                                 ? 0.0f
                                 : static_cast<float>(act) * 0.25f;
        if (card_upgradable(card) && rng.next_float() <= upOdds) card.upgraded = true;
        offered[offeredCount++] = card;
    }
}

void RunContext::roll_shop() {
    shopCount = 0;
    shopRelicCount = 0;
    shopPotionCount = 0;
    removalUsed = false;
    removalPrice = 75 + 25 * cardShopRemovalsUsed;
    Rng &shops = playerRng[PRNG_SHOPS];
    Rng &rewards = playerRng[PRNG_REWARDS];

    static const CardType types[5] = {CardType::ATTACK, CardType::ATTACK, CardType::SKILL,
                                      CardType::SKILL, CardType::POWER};
    const int saleIndex = shops.next_int_exclusive(5);
    CardId used[MAX_SHOP_CARDS]{};
    int usedN = 0;
    for (int i = 0; i < 5; ++i) {
        CardId id = CardId::INVALID;
        for (int rarityTry = 0; rarityTry < 3 && id == CardId::INVALID; ++rarityTry) {
            const float u = shops.next_float();
            float offset = cardRarityOdds;
            Rarity want = u < 0.09f + offset
                              ? Rarity::RARE
                              : (u < 0.09f + offset + 0.37f ? Rarity::UNCOMMON : Rarity::COMMON);
            for (int rank = 0; rank <= rarityTry && id == CardId::INVALID; ++rank) {
                // rank 0 uses the rolled rarity, then falls back to higher rarities
                Rarity target = want;
                if (rank == 1) target = want == Rarity::COMMON ? Rarity::UNCOMMON : Rarity::RARE;
                if (rank == 2) target = Rarity::RARE;
                int pool[64];
                int n = 0;
                for (int c = 1; c < static_cast<int>(CardId::COUNT); ++c) {
                    const CardId cid = static_cast<CardId>(c);
                    if (!in_reward_pool(cid)) continue;
                    if (card_def(cid).rarity != target) continue;
                    if (card_def(cid).type != types[i]) continue;
                    bool dup = false;
                    for (int j = 0; j < usedN; ++j) dup = dup || used[j] == cid;
                    if (!dup) pool[n++] = c;
                }
                if (n > 0) id = static_cast<CardId>(pool[shops.next_int(0, n - 1)]);
            }
        }
        if (id == CardId::INVALID) continue;
        used[usedN++] = id;
        int price = shop_price_value(id, false, shops);
        if (i == saleIndex) price /= 2;
        shopCards[shopCount] = make_run_card(id, false);
        shopPrices[shopCount] = price;
        shopSold[shopCount] = false;
        ++shopCount;
    }
    // Two colorless slots (uncommon, rare).
    const Rarity colorlessRarities[2] = {Rarity::UNCOMMON, Rarity::RARE};
    for (int i = 0; i < 2; ++i) {
        int pool[64];
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
        shopCards[shopCount] = make_run_card(id, false);
        shopPrices[shopCount] = shop_price_value(id, true, shops);
        shopSold[shopCount] = false;
        ++shopCount;
    }

    // Relics: two rolled rarities + one shop rarity.
    for (int i = 0; i < 3; ++i) {
        Rarity want;
        if (i == 2) {
            want = Rarity::SPECIAL;
        } else {
            const float u = shops.next_float();
            want = u < 0.5f ? Rarity::COMMON : (u < 0.83f ? Rarity::UNCOMMON : Rarity::RARE);
        }
        RelicId rid = random_shared_relic(*this, shops, want);
        if (rid == RelicId::INVALID) rid = random_shared_relic(*this, shops, Rarity::UNCOMMON);
        if (rid == RelicId::INVALID) rid = random_shared_relic(*this, shops, Rarity::COMMON);
        if (rid == RelicId::INVALID) rid = random_shared_relic(*this, shops, Rarity::RARE);
        if (rid == RelicId::INVALID) continue;
        shopRelics[shopRelicCount] = static_cast<int>(rid);
        shopRelicPrices[shopRelicCount] = static_cast<int>(
            std::lround(static_cast<float>(relic_merchant_cost(relic_def(rid).rarity)) *
                        shops.next_float(0.85f, 1.15f)));
        shopRelicSold[shopRelicCount] = false;
        ++shopRelicCount;
    }

    // Potions: three random out-of-combat potions.
    for (int i = 0; i < 3; ++i) {
        const PotionId pid = random_potion_from(shops);
        if (pid == PotionId::INVALID) continue;
        shopPotions[shopPotionCount] = static_cast<int>(pid);
        int base = 50;
        if (potion_def(pid).rarity == Rarity::UNCOMMON) base = 75;
        else if (potion_def(pid).rarity == Rarity::RARE) base = 100;
        shopPotionPrices[shopPotionCount] =
            static_cast<int>(std::lround(static_cast<float>(base) * shops.next_float(0.95f, 1.05f)));
        shopPotionSold[shopPotionCount] = false;
        ++shopPotionCount;
    }
    (void)rewards;
}

void RunContext::roll_treasure() {
    Rng &rewards = playerRng[PRNG_REWARDS];
    run_gain_gold(*this, rewards.next_int(42, 52));
    const float u = runRng[RNG_TREASURE_ROOM_RELICS].next_float();
    const Rarity want = u < 0.5f ? Rarity::COMMON
                                 : (u < 0.83f ? Rarity::UNCOMMON : Rarity::RARE);
    RelicId id = random_shared_relic(*this, runRng[RNG_TREASURE_ROOM_RELICS], want);
    if (id == RelicId::INVALID) id = roll_shared_relic(*this, runRng[RNG_TREASURE_ROOM_RELICS]);
    add_relic(id);
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

void RunContext::finish_room() { screen = RunScreen::MAP; }

void RunContext::enter_map_point(int nodeIdx) {
    if (nodeIdx < 0 || nodeIdx >= map.pointCount) return;
    int row = -1;
    int col = -1;
    for (int r = 0; r <= map.mapLength && row < 0; ++r) {
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
                bossEncounter > 0 ? bossEncounter
                                  : static_cast<int>(Encounter::INVALID)));
            break;
        case RoomType::EVENT: {
            int evt = -1;
            if (eventBagN > 0) {
                evt = eventBag[eventBagPos % eventBagN];
                ++eventBagPos;
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
            roll_treasure();
            screen = RunScreen::TREASURE;
            break;
    }
}

void RunContext::finish_combat() {
    inBattle = false;
    sync_potions_from_battle();
    sync_relics_from_battle();
    // Seal of Gold spends real run gold during combat.
    gold = std::max(0, battle.gold);
    const bool eventFight = eventCombat;
    if (battle.outcome == Outcome::PLAYER_VICTORY) {
        hp = battle.player.hp;
        maxHp = battle.player.maxHp;
        if (eventFight) {
            eventCombat = false;
            event_resume_after_combat(*this);
            return;
        }
        Rng &rewards = playerRng[PRNG_REWARDS];
        int minGold = 10;
        int maxGold = 20;
        if (combatIsElite) {
            minGold = 35;
            maxGold = 45;
        } else if (combatIsBoss) {
            minGold = 100;
            maxGold = 100;
        }
        int rewardGold = rewards.next_int(minGold, maxGold) + battle.combatGold;
        if (run_has_relic(*this, RelicId::BOWLER_HAT)) rewardGold += rewardGold * 20 / 100;
        run_gain_gold(*this, rewardGold);
        relics_combat_end(*this, true, combatIsBoss);
        // Potion reward odds (0.4 base, +/-0.1 per roll, elite bonus).
        const bool forcePotion = run_has_relic(*this, RelicId::WHITE_BEAST_STATUE);
        const float before = potionRewardOdds;
        const float roll = rewards.next_float();
        if (roll < before || forcePotion) potionRewardOdds -= 0.1f;
        else potionRewardOdds += 0.1f;
        const float bonus = combatIsElite ? 0.125f : 0.0f;
        const bool potionDropped = forcePotion || roll < before + bonus;
        if (potionDropped && !run_has_relic(*this, RelicId::SOZU) &&
            potionCount < potionSlots) {
            add_potion(random_potion_from(rewards));
        }
        if (combatIsElite) {
            add_relic(roll_shared_relic(*this, rewards));
        }
        roll_card_reward(combatIsBoss);
        screen = RunScreen::CARD_REWARD;
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
    switch (screen) {
        case RunScreen::MAP:
            for (const int idx : available_map_nodes()) {
                out.push_back({RunActionType::MOVE, idx});
            }
            break;
        case RunScreen::CARD_REWARD:
            for (int i = 0; i < offeredCount; ++i) out.push_back({RunActionType::TAKE_CARD, i});
            out.push_back({RunActionType::SKIP_CARD, 0});
            break;
        case RunScreen::REST:
            out.push_back({RunActionType::REST_HEAL, 0});
            for (int i = 0; i < deckCount; ++i) {
                if (card_upgradable(deck[i])) out.push_back({RunActionType::REST_UPGRADE, i});
            }
            if (run_has_relic(*this, RelicId::SHOVEL)) out.push_back({RunActionType::REST_DIG, 0});
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
                if (!shopSold[i] && gold >= shopPrices[i]) {
                    out.push_back({RunActionType::BUY_CARD, i});
                }
            }
            for (int i = 0; i < shopRelicCount; ++i) {
                if (!shopRelicSold[i] && gold >= shopRelicPrices[i]) {
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
            for (int i = 0; i < event_option_count(*this); ++i) {
                if (event_option_available(*this, i)) {
                    out.push_back({RunActionType::EVENT_CHOICE, i});
                }
            }
            break;
        case RunScreen::TREASURE:
            out.push_back({RunActionType::COLLECT, 0});
            break;
        case RunScreen::COMBAT:
        case RunScreen::RUN_OVER:
            break;
    }
    if (screen != RunScreen::COMBAT && screen != RunScreen::RUN_OVER) {
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
            while (potionCount < potionSlots) {
                const PotionId next = random_potion_from(playerRng[PRNG_REWARDS]);
                if (next == PotionId::INVALID) break;
                add_potion(next);
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

bool RunContext::step_combat(const Action &action) {
    if (screen != RunScreen::COMBAT) return false;
    if (battle.outcome != Outcome::UNDECIDED) {
        finish_combat();
        return true;
    }
    if (!battle.step(action)) return false;
    if (battle.outcome != Outcome::UNDECIDED) finish_combat();
    return true;
}

bool RunContext::step(const RunAction &action) {
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
            acquire_card(*this, offered[action.index]);
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
            if (screen != RunScreen::CARD_REWARD) return false;
            if (run_has_relic(*this, RelicId::PAELS_WING)) {
                ++paelsWingSkips;
                if (paelsWingSkips % 2 == 0) add_relic(roll_shared_relic(*this, playerRng[PRNG_REWARDS]));
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
                add_potion(random_potion_from(playerRng[PRNG_REWARDS]));
            }
            if (run_has_relic(*this, RelicId::VENERABLE_TEA_SET)) teaSetPending = true;
            finish_room();
            return true;
        }
        case RunActionType::REST_UPGRADE: {
            if (screen != RunScreen::REST) return false;
            if (action.index < 0 || action.index >= deckCount) return false;
            if (!card_upgradable(deck[action.index])) return false;
            deck[action.index].upgraded = true;
            if (run_has_relic(*this, RelicId::TINY_MAILBOX) &&
                !run_has_relic(*this, RelicId::SOZU) && potionCount < potionSlots) {
                add_potion(random_potion_from(playerRng[PRNG_REWARDS]));
            }
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
            gold -= shopPrices[action.index];
            mawBankPurchased = true;
            acquire_card(*this, shopCards[action.index]);
            shopSold[action.index] = true;
            return true;
        }
        case RunActionType::BUY_RELIC: {
            if (screen != RunScreen::SHOP) return false;
            if (action.index < 0 || action.index >= shopRelicCount) return false;
            if (shopRelicSold[action.index] || gold < shopRelicPrices[action.index]) return false;
            gold -= shopRelicPrices[action.index];
            mawBankPurchased = true;
            add_relic(static_cast<RelicId>(shopRelics[action.index]));
            shopRelicSold[action.index] = true;
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
        case RunActionType::COLLECT:
            if (screen != RunScreen::TREASURE) return false;
            finish_room();
            return true;
        case RunActionType::USE_POTION:
            if (screen == RunScreen::COMBAT || screen == RunScreen::RUN_OVER) return false;
            return use_potion_out_of_combat(action.index);
    }
    return false;
}

std::string RunContext::serialize() const {
    // In-build snapshot: POD layout behind a magic/version/size header.
    struct Header {
        std::uint32_t magic;
        std::uint16_t version;
        std::uint16_t reserved;
        std::uint32_t size;
    } header{0x53545332u, 1u, 0u, static_cast<std::uint32_t>(sizeof(RunContext))};
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
    if (magic != 0x53545332u || version != 1u) return false;
    if (size != sizeof(RunContext) || blob.size() != 12 + sizeof(RunContext)) return false;
    std::memcpy(&out, blob.data() + 12, sizeof(RunContext));
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
    if (won) return 1.0;
    // Partial credit for progress on death (keeps the signal dense).
    return -1.0 + 0.5 * (static_cast<double>(act) * 100 + actFloor) / 340.0;
}

}  // namespace sts2
