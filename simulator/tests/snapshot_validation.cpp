#include "sts2/run.h"
#include "sts2/relics.h"
#include "sts2/relic_raw_rarity.h"
#include "sts2/monsters.h"

#include <cassert>
#include <climits>
#include <cstddef>
#include <cstring>
#include <iostream>
#include <memory>

#define TEST_RUN(name) auto name##Storage = std::make_unique<RunContext>(); RunContext &name = *name##Storage

using namespace sts2;

template <typename T>
static void corrupt(std::string &blob, std::size_t offset, T value) {
    std::memcpy(&blob[12 + offset], &value, sizeof(value));
}

static void rejects_atomically(const std::string &blob, RunContext &out) {
    const std::string before = out.serialize();
    assert(!RunContext::restore(blob, out));
    assert(out.serialize() == before);
}

static int find_event(const char *name) {
    for (int i = 0; i < event_count(); ++i)
        if (std::strcmp(event_info(i)->name, name) == 0) return i;
    assert(false && "event missing");
    return -1;
}

int main() {
    int cost_or_keyword_upgrades = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardId id = static_cast<CardId>(i);
        const CardDef &def = card_def(id);
        bool changes_var = false;
        for (int value : def.varUp) changes_var |= value != 0;
        if (def.damageUp == 0 && def.blockUp == 0 && !changes_var &&
            (def.cost != def.costUp || def.flags != def.flagsUp)) {
            assert(card_upgradable(make_card(id, false, 1)));
            ++cost_or_keyword_upgrades;
        }
    }
    assert(cost_or_keyword_upgrades == 27);
    TEST_RUN(src); TEST_RUN(out);
    TEST_RUN(seeded);
    seeded.init(123, 0);
    assert(seeded.seed == 1816791482u);
    seeded.nextUid = 65535;
    const Card wrapped = seeded.make_run_card(CardId::BASH, false);
    assert(wrapped.uid != 0 && wrapped.uid != 65535);
    for (int i = 0; i < seeded.deckCount; ++i) assert(wrapped.uid != seeded.deck[i].uid);
    Rng map_rng(seeded.seed, "act_1_map");
    ActMap expected_map{};
    generate_act_map(expected_map, map_rng, 0);
    assert(std::memcmp(&seeded.map, &expected_map, sizeof(ActMap)) == 0);

    for (int level = 0; level <= 10; ++level) {
        TEST_RUN(ascended);
        ascended.init(123, level);
        assert(ascended.gold == 99);
        assert(ascended.potionSlots == (level >= 4 ? 2 : 3));
        assert(ascended.deckCount == (level >= 5 ? 11 : 10));
        if (level >= 5) assert(ascended.deck[10].id == CardId::ASCENDERS_BANE);
        Rng reward_rng = ascended.playerRng[PRNG_REWARDS];
        (void)reward_rng.next_float();  // potion-drop roll precedes gold population
        const int expected_gold = level >= 3 ? reward_rng.next_int(7, 15)
                                             : reward_rng.next_int(10, 20);
        ascended.gold = 0;
        ascended.battle.gold = 0;
        ascended.battle.combatGold = 0;
        ascended.battle.outcome = Outcome::PLAYER_VICTORY;
        ascended.finish_combat();
        assert(ascended.gold == 0 && ascended.pendingGoldReward == expected_gold);
        assert(ascended.step({RunActionType::TAKE_GOLD_REWARD, 0}));
        assert(ascended.gold == expected_gold);
    }

    TEST_RUN(hooks);
    hooks.init(987, 0);
    hooks.hp = 30;
    hooks.gold = 0;
    assert(hooks.add_relic(RelicId::LUCKY_FYSH));
    assert(hooks.add_relic(RelicId::BOOK_OF_FIVE_RINGS));
    assert(hooks.add_relic(RelicId::DARKSTONE_PERIAPT));
    assert(hooks.add_relic(RelicId::BING_BONG));
    hooks.cardsAdded = 3;
    const int old_deck_count = hooks.deckCount;
    const Card curse = hooks.make_run_card(CardId::ASCENDERS_BANE, false);
    assert(hooks.add_card_to_deck(curse));
    assert(hooks.deckCount == old_deck_count + 2);
    assert(hooks.deck[old_deck_count].uid != hooks.deck[old_deck_count + 1].uid);
    assert(hooks.gold == 30 && hooks.cardsAdded == 5);
    assert(hooks.maxHp == 92 && hooks.hp == 57);

    hooks.deckCount = MAX_DECK - 1;
    const Card extra = hooks.make_run_card(CardId::STRIKE_IRONCLAD, false);
    const std::string before_full = hooks.serialize();
    assert(!hooks.add_card_to_deck(extra));
    assert(hooks.serialize() == before_full);
    hooks.screen = RunScreen::CARD_REWARD;
    hooks.offeredCount = 1;
    hooks.offered[0] = extra;
    const std::string before_reward = hooks.serialize();
    assert(!hooks.step({RunActionType::TAKE_CARD, 0}));
    assert(hooks.serialize() == before_reward);

    TEST_RUN(guilty);
    guilty.init(81, 0);
    Card first_guilty = guilty.make_run_card(CardId::GUILTY, false);
    Card second_guilty = guilty.make_run_card(CardId::GUILTY, false);
    second_guilty.guiltyCombatsSeen = 2;
    assert(guilty.add_card_to_deck(first_guilty));
    assert(guilty.add_card_to_deck(second_guilty));
    for (int i = 0; i < 5; ++i) {
        guilty.battle.outcome = Outcome::PLAYER_VICTORY;
        guilty.finish_combat();
        const int expected = i < 2 ? 12 : (i < 4 ? 11 : 10);
        assert(guilty.deckCount == expected);
        if (i < 4) assert(guilty.deck[10].guiltyCombatsSeen == i + 1);
        assert(RunContext::restore(guilty.serialize(), out));
    }

    // An event bag skips disallowed and previously visited events; one full
    // unsuccessful cycle falls back to the reference's repetition behavior.
    TEST_RUN(events);
    events.init(123, 0);
    events.act = 1;
    events.gold = 0;
    const int wongo = find_event("WELCOME_TO_WONGOS");
    const int seen = find_event("TABLET_OF_TRUTH");
    const int allowed = find_event("WELLSPRING");
    const int node = events.map.at(events.curRow, events.curCol);
    assert(node >= 0);
    events.map.nodes[node].type = static_cast<int>(MapPointType::UNKNOWN);
    events.unknownMonsterOdds = events.unknownEliteOdds = -1;
    events.unknownTreasureOdds = events.unknownShopOdds = -1;
    events.eventBagN = 3;
    events.eventBagPos = 0;
    events.eventBag[0] = wongo;
    events.eventBag[1] = seen;
    events.eventBag[2] = allowed;
    events.visitedEvents = std::uint64_t{1} << seen;
    events.enter_map_point(node);
    assert(events.eventId == allowed && events.eventBagPos == 3);
    assert((events.visitedEvents & (std::uint64_t{1} << allowed)) != 0);
    events.eventBagN = 1;
    events.eventBagPos = 0;
    events.eventBag[0] = wongo;
    events.unknownMonsterOdds = events.unknownEliteOdds = -1;
    events.unknownTreasureOdds = events.unknownShopOdds = -1;
    events.enter_map_point(node);
    assert(events.eventId == wongo && events.eventBagPos == 2);

    RunContext reward_a0, reward_a7;
    reward_a0.init(19, 0);
    reward_a7.init(19, 7);
    reward_a0.cardRarityOdds = reward_a7.cardRarityOdds = -0.05f;
    reward_a0.roll_card_reward(false);
    reward_a7.roll_card_reward(false);
    assert(std::abs(reward_a0.cardRarityOdds - (-0.02f)) < 0.00001f);
    assert(std::abs(reward_a7.cardRarityOdds - (-0.035f)) < 0.00001f);

    // Colorless has no common cards: a common roll promotes to uncommon
    // without a second rarity roll, preserving the subsequent RNG stream.
    TEST_RUN(colorless);
    colorless.init(31, 0);
    Rng expectedRng = colorless.playerRng[PRNG_REWARDS];
    CardId expectedCards[3]{};
    bool promoted = false;
    for (int i = 0; i < 3; ++i) {
        const float roll = expectedRng.next_float();
        Rarity rarity = roll < 0.03f ? Rarity::RARE : Rarity::UNCOMMON;
        promoted |= roll >= 0.37f;
        CardId pool[static_cast<int>(CardId::COUNT)];
        int count = 0;
        for (int id = 1; id < static_cast<int>(CardId::COUNT); ++id) {
            const auto card = static_cast<CardId>(id);
            const CardDef &def = card_def(card);
            bool seen = false;
            for (int j = 0; j < i; ++j) seen |= expectedCards[j] == card;
            if (!seen && def.pool == CardPool::COLORLESS && def.rarity == rarity &&
                !(def.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY))) pool[count++] = card;
        }
        assert(count > 0);
        expectedCards[i] = pool[expectedRng.next_int(0, count - 1)];
        (void)expectedRng.next_float();
    }
    assert(promoted && colorless.queue_card_reward(Rarity::COMMON, true, CardPool::COLORLESS));
    for (int i = 0; i < 3; ++i) assert(colorless.rewardCards[0][i].id == expectedCards[i]);
    assert(colorless.playerRng[PRNG_REWARDS].next_float() == expectedRng.next_float());

    int rare_potions = 0, uncommon_potions = 0;
    Rng potion_rng(517);
    for (int i = 0; i < 20000; ++i) {
        const auto potion = random_potion_out_of_combat(potion_rng);
        const auto rarity = potion_def(potion).rarity;
        assert(potion != PotionId::INVALID && potion_def(potion).ironclad);
        assert(rarity == Rarity::COMMON || rarity == Rarity::UNCOMMON || rarity == Rarity::RARE);
        rare_potions += rarity == Rarity::RARE;
        uncommon_potions += rarity == Rarity::UNCOMMON;
    }
    assert(rare_potions > 1700 && rare_potions < 2300);
    assert(uncommon_potions > 4600 && uncommon_potions < 5400);

    bool pity_changes_shop = false;
    for (int seed = 0; seed < 500; ++seed) {
        TEST_RUN(shop); TEST_RUN(high_pity);
        shop.init(seed, 0);
        shop.floor = 41;
        high_pity = shop;
        shop.cardRarityOdds = -0.05f;
        high_pity.cardRarityOdds = 0.4f;
        shop.roll_shop();
        high_pity.roll_shop();
        assert(shop.cardRarityOdds == -0.05f && high_pity.cardRarityOdds == 0.4f);
        for (int i = 0; i < std::min(5, shop.shopCount); ++i)
            pity_changes_shop |= shop.shopCards[i].id != high_pity.shopCards[i].id;
        for (int i = 0; i < shop.shopRelicCount; ++i) {
            const RelicId id = static_cast<RelicId>(shop.shopRelics[i]);
            assert(id != RelicId::THE_COURIER && id != RelicId::OLD_COIN);
            assert(run_relic_allowed(shop, id));
            for (int j = 0; j < i; ++j) assert(shop.shopRelics[j] != shop.shopRelics[i]);
        }
        for (int i = 0; i < shop.shopPotionCount; ++i) {
            const auto id = static_cast<PotionId>(shop.shopPotions[i]);
            const auto rarity = potion_def(id).rarity;
            assert(potion_def(id).ironclad &&
                   (rarity == Rarity::COMMON || rarity == Rarity::UNCOMMON || rarity == Rarity::RARE));
            for (int j = 0; j < i; ++j) assert(shop.shopPotions[j] != shop.shopPotions[i]);
        }
    }
    assert(pity_changes_shop);

    // The shuffled relic deques persist and front/back pulls cross-remove
    // from the shared bag. Skipping a queued reward does not put it back.
    TEST_RUN(bag_base);
    bag_base.init(777, 0);
    assert(bag_base.playerRelicBag.counts[0] > 1);
    RunContext front = bag_base, back = bag_base;
    const int expected_front = front.playerRelicBag.entries[0][0];
    const int expected_back = back.playerRelicBag.entries[0][back.playerRelicBag.counts[0] - 1];
    const RelicId front_id = front.pull_relic(Rarity::COMMON);
    const RelicId back_id = back.pull_relic(Rarity::COMMON, true);
    assert(static_cast<int>(front_id) == expected_front);
    assert(static_cast<int>(back_id) == expected_back);
    for (int i = 0; i < front.sharedRelicBag.counts[0]; ++i)
        assert(front.sharedRelicBag.entries[0][i] != static_cast<int>(front_id));
    assert(RunContext::restore(front.serialize(), out));
    assert(out.serialize() == front.serialize());

    RunContext fallback = bag_base;
    fallback.playerRelicBag.counts[0] = 0;
    const RelicId next_rarity = fallback.pull_relic(Rarity::COMMON);
    assert(next_rarity != RelicId::INVALID && relic_raw_rarity(next_rarity) == 2);

    RunContext shared = bag_base;
    const RelicId shared_id = shared.pull_relic(Rarity::COMMON, false, true);
    assert(shared_id != RelicId::INVALID);
    assert(shared.add_relic(shared_id));
    for (int i = 0; i < shared.playerRelicBag.counts[0]; ++i)
        assert(shared.playerRelicBag.entries[0][i] != static_cast<int>(shared_id));

    TEST_RUN(exhausted);
    exhausted.init(778, 0);
    for (int &count : exhausted.playerRelicBag.counts) count = 0;
    assert(exhausted.pull_relic(Rarity::COMMON) == RelicId::CIRCLET);
    assert(exhausted.add_relic(RelicId::CIRCLET));
    assert(exhausted.add_relic(RelicId::CIRCLET));
    assert(exhausted.queue_random_relic_reward(exhausted.playerRng[PRNG_REWARDS]));
    assert(exhausted.queue_random_relic_reward(exhausted.playerRng[PRNG_REWARDS]));
    assert(exhausted.pendingRelics[0] == static_cast<int>(RelicId::CIRCLET));
    assert(exhausted.pendingRelics[1] == static_cast<int>(RelicId::CIRCLET));
    exhausted.screen = RunScreen::REWARDS;
    assert(exhausted.step({RunActionType::TAKE_RELIC_REWARD, 0}));
    assert(exhausted.step({RunActionType::TAKE_RELIC_REWARD, 1}));
    assert(RunContext::restore(exhausted.serialize(), out));
    exhausted.screen = RunScreen::SHOP;
    exhausted.shopRelicCount = 1;
    exhausted.shopRelics[0] = static_cast<int>(RelicId::CIRCLET);
    exhausted.shopRelicPrices[0] = 0;
    exhausted.shopRelicBasePrices[0] = 0;
    exhausted.shopRelicSold[0] = false;
    assert(exhausted.step({RunActionType::BUY_RELIC, 0}));

    for (int act = 0; act < MAX_ACTS; ++act) {
        int weak_pool = 0, normal_pool = 0, elite_pool = 0;
        for (int i = 1; i < static_cast<int>(Encounter::COUNT); ++i) {
            const EncounterDef &def = encounter_def(i);
            if (def.act != act + 1 || !def.key || std::strstr(def.key, "BOSS")) continue;
            if (std::strstr(def.key, "ELITE")) ++elite_pool;
            else if (std::strstr(def.key, "WEAK")) ++weak_pool;
            else ++normal_pool;
        }
        const int weak_count = act == 0 ? 3 : 2;
        for (int seed = 0; seed < 100; ++seed) {
            TEST_RUN(bag);
            bag.init(seed, 0);
            if (act != 0) bag.start_act(act);
            assert(bag.normalBagN == bag.map.rooms && bag.eliteBagN == 15);
            for (int i = 0; i < bag.normalBagN; ++i) {
                const char *key = encounter_def(bag.normalBag[i]).key;
                assert((std::strstr(key, "WEAK") != nullptr) == (i < weak_count));
            }
            for (int i = 0; i < std::min(weak_count, weak_pool); ++i)
                for (int j = 0; j < i; ++j) assert(bag.normalBag[i] != bag.normalBag[j]);
            const int normal_end = std::min(bag.normalBagN, weak_count + normal_pool);
            for (int i = weak_count; i < normal_end; ++i)
                for (int j = weak_count; j < i; ++j) assert(bag.normalBag[i] != bag.normalBag[j]);
            for (int i = 0; i < std::min(15, elite_pool); ++i)
                for (int j = 0; j < i; ++j) assert(bag.eliteBag[i] != bag.eliteBag[j]);
        }
    }

    TEST_RUN(cauldron);
    cauldron.init(71, 0);
    cauldron.screen = RunScreen::SHOP;
    assert(cauldron.add_relic(RelicId::CAULDRON));
    assert(cauldron.screen == RunScreen::REWARDS && cauldron.pendingPotionCount == 5);
    for (int i = 0; i < 5; ++i) assert(cauldron.pendingPotions[i] != 0);
    assert(RunContext::restore(cauldron.serialize(), out));
    assert(cauldron.step({RunActionType::TAKE_POTION_REWARD, 4}));
    assert(cauldron.pendingPotions[4] == 0 && cauldron.pendingPotions[0] != 0);
    assert(cauldron.step({RunActionType::LEAVE_REWARDS, 0}));
    assert(cauldron.screen == RunScreen::SHOP);

    TEST_RUN(glass);
    glass.init(72, 0);
    glass.screen = RunScreen::REWARDS;
    glass.pendingGoldReward = 50;
    assert(glass.add_relic(RelicId::GLASS_EYE));
    const Rarity expectedRarities[] = {Rarity::COMMON, Rarity::COMMON, Rarity::UNCOMMON,
                                       Rarity::UNCOMMON, Rarity::RARE};
    for (int i = 0; i < 5; ++i) {
        assert(glass.rewardCardPending[i] && glass.rewardCardCounts[i] == 3);
        for (int j = 0; j < 3; ++j) assert(card_def(glass.rewardCards[i][j].id).rarity == expectedRarities[i]);
    }
    assert(RunContext::restore(glass.serialize(), out));
    assert(glass.step({RunActionType::OPEN_CARD_REWARD, 3}));
    assert(glass.step({RunActionType::SKIP_CARD, 0}));
    assert(!glass.rewardCardPending[3] && glass.rewardCardPending[0] && glass.pendingGoldReward == 50);

    TEST_RUN(coffer);
    coffer.init(73, 0);
    assert(coffer.add_relic(RelicId::LOST_COFFER));
    assert(coffer.screen == RunScreen::REWARDS && coffer.pendingPotionCount == 1 && coffer.rewardCardPending[0]);
    TEST_RUN(bell);
    bell.init(74, 0);
    const int bellDeck = bell.deckCount;
    assert(bell.add_relic(RelicId::CALLING_BELL));
    assert(bell.deckCount == bellDeck + 1 && bell.pendingRelicCount == 3 && bell.screen == RunScreen::REWARDS);
    for (int i = 0; i < 3; ++i) assert(relic_raw_rarity(static_cast<RelicId>(bell.pendingRelics[i])) == i + 1);
    assert(RunContext::restore(bell.serialize(), out));

    TEST_RUN(thief);
    thief.init(75, 0);
    thief.begin_combat(Encounter::SETUP_AXEBOTS_NORMAL);
    Card original = thief.deck[0];
    thief.battle.theftCount = 1;
    thief.battle.theftUids[0] = original.uid;
    thief.battle.theftCards[0] = original;
    thief.battle.theftOwners[0] = 0;
    thief.sync_stolen_cards();
    assert(thief.deckCount == 9 && thief.stolenOriginalPresent[0]);
    assert(RunContext::restore(thief.serialize(), out));
    thief.battle.theftReturned[0] = true;
    thief.battle.outcome = Outcome::PLAYER_VICTORY;
    thief.finish_combat();
    assert(thief.stolenRewardPending[0] && thief.deckCount == 9);
    assert(RunContext::restore(thief.serialize(), out));
    assert(thief.step({RunActionType::TAKE_STOLEN_CARD_REWARD, 0}));
    assert(thief.deckCount == 10 && thief.deck[9].uid == original.uid);
    assert(!thief.stolenRewardPending[0]);

    TEST_RUN(injected);
    injected.init(77, 0);
    injected.nextCombatDazed = 2;
    injected.begin_combat(Encounter::SETUP_AXEBOTS_NORMAL);
    assert(RunContext::restore(injected.serialize(), out));
    for (auto word : injected.battle.uidReservations) assert(word == 0);

    TEST_RUN(escaped);
    escaped.init(76, 0);
    escaped.begin_combat(Encounter::SETUP_AXEBOTS_NORMAL);
    escaped.battle.theftCount = 1;
    escaped.battle.theftUids[0] = escaped.deck[0].uid;
    escaped.battle.theftCards[0] = escaped.deck[0];
    escaped.battle.theftOwners[0] = -1;
    escaped.battle.outcome = Outcome::PLAYER_VICTORY;
    escaped.finish_combat();
    assert(escaped.deckCount == 9 && !escaped.stolenRewardPending[0]);

    TEST_RUN(elite);
    elite.init(29, 0);
    assert(elite.add_relic(RelicId::BLACK_STAR));
    elite.combatIsElite = true;
    elite.begin_combat(Encounter::SETUP_BYRDONIS_ELITE);
    elite.battle.outcome = Outcome::PLAYER_VICTORY;
    const int prior_gold = elite.gold;
    const int prior_relics = elite.relicCount;
    const int prior_deck = elite.deckCount;
    elite.finish_combat();
    assert(elite.screen == RunScreen::REWARDS && elite.gold == prior_gold);
    assert(elite.relicCount == prior_relics && elite.pendingRelicCount == 2);
    assert(elite.pendingRelics[0] != elite.pendingRelics[1]);
    assert(elite.pendingCardReward && elite.deckCount == prior_deck);
    assert(RunContext::restore(elite.serialize(), out));
    assert(elite.step({RunActionType::TAKE_RELIC_REWARD, 1}));
    assert(elite.pendingRelicClaimed[1] && elite.relicCount == prior_relics + 1);
    assert(elite.step({RunActionType::OPEN_CARD_REWARD, 0}));
    assert(elite.screen == RunScreen::CARD_REWARD);
    assert(elite.step({RunActionType::SKIP_CARD, 0}));
    assert(elite.screen == RunScreen::REWARDS && !elite.pendingCardReward);
    assert(elite.step({RunActionType::LEAVE_REWARDS, 0}));
    assert(elite.screen == RunScreen::MAP && elite.gold == prior_gold);

    TEST_RUN(first_boss);
    first_boss.init(29, 0);
    first_boss.combatIsBoss = true;
    first_boss.begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
    first_boss.battle.outcome = Outcome::PLAYER_VICTORY;
    first_boss.finish_combat();
    assert(first_boss.screen == RunScreen::REWARDS && first_boss.pendingCardReward);
    assert(first_boss.step({RunActionType::OPEN_CARD_REWARD, 0}));
    assert(first_boss.step({RunActionType::SKIP_CARD, 0}));
    assert(first_boss.screen == RunScreen::REWARDS);
    assert(first_boss.step({RunActionType::LEAVE_REWARDS, 0}));
    assert(first_boss.act == 1 && first_boss.screen == RunScreen::EVENT);

    TEST_RUN(final_boss);
    final_boss.init(29, 0);
    final_boss.start_act(2);
    final_boss.enter_map_point(final_boss.map.bossIdx);
    final_boss.battle.outcome = Outcome::PLAYER_VICTORY;
    final_boss.finish_combat();
    assert(final_boss.won && final_boss.screen == RunScreen::RUN_OVER);
    assert(final_boss.pendingGoldReward == 0 && !final_boss.pendingCardReward);

    TEST_RUN(double_boss);
    double_boss.init(29, 10);
    double_boss.start_act(2);
    assert(double_boss.map.secondBossIdx >= 0);
    assert(double_boss.secondBossEncounter != double_boss.bossEncounter);
    assert(RunContext::restore(double_boss.serialize(), out));
    double_boss.enter_map_point(double_boss.map.bossIdx);
    assert(static_cast<int>(double_boss.battle.encounter) == double_boss.bossEncounter);
    double_boss.battle.outcome = Outcome::PLAYER_VICTORY;
    double_boss.finish_combat();
    assert(!double_boss.won && double_boss.screen == RunScreen::MAP);
    const auto next_nodes = double_boss.available_map_nodes();
    assert(next_nodes.size() == 1 && next_nodes[0] == double_boss.map.secondBossIdx);
    assert(double_boss.step({RunActionType::MOVE, next_nodes[0]}));
    assert(static_cast<int>(double_boss.battle.encounter) == double_boss.secondBossEncounter);
    double_boss.battle.outcome = Outcome::PLAYER_VICTORY;
    double_boss.finish_combat();
    assert(double_boss.won && double_boss.screen == RunScreen::RUN_OVER);

    TEST_RUN(cutoff);
    cutoff.init(30, 0);
    cutoff.begin_combat(Encounter::SETUP_AXEBOTS_NORMAL);
    cutoff.battle.player.hp = 37;
    cutoff.battle.turn = 200;
    cutoff.battle.end_player_turn();
    assert(cutoff.battle.outcome == Outcome::TRUNCATED);
    cutoff.finish_combat();
    assert(cutoff.truncated && !cutoff.won && cutoff.hp == 37);
    assert(cutoff.screen == RunScreen::RUN_OVER && cutoff.terminal_reward() == 0.0);
    assert(RunContext::restore(cutoff.serialize(), out));

    TEST_RUN(waterfall);
    waterfall.init(31, 0);
    waterfall.begin_combat(Encounter::SETUP_WATERFALL_GIANT_BOSS);
    assert(waterfall.battle.monsterCount > 0);
    waterfall.battle.monsters[0].hp = waterfall.battle.monsters[0].maxHp = 999999999;
    assert(RunContext::restore(waterfall.serialize(), out));

    // Merchant prices use decimal fractions and truncate once, including when
    // both discounts are present.
    for (int seed = 0; seed < 25; ++seed) {
        TEST_RUN(regular); TEST_RUN(member); TEST_RUN(both);
        regular.init(seed, 0);
        member = regular;
        both = regular;
        assert(member.add_relic(RelicId::MEMBERSHIP_CARD));
        assert(both.add_relic(RelicId::MEMBERSHIP_CARD));
        assert(both.add_relic(RelicId::THE_COURIER));
        regular.roll_shop();
        member.roll_shop();
        both.roll_shop();
        assert(regular.shopCount == member.shopCount && regular.shopCount == both.shopCount);
        for (int i = 0; i < regular.shopCount; ++i) {
            assert(member.shopPrices[i] == regular.shopPrices[i] / 2);
            assert(both.shopPrices[i] == regular.shopPrices[i] * 2 / 5);
        }

        // Buy both discounts in the shop. Recompute from unrounded base
        // prices so buying in either order gives the same final result.
        regular.screen = RunScreen::SHOP;
        regular.gold = 100000;
        assert(regular.shopRelicCount > 0);
        regular.shopRelics[0] = static_cast<int>(RelicId::MEMBERSHIP_CARD);
        regular.shopRelicPrices[0] = 0;
        regular.shopRelicBasePrices[0] = 0;
        regular.shopRelicSold[0] = false;
        assert(regular.step({RunActionType::BUY_RELIC, 0}));
        for (int i = 0; i < regular.shopCount; ++i)
            assert(regular.shopPrices[i] == regular.shopBasePrices[i] / 2);
        regular.shopRelics[0] = static_cast<int>(RelicId::THE_COURIER);
        regular.shopRelicPrices[0] = 0;
        regular.shopRelicBasePrices[0] = 0;
        regular.shopRelicSold[0] = false;
        assert(regular.step({RunActionType::BUY_RELIC, 0}));
        for (int i = 0; i < regular.shopCount; ++i)
            assert(regular.shopPrices[i] == regular.shopBasePrices[i] * 2 / 5);
    }
    src.init(42, 0);
    out.init(7, 0);
    const std::string valid = src.serialize();
    assert(RunContext::restore(valid, out));
    assert(out.serialize() == valid);
    const auto check = [&](std::size_t off, int value) {
        std::string bad = valid;
        corrupt(bad, off, value);
        rejects_atomically(bad, out);
    };
    const auto offset = [&](const void *member) {
        return static_cast<std::size_t>(static_cast<const char *>(member) -
                                        reinterpret_cast<const char *>(&src));
    };
    check(offset(&src.deckCount), INT_MAX);
    check(offset(&src.offeredCount), INT_MAX);
    check(offset(&src.potionCount), -1);
    check(offset(&src.relicCount), INT_MAX);
    check(offset(&src.hp), -1);
    check(offset(&src.gold), -1);
    check(offset(&src.battle.drawCount), INT_MAX);
    check(offset(&src.battle.pending.count), INT_MAX);
    check(offset(&src.battle.toricCount), INT_MAX);
    check(offset(&src.battle.rollingCount), INT_MAX);
    check(offset(&src.battle.panacheCount), INT_MAX);
    check(offset(&src.battle.monsters[0].grappleCount), INT_MAX);
    std::string invalid_card = valid;
    corrupt(invalid_card, offset(&src.deck[0].id),
            static_cast<std::uint16_t>(CardId::COUNT));
    rejects_atomically(invalid_card, out);
    std::string invalid_bool = valid;
    corrupt(invalid_bool, offset(&src.won), static_cast<unsigned char>(2));
    rejects_atomically(invalid_bool, out);
    std::string invalid_map = valid;
    corrupt(invalid_map, offset(&src.map.nodes[0].childCount),
            static_cast<unsigned char>(MAP_MAX_EDGES + 1));
    rejects_atomically(invalid_map, out);

    // Real snapshots, including combat and card choices, should remain valid.
    int checked = 0;
    for (int seed = 0; seed < 100; ++seed) {
        TEST_RUN(run);
        run.init(seed, 0);
        Rng rng(static_cast<std::uint32_t>(seed));
        for (int step = 0; step < 300 && !run.is_over(); ++step) {
            const std::string state = run.serialize();
            if (!RunContext::restore(state, out)) {
                std::cerr << "valid snapshot rejected: seed=" << seed << " step=" << step
                          << " screen=" << static_cast<int>(run.screen) << "\n";
                return 1;
            }
            assert(out.serialize() == state);
            ++checked;
            if (run.inBattle) {
                const auto actions = run.battle.legal_actions();
                if (actions.empty()) break;
                assert(run.step_combat(actions[rng.next_index(static_cast<int>(actions.size()))]));
            } else {
                const auto actions = run.legal_actions();
                if (actions.empty()) break;
                assert(run.step(actions[rng.next_index(static_cast<int>(actions.size()))]));
            }
        }
    }
    std::cout << "validated " << checked << " live snapshots and rejected malformed inputs\n";
}
