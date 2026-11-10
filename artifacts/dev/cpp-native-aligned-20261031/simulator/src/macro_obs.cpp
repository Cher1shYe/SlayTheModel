#include "sts2/macro_obs.h"

#include "sts2/card_candidates.h"
#include "sts2/observe.h"
#include "sts2/relics.h"
#include "sts2/search.h"

#include <algorithm>
#include <cassert>
#include <stdexcept>

namespace sts2 {
namespace {

constexpr int EVENT_OPTION_VOCAB = MAX_EVENTS * MAX_EVENT_CHOICES;

bool visited(const RunContext &rc, int idx) {
    if (idx < 0) return false;
    if (idx < 64) return (rc.visitedLo >> idx) & 1u;
    if (idx < 128) return (rc.visitedHi >> (idx - 64)) & 1u;
    return false;
}

// Generated-card selectors keep their own cards; every other selector indexes
// the master deck (see begin_card_grid / begin_deck_relic_choice).
bool grid_uses_own_cards(int kind) { return kind == 1 || kind == 2 || kind == 5 || kind == 13 || kind == 14; }

class Builder {
public:
    explicit Builder(MacroObservation &out) : out_(out) {}

    // Starts an entity and returns its index; push numeric features with f().
    int begin(MacroEntity kind, int id) {
        finish();
        const int index = static_cast<int>(out_.kind.size());
        out_.kind.push_back(static_cast<std::int32_t>(kind));
        out_.id.push_back(id);
        open_ = 0;
        out_.num.resize(out_.num.size() + MACRO_ENTITY_NUM, 0.0f);
        base_ = out_.num.size() - MACRO_ENTITY_NUM;
        return index;
    }
    void f(float value) {
        if (open_ >= MACRO_ENTITY_NUM) throw std::logic_error("macro entity feature overflow");
        out_.num[base_ + open_++] = value;
    }
    void one_hot(int index, int count) {
        for (int i = 0; i < count; ++i) f(i == index ? 1.0f : 0.0f);
    }
    void finish() {}

private:
    MacroObservation &out_;
    std::size_t base_ = 0;
    int open_ = 0;
};

// Static and instance features of one visible card (no UID, no deck position).
void card_numeric(Builder &b, const Card &c) {
    const CardDef &d = card_def(c.id);
    const int cost = card_cost(c);
    b.f(cost < 0 ? 1.0f : 0.0f);               // X cost
    b.f(cost < 0 ? 0.0f : cost / 3.0f);
    b.one_hot(static_cast<int>(card_type(c)), 6);
    b.one_hot(static_cast<int>(d.rarity), 11);
    b.f(c.upgraded ? 1.0f : 0.0f);
    b.f(card_damage(c) / 30.0f);
    b.f(card_block(c) / 30.0f);
    b.f(c.replay / 4.0f);
    b.f(c.bonusReplay / 4.0f);
    b.f(c.freeCombat ? 1.0f : 0.0f);
    b.f(c.costThisTurn ? 1.0f : 0.0f);
    b.f(c.combatCostCap / 3.0f);
    b.f(c.bonusDamage / 30.0f);
    b.f(c.bonusBlock / 30.0f);
    b.f(c.etherealThisCombat ? 1.0f : 0.0f);
    b.f(c.retainThisCombat ? 1.0f : 0.0f);
    b.f(std::min<int>(99, c.galvanized) / 10.0f);
    b.f(c.guiltyCombatsSeen / 5.0f);
    b.one_hot(static_cast<int>(c.enchantment), static_cast<int>(ENCHANTMENT_LAST) + 1);
    b.f(c.enchantmentAmount / 10.0f);
    b.f(c.enchantmentDisabled ? 1.0f : 0.0f);
    b.f(c.tinkerType / 3.0f);
    b.f(c.tinkerRider / 9.0f);
}
constexpr int CARD_NUMERIC = 2 + 6 + 11 + 1 + 2 + 2 + 2 + 1 + 3 + 2 + 1 + 1 + 1 +
                             (static_cast<int>(ENCHANTMENT_LAST) + 1) + 2 + 2;
static_assert(CARD_NUMERIC + 8 <= MACRO_ENTITY_NUM, "card features plus offer metadata must fit");

enum OfferSource { SRC_REWARD, SRC_SHOP, SRC_GRID, SRC_STOLEN, SRC_STORED, SRC_EVENT, SRC_PENDING, SRC_COUNT };

}  // namespace

int macro_id_vocab(MacroEntity kind) {
    switch (kind) {
        case MacroEntity::GLOBAL: return 1;
        case MacroEntity::CONTEXT: return MAX_EVENTS + 1;
        case MacroEntity::DECK_CARD:
        case MacroEntity::OFFER_CARD: return static_cast<int>(CardId::COUNT);
        case MacroEntity::RELIC:
        case MacroEntity::OFFER_RELIC: return static_cast<int>(RelicId::COUNT);
        case MacroEntity::POTION:
        case MacroEntity::OFFER_POTION: return static_cast<int>(PotionId::COUNT);
        case MacroEntity::MAP_NODE: return 9;
        case MacroEntity::BOSS: return static_cast<int>(Encounter::COUNT);
        case MacroEntity::REWARD: return 4;  // gold, recovered gold, extra gold, card-reward slot
        case MacroEntity::EVENT_OPTION: return EVENT_OPTION_VOCAB;
        case MacroEntity::SPHERE_CELL: return CRYSTAL_SPHERE_ITEM_TYPES + 1;
        default: return 0;
    }
}

MacroObservation macro_observation(const RunContext &rc) {
    MacroObservation out;
    Builder b(out);
    const int screen = static_cast<int>(rc.screen);
    const RunCardGrid &grid = rc.cardGrid;
    out.phase = screen * 2 + (grid.kind ? 1 : 0);
    const bool rewardsVisible = rc.screen == RunScreen::REWARDS ||
        (rc.screen == RunScreen::CARD_REWARD && rc.rewardReturnToRewards);

    // --- GLOBAL --------------------------------------------------------------
    b.begin(MacroEntity::GLOBAL, 0);
    b.f(rc.maxHp > 0 ? static_cast<float>(rc.hp) / rc.maxHp : 0.0f);
    b.f(rc.hp / 100.0f);
    b.f(rc.maxHp / 100.0f);
    b.f(rc.gold / 300.0f);
    b.f(rc.floor / 49.0f);
    b.one_hot(rc.act, 3);
    b.f(rc.actFloor / 16.0f);
    b.f(rc.ascension / 10.0f);
    b.f(rc.deckCount / 40.0f);
    int upgrades = 0;
    for (int i = 0; i < rc.deckCount; ++i) upgrades += rc.deck[i].upgraded ? 1 : 0;
    b.f(rc.deckCount > 0 ? static_cast<float>(upgrades) / rc.deckCount : 0.0f);
    b.f(rc.relicCount / 20.0f);
    b.f(rc.potionSlots / 5.0f);
    b.f(rc.potionCount / 5.0f);
    b.f(rc.combatsFought / 40.0f);
    b.f(rc.elitesFought / 10.0f);
    b.f(rc.bossesFought / 3.0f);
    b.f(rc.teaSetPending ? 1.0f : 0.0f);
    b.f(rc.cardsAdded / 10.0f);
    b.f(rc.nextCombatEnergy / 10.0f);
    b.f(rc.nextCombatUpgradeHand ? 1.0f : 0.0f);
    b.f(rc.nextCombatDazed / 10.0f);
    b.f(rc.emberTeaCombats / 10.0f);
    b.f(rc.furCoatCombats / 10.0f);
    b.f(rc.toyBoxCombats / 15.0f);
    b.f(rc.wongoCombats / 6.0f);
    b.f(rc.swordOfStoneWins / 10.0f);
    b.f(rc.paelsWingSkips / 10.0f);
    b.f(rc.silverCrucibleUses / 10.0f);
    b.f(rc.mawBankPurchased ? 1.0f : 0.0f);
    b.f(rc.treasureSkipped ? 1.0f : 0.0f);
    b.f(rc.removalPrice / 200.0f);
    b.f(rc.removalUsed ? 1.0f : 0.0f);
    b.f(rc.cardShopRemovalsUsed / 5.0f);
    b.one_hot(rc.goldenPathAct + 1, 4);
    b.f(rc.unknownMapPointsVisited / 30.0f);
    for (const auto type : rc.actTypes) b.one_hot(static_cast<int>(type), 4);
    const bool spoils = rc.spoils_quest_active();
    b.f(spoils ? 1.0f : 0.0f);
    b.f(rc.paelsToothCount / 5.0f);
    b.f(rc.pendingRelicObtainCount / 5.0f);

    // --- CONTEXT -------------------------------------------------------------
    b.begin(MacroEntity::CONTEXT, rc.screen == RunScreen::EVENT && rc.eventId >= 0 ? rc.eventId + 1 : 0);
    b.one_hot(screen, 9);
    b.f(rc.eventPage / 4.0f);
    b.f(rc.eventChoiceCount / 8.0f);
    b.f(rc.eventCombat ? 1.0f : 0.0f);
    b.f(rc.eventCardSelection / 15.0f);
    b.one_hot(grid.kind, 16);
    b.f(grid.count / 40.0f);
    b.f(grid.selectedCount / 8.0f);
    b.f(grid.minSelect / 8.0f);
    b.f(grid.maxSelect / 8.0f);
    b.f(grid.preview ? 1.0f : 0.0f);
    b.f(grid.slotCount / 8.0f);
    b.f(grid.kind ? grid.damageAfterSelection / 16.0f : 0.0f);
    b.f(grid.kind ? static_cast<int>(grid.curseAfterSelection) / static_cast<float>(CardId::COUNT) : 0.0f);
    b.f(rewardsVisible ? 1.0f : 0.0f);
    b.f(rewardsVisible && rc.pendingReturnToEvent ? 1.0f : 0.0f);
    b.f(rewardsVisible && rc.deferredCustomRewards ? 1.0f : 0.0f);
    b.f(rc.rewardIsBoss ? 1.0f : 0.0f);
    b.f(rc.crystalSphere.active ? 1.0f : 0.0f);
    b.f(rc.crystalSphere.active ? rc.crystalSphere.divinations / 6.0f : 0.0f);
    b.f(rc.screen == RunScreen::CARD_REWARD ? rc.offeredCount / 4.0f : 0.0f);

    // --- DECK ----------------------------------------------------------------
    std::vector<int> deckEntity(rc.deckCount, -1);
    const bool gridOnDeck = grid.kind && !grid_uses_own_cards(grid.kind);
    for (int i = 0; i < rc.deckCount; ++i) {
        deckEntity[i] = b.begin(MacroEntity::DECK_CARD, static_cast<int>(rc.deck[i].id));
        card_numeric(b, rc.deck[i]);
        b.f(gridOnDeck && i < grid.count && grid.selected[i] ? 1.0f : 0.0f);
    }

    // --- RELICS / POTIONS ------------------------------------------------------
    for (int i = 0; i < rc.relicCount; ++i) {
        b.begin(MacroEntity::RELIC, rc.relics[i]);
        b.f(rc.relicAux[i] / 10.0f);
        b.f(rc.relicWax[i] ? 1.0f : 0.0f);
        b.f(rc.relicMelted[i] ? 1.0f : 0.0f);
        b.f(i / 30.0f);  // pickup order is public and matters for hook order
    }
    std::vector<int> potionEntity(rc.potionSlots, -1);
    for (int i = 0; i < rc.potionSlots; ++i) {
        potionEntity[i] = b.begin(MacroEntity::POTION, rc.potions[i]);
        b.f(i / 5.0f);
        b.f(rc.potions[i] ? 0.0f : 1.0f);
    }

    // --- MAP -----------------------------------------------------------------
    const std::vector<int> reachable = rc.available_map_nodes();
    const int current = rc.map.at(rc.curRow, rc.curCol);
    std::vector<int> nodeEntity(rc.map.pointCount, -1);
    for (int idx = 0; idx < rc.map.pointCount; ++idx) {
        int row = -1, col = -1;
        for (int r = 0; r < MAP_MAX_ROWS && row < 0; ++r)
            for (int c = 0; c < MAP_WIDTH; ++c)
                if (rc.map.index[r][c] == idx) { row = r; col = c; break; }
        if (row < 0) continue;
        const MapNode &n = rc.map.nodes[idx];
        nodeEntity[idx] = b.begin(MacroEntity::MAP_NODE, std::clamp<int>(n.type, 0, 8));
        b.f(row / 16.0f);
        b.f(col / 6.0f);
        b.f(std::find(reachable.begin(), reachable.end(), idx) != reachable.end() ? 1.0f : 0.0f);
        b.f(visited(rc, idx) ? 1.0f : 0.0f);
        b.f(idx == current ? 1.0f : 0.0f);
        b.f(n.childCount / 4.0f);
        b.f(n.parentCount / 4.0f);
        b.f(spoils && row == rc.spoilsQuestRow && col == rc.spoilsQuestCol ? 1.0f : 0.0f);
        b.f(rc.curRow >= 0 ? (row - rc.curRow) / 16.0f : row / 16.0f);
    }
    for (int idx = 0; idx < rc.map.pointCount; ++idx) {
        if (nodeEntity[idx] < 0) continue;
        const MapNode &n = rc.map.nodes[idx];
        for (int k = 0; k < n.childCount; ++k) {
            const int child = n.children[k];
            if (child < rc.map.pointCount && nodeEntity[child] >= 0) {
                out.edges.push_back(nodeEntity[idx]);
                out.edges.push_back(nodeEntity[child]);
            }
        }
    }
    for (int boss : {rc.bossEncounter, rc.secondBossEncounter}) {
        if (boss <= 0) continue;
        b.begin(MacroEntity::BOSS, boss);
        b.f(boss == rc.secondBossEncounter ? 1.0f : 0.0f);
    }

    // --- OFFERS --------------------------------------------------------------
    auto offer_card = [&](const Card &c, int source, int price, bool sold) {
        const int e = b.begin(MacroEntity::OFFER_CARD, static_cast<int>(c.id));
        card_numeric(b, c);
        b.one_hot(source, SRC_COUNT);
        b.f(price >= 0 ? price / 200.0f : 0.0f);
        b.f(sold ? 1.0f : 0.0f);
        return e;
    };
    auto offer_relic = [&](int relic, int source, int price, bool taken) {
        const int e = b.begin(MacroEntity::OFFER_RELIC, relic);
        b.one_hot(source, SRC_COUNT);
        b.f(price >= 0 ? price / 300.0f : 0.0f);
        b.f(taken ? 1.0f : 0.0f);
        return e;
    };
    auto offer_potion = [&](int potion, int source, int price, bool sold) {
        const int e = b.begin(MacroEntity::OFFER_POTION, potion);
        b.one_hot(source, SRC_COUNT);
        b.f(price >= 0 ? price / 150.0f : 0.0f);
        b.f(sold ? 1.0f : 0.0f);
        return e;
    };

    std::vector<int> rewardCard(MAX_REWARD_CARD_CHOICES, -1);
    if (rc.screen == RunScreen::CARD_REWARD)
        for (int i = 0; i < rc.offeredCount; ++i) rewardCard[i] = offer_card(rc.offered[i], SRC_REWARD, -1, false);

    std::vector<int> shopCard(MAX_SHOP_CARDS, -1), shopRelic(MAX_SHOP_RELICS, -1), shopPotion(MAX_SHOP_POTIONS, -1);
    if (rc.screen == RunScreen::SHOP) {
        for (int i = 0; i < rc.shopCount; ++i)
            shopCard[i] = offer_card(rc.shopCards[i], SRC_SHOP, rc.shopPrices[i], rc.shopSold[i]);
        for (int i = 0; i < rc.shopRelicCount; ++i)
            shopRelic[i] = offer_relic(rc.shopRelics[i], SRC_SHOP, rc.shopRelicPrices[i], rc.shopRelicSold[i]);
        for (int i = 0; i < rc.shopPotionCount; ++i)
            shopPotion[i] = offer_potion(rc.shopPotions[i], SRC_SHOP, rc.shopPotionPrices[i], rc.shopPotionSold[i]);
    }

    std::vector<int> gridCard(grid.kind && grid_uses_own_cards(grid.kind) ? grid.count : 0, -1);
    for (int i = 0; i < static_cast<int>(gridCard.size()); ++i) {
        gridCard[i] = offer_card(grid.cards[i], SRC_GRID, -1, false);
        // Selection state of generated choices lives on the offer itself.
        out.num[static_cast<std::size_t>(gridCard[i]) * MACRO_ENTITY_NUM + MACRO_ENTITY_NUM - 1] =
            grid.selected[i] ? 1.0f : 0.0f;
    }

    std::vector<int> rewardRelic(MAX_REWARD_RELICS, -1), rewardPotion(MAX_REWARD_POTIONS, -1);
    std::vector<int> goldReward(2 + MAX_EXTRA_GOLD_REWARDS, -1), cardSlot(MAX_CARD_REWARDS, -1);
    std::vector<int> stolenCard(MAX_PILE, -1);
    if (rewardsVisible) {
        for (int i = 0; i < rc.pendingRelicCount; ++i)
            rewardRelic[i] = offer_relic(rc.pendingRelics[i], SRC_REWARD, -1, rc.pendingRelicClaimed[i]);
        for (int i = 0; i < rc.pendingPotionCount; ++i)
            if (rc.pendingPotions[i]) rewardPotion[i] = offer_potion(rc.pendingPotions[i], SRC_REWARD, -1, false);
        const int amounts[2] = {rc.pendingGoldReward, rc.pendingRecoveredGold};
        for (int k = 0; k < 2 + MAX_EXTRA_GOLD_REWARDS; ++k) {
            const int amount = k < 2 ? amounts[k] : rc.extraGoldRewards[k - 2];
            if (amount <= 0) continue;
            goldReward[k] = b.begin(MacroEntity::REWARD, k < 2 ? k : 2);
            b.f(amount / 300.0f);
        }
        for (int i = 0; i < MAX_CARD_REWARDS; ++i) {
            if (!rc.rewardCardPending[i]) continue;
            cardSlot[i] = b.begin(MacroEntity::REWARD, 3);  // contents hidden until opened
            b.f(0.0f);
            b.f(i / static_cast<float>(MAX_CARD_REWARDS));
        }
        for (int i = 0; i < rc.stolenSyncCount; ++i)
            if (rc.stolenOriginalPresent[i] && rc.stolenRewardPending[i])
                stolenCard[i] = offer_card(rc.stolenOriginals[i], SRC_STOLEN, -1, false);
    }
    for (int i = 0; i < rc.paelsToothCount; ++i) offer_card(rc.paelsToothCards[i], SRC_STORED, -1, false);
    for (int i = 0; i < rc.pendingRelicObtainCount; ++i) offer_relic(rc.pendingRelicObtains[i], SRC_PENDING, -1, false);

    // --- EVENT ---------------------------------------------------------------
    std::vector<int> eventOption(MAX_EVENT_CHOICES, -1), eventRelic(MAX_EVENT_CHOICES, -1);
    if (rc.screen == RunScreen::EVENT && rc.eventId >= 0 && !rc.crystalSphere.active) {
        for (int i = 0; i < rc.eventChoiceCount && i < MAX_EVENT_CHOICES; ++i) {
            eventOption[i] = b.begin(MacroEntity::EVENT_OPTION,
                                     std::clamp<int>(rc.eventId, 0, MAX_EVENTS - 1) * MAX_EVENT_CHOICES + i);
            b.f(i / 8.0f);
            b.f(event_option_available(rc, i) ? 1.0f : 0.0f);
            b.f(rc.eventData[i] / 100.0f);
            b.f(rc.eventRelics[i] > 0 ? 1.0f : 0.0f);
            if (rc.eventRelics[i] > 0) eventRelic[i] = offer_relic(rc.eventRelics[i], SRC_EVENT, -1, false);
        }
    }
    std::vector<int> sphereCell(CRYSTAL_SPHERE_CELLS, -1);
    if (rc.crystalSphere.active) {
        const CrystalSphereState &g = rc.crystalSphere;
        for (int c = 0; c < CRYSTAL_SPHERE_CELLS; ++c) {
            const bool hidden = (g.hidden[c / 64] >> (c % 64)) & 1u;
            const int item = !hidden ? g.cellItem[c] - 1 : -1;
            sphereCell[c] = b.begin(MacroEntity::SPHERE_CELL, item >= 0 ? g.itemType[item] + 1 : 0);
            b.f((c / CRYSTAL_SPHERE_SIZE) / 10.0f);
            b.f((c % CRYSTAL_SPHERE_SIZE) / 10.0f);
            b.f(hidden ? 1.0f : 0.0f);
        }
    }

    // --- CANDIDATES ------------------------------------------------------------
    for (const RunAction &a : rc.legal_actions()) {
        int target = -1, target2 = -1, price = -1;
        const int i = a.index;
        auto at = [](const std::vector<int> &v, int k) { return k >= 0 && k < static_cast<int>(v.size()) ? v[k] : -1; };
        switch (a.type) {
            case RunActionType::MOVE: target = at(nodeEntity, i); break;
            case RunActionType::TAKE_CARD: target = at(rewardCard, i); break;
            case RunActionType::REST_UPGRADE:
            case RunActionType::REMOVE_CARD:
            case RunActionType::EVENT_SELECT_CARD: target = at(deckEntity, i); break;
            case RunActionType::BUY_CARD: target = at(shopCard, i); price = rc.shopPrices[i]; break;
            case RunActionType::BUY_RELIC: target = at(shopRelic, i); price = rc.shopRelicPrices[i]; break;
            case RunActionType::BUY_POTION: target = at(shopPotion, i); price = rc.shopPotionPrices[i]; break;
            case RunActionType::EVENT_CHOICE: target = at(eventOption, i); target2 = at(eventRelic, i); break;
            case RunActionType::USE_POTION:
            case RunActionType::DISCARD_POTION: target = at(potionEntity, i); break;
            case RunActionType::TAKE_GOLD_REWARD: target = at(goldReward, i); break;
            case RunActionType::TAKE_POTION_REWARD: target = at(rewardPotion, i); break;
            case RunActionType::TAKE_RELIC_REWARD: target = at(rewardRelic, i); break;
            case RunActionType::OPEN_CARD_REWARD: target = at(cardSlot, i); break;
            case RunActionType::TAKE_STOLEN_CARD_REWARD:
            case RunActionType::SKIP_STOLEN_CARD_REWARD: target = at(stolenCard, i); break;
            case RunActionType::SELECT_GRID_CARD:
                target = grid_uses_own_cards(grid.kind) ? at(gridCard, i) : at(deckEntity, i);
                break;
            case RunActionType::CRYSTAL_SPHERE_SMALL:
            case RunActionType::CRYSTAL_SPHERE_BIG: target = at(sphereCell, i); break;
            default: break;
        }
        if (a.type == RunActionType::REMOVE_CARD) price = rc.removalPrice;
        out.candType.push_back(static_cast<std::int32_t>(a.type));
        out.candIndex.push_back(i);
        out.candTarget.push_back(target);
        out.candTarget2.push_back(target2);
        out.candNum.push_back(price >= 0 ? price / 300.0f : 0.0f);
        out.candNum.push_back(price >= 0 && price > rc.gold ? 1.0f : 0.0f);
        out.candNum.push_back(i / 40.0f);
        out.candNum.push_back(target >= 0 ? 1.0f : 0.0f);
    }
    return out;
}

CombatDriveResult play_combat_mcts(RunContext &rc, int normalSimulations, int bossSimulations,
                                   double exploration, std::uint32_t seedBase, int decisionIndexStart,
                                   double rolloutEpsilon, double potionWeight, int maxSteps) {
    CombatDriveResult result;
    int decision = decisionIndexStart;
    for (int step = 0; step < maxSteps && rc.screen == RunScreen::COMBAT; ++step) {
        const std::vector<Action> legal = rc.battle.legal_actions();
        if (legal.empty()) {
            // A decided battle still needs one step to settle the run screen.
            if (!rc.step_combat(Action{})) { result.ok = false; break; }
            continue;
        }
        Action chosen = legal.front();
        if (legal.size() > 1) {
            const int budget = rc.combatIsBoss ? bossSimulations : normalSimulations;
            const auto seed = static_cast<std::uint32_t>(seedBase + 7919u * static_cast<std::uint32_t>(decision));
            ++decision;
            ++result.decisions;
            const MctsResult r = mcts(rc.battle, budget, exploration, seed, /*resample=*/true,
                                      /*greedy_rollout=*/false, rolloutEpsilon, potionWeight);
            result.simulations += r.simulations;
            if (r.actions.empty() ||
                std::find(legal.begin(), legal.end(), r.actions.front()) == legal.end()) {
                result.ok = false;
                break;
            }
            chosen = r.actions.front();
        } else {
            ++result.forced;
        }
        if (!rc.step_combat(chosen)) { result.ok = false; break; }
    }
    if (rc.screen == RunScreen::COMBAT) result.ok = false;  // step cap reached
    return result;
}

}  // namespace sts2
