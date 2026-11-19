// Native UI/command decision boundaries. Source-based tests, not DLL replays.
#include "sts2/run.h"
#include "sts2/relics.h"
#include "sts2/observe.h"
#include "sts2/macro_obs.h"
#include "sts2/combat_obs.h"
#include <cassert>
#include <cstring>
#include <iostream>
#include <memory>
using namespace sts2;

static Action pick(int uid) { Action a; a.type=ActionType::CHOOSE; a.uid=uid; return a; }
static Action confirm() { Action a; a.type=ActionType::CONFIRM; return a; }
static Action potion(ActionType type, int slot) { Action a; a.type=type; a.hand=slot; return a; }
static int event_id(const char *name) {
    for(int i=0;i<event_count();++i) if(!std::strcmp(event_info(i)->name,name)) return i;
    assert(false); return -1;
}
static bool has(const BattleContext &b, ActionType type) {
    for(auto &a:b.legal_actions()) if(a.type==type) return true;
    return false;
}
int main() {
    auto run=std::make_unique<RunContext>(); auto &r=*run; r.init(70231,10);
    r.begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
    auto &b=r.battle;
    b.handCount=3; b.drawCount=b.discardCount=b.exhaustCount=0;
    for(int i=0;i<3;++i) b.hand[i]=make_card(CardId::DEFEND_IRONCLAD,false,100+i);
    b.start_choice(ChoiceOp::UPGRADE,ChoicePile::HAND,1,false,Card{},false);
    b.pending.hasSource=false;
    assert(!has(b,ActionType::CONFIRM));
    assert(b.step(pick(100)) && b.pending.selectedCount==1 && !b.hand[0].upgraded);
    assert(has(b,ActionType::CONFIRM));
    assert(b.step(pick(101)) && b.pending.selectedCount==1 && b.pending.selectedUids[0]==101);
    assert(b.step(pick(101)) && b.pending.selectedCount==0 && !has(b,ActionType::CONFIRM));
    assert(b.step(pick(100)));
    auto restored=std::make_unique<RunContext>();
    assert(RunContext::restore(r.serialize(),*restored));
    assert(restored->battle.pending.selectedUids[0]==100);
    assert(restored->battle.step(confirm()));
    assert(restored->battle.hand[0].uid==100 && restored->battle.hand[0].upgraded);
    assert(b.step(confirm()) && b.pending.op==ChoiceOp::NONE);
    assert(b.hand[0].uid==100 && b.hand[1].uid==101 && b.hand[0].upgraded);

    // The selected hand remains intact until confirmation; queued belt actions
    // cannot be submitted twice or execute through the suspended card action.
    b.start_choice(ChoiceOp::DISCARD_ANY,ChoicePile::HAND,3,true,Card{},false);
    b.pending.hasSource=false;
    b.add_potion(PotionId::BLOOD_POTION); b.add_potion(PotionId::FIRE_POTION);
    b.player.hp=30;
    assert(b.step(potion(ActionType::USE_POTION,0)));
    assert(b.step(potion(ActionType::DISCARD_POTION,1)));
    assert(b.potionCount==2 && b.player.hp==30 && b.queuedPotionActionCount==2);
    assert(!b.step(potion(ActionType::DISCARD_POTION,0)));
    assert(b.step(pick(101)) && b.handCount==3 && b.discardCount==0);
    assert(RunContext::restore(r.serialize(),*restored));
    assert(b.step(confirm()));
    assert(b.queuedPotionActionCount==0 && b.potionCount==0 && b.player.hp==46);
    assert(restored->battle.step(confirm()) && restored->battle.player.hp==46);
    assert(public_combat_observation(b).size()==PUBLIC_COMBAT_OBS_DIM);
    assert(combat_action_features(b,potion(ActionType::DISCARD_POTION,1)).size()==ACTION_FEAT_DIM);

    r.inBattle=false; r.screen=RunScreen::EVENT;
    event_begin(r,event_id("ABYSSAL_BATHS"),false);
    assert(r.step({RunActionType::EVENT_CHOICE,1}));
    assert(r.screen==RunScreen::EVENT && r.eventPage==127 && event_option_count(r)==1);
    assert(r.step({RunActionType::EVENT_CHOICE,0}) && r.screen==RunScreen::MAP);

    // Closed chests must not reveal the pre-rolled relic to any legacy actor.
    r.screen=RunScreen::TREASURE; r.treasureStage=0; r.treasureRelic=static_cast<int>(RelicId::GORGET);
    auto before=macro_observation(r); auto flat=public_observation(r);
    r.treasureRelic=static_cast<int>(RelicId::ANCHOR);
    auto after=macro_observation(r);
    assert(before.kind==after.kind && before.id==after.id && before.num==after.num);
    assert(flat==public_observation(r));
    assert(r.step({RunActionType::COLLECT,0}) && r.screen==RunScreen::TREASURE && r.treasureStage==1);
    assert(r.step({RunActionType::TAKE_TREASURE_RELIC,0}));
    assert(r.screen==RunScreen::TREASURE && r.treasureStage==2);
    assert(r.step({RunActionType::LEAVE_TREASURE,0}) && r.screen==RunScreen::MAP);
    assert(RunContext::restore(r.serialize(),*restored));

    // Cleared fragments do not reveal the identity of a partly hidden prize.
    r.screen=RunScreen::EVENT;
    auto &sphere=r.crystalSphere; sphere.active=true; sphere.divinations=3;
    sphere.itemCount=1; sphere.itemPlaced[0]=true; sphere.cellItem[0]=1;
    sphere.hidden[0]=2; sphere.cellItem[1]=1; sphere.itemType[0]=3;
    before=macro_observation(r); flat=public_observation(r);
    sphere.itemType[0]=5;
    after=macro_observation(r);
    assert(before.kind==after.kind && before.id==after.id && before.num==after.num);
    assert(flat==public_observation(r));
    sphere.hidden[0]=0; sphere.revealedCount=1; sphere.revealed[0]=0;
    assert(macro_observation(r).id!=after.id && public_observation(r)!=flat);
    sphere=CrystalSphereState{};

    r.begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
    b.handCount=3; b.drawCount=b.discardCount=b.exhaustCount=0;
    for(int i=0;i<3;++i)b.hand[i]=make_card(CardId::DEFEND_IRONCLAD,false,200+i);
    // These counters belong to the power instance, not to turn history before
    // the power was applied. Tender's debuffs also obey Artifact individually.
    b.cardsPlayedThisTurn=5;
    b.add_player_power(PowerId::SLOTH,1);
    b.add_player_power(PowerId::TENDER,1);
    b.add_player_power(PowerId::ARTIFACT,1);
    assert(b.slothCardsPlayedThisTurn==0 && b.tenderCardsPlayedThisTurn==0);
    auto plays=b.legal_actions();
    auto playable=std::find_if(plays.begin(),plays.end(),[](const Action &a){return a.type==ActionType::PLAY_CARD;});
    assert(playable!=plays.end() && b.step(*playable));
    assert(b.slothCardsPlayedThisTurn==1 && b.tenderCardsPlayedThisTurn==1);
    assert(!has(b,ActionType::PLAY_CARD));
    assert(b.player_power(PowerId::ARTIFACT)==0 && b.player_power(PowerId::STRENGTH)==0 &&
           b.player_power(PowerId::DEXTERITY)==-1);
    b.end_player_turn();
    assert(b.tenderCardsPlayedThisTurn==0 && b.player_power(PowerId::STRENGTH)==1 &&
           b.player_power(PowerId::DEXTERITY)==0);
    b.add_player_power(PowerId::SLOTH,-1);
    assert(b.slothCardsPlayedThisTurn==0);

    // Hex is a real affliction and cannot replace another affliction.
    b.handCount=2;
    b.hand[0]=make_card(CardId::DEFEND_IRONCLAD,false,301);
    b.hand[1]=make_card(CardId::DEFEND_IRONCLAD,false,302); b.hand[1].bound=true;
    b.add_player_power(PowerId::HEX,1);
    assert(b.hand[0].hexed && !b.hand[1].hexed && b.hand[1].bound);
    assert(RunContext::restore(r.serialize(),*restored));
    assert(restored->battle.hand[0].hexed && !restored->battle.hand[1].hexed);
    b.add_player_power(PowerId::HEX,-1);
    assert(!b.hand[0].hexed && b.hand[1].bound);
    static_assert(sizeof(Card)==304,"Card size must remain compatible with stack budgets");
    // Native A6 changes shop prices, not the map's rest-site count.
    for(int act=0;act<3;++act) {
        ActMap a5{},a6{}; Rng rng5(4242),rng6(4242);
        generate_act_map(a5,rng5,act,5); generate_act_map(a6,rng6,act,6);
        assert(a5.pointCount==a6.pointCount && rng5.counter==rng6.counter);
        for(int i=0;i<a5.pointCount;++i) {
            assert(a5.nodes[i].type==a6.nodes[i].type);
            assert(a5.nodes[i].childCount==a6.nodes[i].childCount);
            for(int j=0;j<a5.nodes[i].childCount;++j)assert(a5.nodes[i].children[j]==a6.nodes[i].children[j]);
        }
    }
    std::cout << "Native decision boundaries, public power instances and hidden-state observations passed\n";
}
