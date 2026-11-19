// Source-port contracts from CardReward, RewardSynchronizer, Driftwood,
// ForbiddenGrimoirePower and TheLanternKey. Not a native DLL execution trace.
#include "sts2/run.h"
#include "sts2/relic_card_rewards.h"
#include "sts2/card_candidates.h"
#include <cassert>
#include <iostream>
#include <memory>
using namespace sts2;
static std::unique_ptr<RunContext> base() {
    auto r=std::make_unique<RunContext>(); r->init_seed("REWARDCONTRACT",10);
    r->screen=RunScreen::SHOP; return r;
}
static bool has(const RunContext&r,RunActionType type) {
    for(auto a:r.legal_actions())if(a.type==type)return true;return false;
}
static void roundtrip(RunContext&r) {
    auto saved=std::make_unique<RunContext>();assert(RunContext::restore(r.serialize(),*saved));
    assert(saved->serialize()==r.serialize());
}
int main() {
    {
        auto r=base();assert(r->add_relic(RelicId::DRIFTWOOD));
        assert(r->queue_card_reward(Rarity::COMMON,true));
        r->deferredCustomRewards=false;r->screen=RunScreen::REWARDS;
        const auto before=r->playerRng[PRNG_REWARDS].counter;
        assert(r->step({RunActionType::OPEN_CARD_REWARD,0}));
        assert(has(*r,RunActionType::REROLL_CARD_REWARD));
        roundtrip(*r);
        assert(r->step({RunActionType::REROLL_CARD_REWARD,0}));
        assert(r->playerRng[PRNG_REWARDS].counter>before);
        assert(!has(*r,RunActionType::REROLL_CARD_REWARD));
        Card cards[4];std::copy(r->offered,r->offered+r->offeredCount,cards);
        const auto after=r->playerRng[PRNG_REWARDS].counter;
        assert(r->step({RunActionType::SKIP_CARD,0}));
        assert(r->rewardCardPending[0]);
        assert(r->step({RunActionType::OPEN_CARD_REWARD,0}));
        assert(!has(*r,RunActionType::REROLL_CARD_REWARD));
        for(int i=0;i<r->offeredCount;++i)assert(r->offered[i].uid==cards[i].uid);
        assert(r->playerRng[PRNG_REWARDS].counter==after);
        roundtrip(*r);
    }
    {
        auto r=base();r->screen=RunScreen::REWARDS;r->pendingCardRemovals=2;
        // A sole eligible card must still present select/preview/confirm.
        r->deckCount=1;r->deck[0]=r->make_run_card(CardId::BASH,false);
        const int gold=r->gold;
        assert(r->step({RunActionType::OPEN_CARD_REMOVAL_REWARD,1}));
        assert(r->cardGrid.service==3 && r->deckCount==1 && r->pendingCardRemovals==2);
        assert(r->step({RunActionType::CANCEL_GRID_SELECTION,0}));
        assert(r->pendingCardRemovals==2);
        assert(r->step({RunActionType::OPEN_CARD_REMOVAL_REWARD,0}));
        assert(r->step({RunActionType::SELECT_GRID_CARD,0}));
        assert(r->cardGrid.preview && r->deckCount==1);
        roundtrip(*r);
        assert(r->step({RunActionType::CANCEL_GRID_PREVIEW,0}));
        assert(r->step({RunActionType::SELECT_GRID_CARD,0}));
        assert(r->step({RunActionType::CONFIRM_GRID_CARDS,0}));
        assert(r->deckCount==0 && r->pendingCardRemovals==1 && r->gold==gold);
        assert(r->step({RunActionType::OPEN_CARD_REMOVAL_REWARD,0}));
        assert(!r->cardGrid.kind && r->pendingCardRemovals==1);
        roundtrip(*r);
    }
    {
        auto r=base();const int before=r->deckCount;
        assert(r->queue_special_card_reward(r->make_run_card(CardId::LANTERN_KEY,false)));
        r->deferredCustomRewards=false;r->screen=RunScreen::REWARDS;
        assert(has(*r,RunActionType::TAKE_SPECIAL_CARD_REWARD));
        assert(!has(*r,RunActionType::OPEN_CARD_REWARD) && r->deckCount==before);
        roundtrip(*r);
        assert(r->step({RunActionType::TAKE_SPECIAL_CARD_REWARD,0}));
        assert(r->deckCount==before+1 && r->deck[before].id==CardId::LANTERN_KEY);
        assert(!has(*r,RunActionType::TAKE_SPECIAL_CARD_REWARD));
    }
    {
        auto r=base();r->begin_combat(Encounter::SETUP_SLIMES_WEAK);
        r->battle.add_player_power(PowerId::FORBIDDEN_GRIMOIRE,2);
        r->battle.outcome=Outcome::PLAYER_VICTORY;r->finish_combat();
        assert(r->pendingCardRemovals==2 && has(*r,RunActionType::OPEN_CARD_REMOVAL_REWARD));
        roundtrip(*r);
    }
    std::cout<<"native_reward_contract: source regression passed\n";
}
