// Source ports of the fifteen former v11 relic coverage boundaries.
// These tests exercise decisions/state transitions; they are not DLL parity evidence.
#include "sts2/relics.h"
#include "sts2/card_candidates.h"
#include <cassert>
#include <iostream>
#include <memory>
using namespace sts2;
namespace {
std::unique_ptr<RunContext> run() {
    auto r=std::make_unique<RunContext>();r->init(4321,10);
    r->screen=RunScreen::MAP;return r;
}
std::unique_ptr<BattleContext> battle(std::initializer_list<RelicId> relics) {
    auto b=std::make_unique<BattleContext>();Card deck[12];int ids[MAX_RELICS],n=0;
    for(int i=0;i<12;++i)deck[i]=make_card(CardId::STRIKE_IRONCLAD,false,i+1);
    for(auto id:relics)ids[n++]=static_cast<int>(id);
    b->init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS,321,deck,12,10,80,80,ids,n);
    return b;
}
void snapshot(const RunContext &r) {
    auto restored=std::make_unique<RunContext>();assert(RunContext::restore(r.serialize(),*restored));
    assert(restored->serialize()==r.serialize());
}
Action choose(int uid) { Action a;a.type=ActionType::CHOOSE;a.uid=uid;return a; }
Action confirm() { Action a;a.type=ActionType::CONFIRM;return a; }
void win(RunContext &r,bool elite=false) {
    r.combatIsElite=elite;r.combatIsBoss=false;
    r.begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
    r.battle.outcome=Outcome::PLAYER_VICTORY;r.finish_combat();
}
int reward_count(const RunContext &r) {int n=0;for(bool p:r.rewardCardPending)n+=p;return n;}
}
int main() {
    static_assert(sizeof(Card)==304,"Momentum must not enlarge the per-card state");
    for(auto id:{RelicId::JUZU_BRACELET,RelicId::GAMBLING_CHIP,RelicId::LASTING_CANDY,
        RelicId::PRAYER_WHEEL,RelicId::UNSETTLING_LAMP,RelicId::WHITE_STAR,RelicId::DOLLYS_MIRROR,
        RelicId::GNARLED_HAMMER,RelicId::KIFUDA,RelicId::MINIATURE_TENT,RelicId::MYSTIC_LIGHTER,
        RelicId::ORRERY,RelicId::PUNCH_DAGGER,RelicId::ROYAL_STAMP,RelicId::WING_CHARM})assert(relic_implemented(id));
    {
        auto r=run();assert(r->add_relic(RelicId::JUZU_BRACELET));
        r->unknownMonsterOdds=1;r->unknownTreasureOdds=r->unknownShopOdds=0;
        const auto rng=r->runRng[RNG_UNKNOWN_MAP_POINT].counter;
        for(int i=0;i<10;++i)assert(r->roll_unknown_room_type()!=static_cast<int>(RoomType::MONSTER));
        assert(r->unknownMonsterOdds==1 && r->runRng[RNG_UNKNOWN_MAP_POINT].counter==rng+10);
        r->nativeProgress.numberOfRuns=0;r->unknownMapPointsVisited=2;
        assert(r->roll_unknown_room_type()==static_cast<int>(RoomType::MONSTER)); // tutorial precedes relic
        assert(!run_relic_allowed(*r,RelicId::LASTING_CANDY));
    }
    {
        auto r=run();assert(r->add_relic(RelicId::DOLLYS_MIRROR));
        const int before=r->deckCount;assert(r->cardGrid.kind==17);
        r->deck[0].bonusDamage=3;const auto uid=r->deck[0].uid;
        assert(r->step({RunActionType::SELECT_GRID_CARD,0}));
        assert(r->cardGrid.preview && r->deckCount==before);snapshot(*r);
        assert(r->step({RunActionType::CONFIRM_GRID_CARDS,0}));
        assert(r->deckCount==before+1 && r->deck[before].uid!=uid && r->deck[before].bonusDamage==3);
    }
    for(auto id:{RelicId::GNARLED_HAMMER,RelicId::KIFUDA}) {
        auto r=run();assert(r->add_relic(id));
        assert(r->cardGrid.minSelect==0 && r->cardGrid.maxSelect==3);
        int selected[3],n=0;
        for(int i=0;i<r->deckCount && n<3;++i)if(card_grid_can_select(*r,i)) {
            selected[n++]=i;assert(r->step({RunActionType::SELECT_GRID_CARD,i}));
        }
        assert(n==3 && r->cardGrid.preview && r->cardGrid.selectedCount==3);
        assert(r->deck[selected[0]].enchantment==EnchantmentId::NONE);snapshot(*r);
        assert(r->step({RunActionType::CANCEL_GRID_PREVIEW,0}));
        assert(r->cardGrid.selectedCount==0);
        assert(r->step({RunActionType::SELECT_GRID_CARD,selected[1]}));
        assert(r->step({RunActionType::SELECT_GRID_CARD,selected[2]}));
        assert(r->step({RunActionType::CONFIRM_GRID_CARDS,0}));assert(r->cardGrid.preview);
        assert(r->deck[selected[1]].enchantment==EnchantmentId::NONE);
        assert(r->step({RunActionType::CONFIRM_GRID_CARDS,0}));
        assert(r->deck[selected[0]].enchantment==EnchantmentId::NONE);
        assert(r->deck[selected[1]].enchantmentAmount==3);
    }
    for(auto id:{RelicId::GNARLED_HAMMER,RelicId::KIFUDA}) for(int count=1;count<=2;++count) {
        auto r=run();r->deckCount=count;assert(r->add_relic(id));
        assert(r->cardGrid.maxSelect==3);
        for(int i=0;i<count;++i)assert(r->step({RunActionType::SELECT_GRID_CARD,i}));
        assert(!r->cardGrid.preview);snapshot(*r);
        assert(r->step({RunActionType::CONFIRM_GRID_CARDS,0}));assert(r->cardGrid.preview);snapshot(*r);
        assert(r->step({RunActionType::CONFIRM_GRID_CARDS,0}));assert(!r->cardGrid.kind);
        for(int i=0;i<count;++i)assert(r->deck[i].enchantmentAmount==3);
    }
    {
        auto r=run();assert(r->add_relic(RelicId::KIFUDA));
        assert(r->step({RunActionType::CONFIRM_GRID_CARDS,0}));assert(r->cardGrid.preview);
        assert(r->step({RunActionType::CONFIRM_GRID_CARDS,0}));assert(r->cardGrid.kind==19 && r->cardGrid.selectedCount==0);
        snapshot(*r);
    }
    {
        auto r=run();assert(r->add_relic(RelicId::PUNCH_DAGGER));
        int i=0;while(!card_grid_can_select(*r,i))++i;
        assert(r->step({RunActionType::SELECT_GRID_CARD,i}));assert(r->cardGrid.preview);
        assert(r->step({RunActionType::CONFIRM_GRID_CARDS,0}));
        assert(r->deck[i].enchantment==EnchantmentId::MOMENTUM && r->deck[i].enchantmentAmount==5);
        auto b=battle({});Card card=make_card(CardId::BODY_SLAM,false,600);
        assert(card_apply_enchantment(card,EnchantmentId::MOMENTUM,5));card.momentumExtraDamage=10;
        assert(b->enchant_card_damage(card,7)==17); // calculated damage, not card's static DamageVar
        b->handCount=1;b->hand[0]=card;b->player.block=7;b->player.energy=9;
        b->step({ActionType::PLAY_CARD,0,0,0});
        assert(b->discard[b->discardCount-1].momentumExtraDamage==15);
    }
    {
        auto r=run();int eligible=0;
        for(int i=0;i<r->deckCount;++i)eligible+=card_can_enchant(r->deck[i],EnchantmentId::ROYALLY_APPROVED);
        const auto calls=r->runRng[RNG_NICHE].counter;
        assert(r->add_relic(RelicId::ROYAL_STAMP));
        assert(r->runRng[RNG_NICHE].counter==calls+eligible-1);
        assert(r->step({RunActionType::SELECT_GRID_CARD,0}));assert(r->step({RunActionType::CONFIRM_GRID_CARDS,0}));
        assert(card_has(r->deck[0],CF_INNATE) && card_has(r->deck[0],CF_RETAIN));
    }
    {
        auto b=battle({RelicId::MYSTIC_LIGHTER});Card card=make_card(CardId::STRIKE_IRONCLAD,false,600);
        assert(b->calc_player_damage(6,0,true,&card)==6);
        assert(card_apply_enchantment(card,EnchantmentId::ADROIT,3));
        assert(b->calc_player_damage(6,0,true,&card)==15);
        assert(b->calc_player_damage(6,0,false,&card)==6);
        b->handCount=1;b->hand[0]=card;b->player.dexterity=2;b->player.energy=9;
        b->step({ActionType::PLAY_CARD,0,0,0});assert(b->player.block==5);
    }
    {
        auto r=run();assert(r->add_relic(RelicId::WING_CHARM));const auto calls=r->runRng[RNG_NICHE].counter;
        assert(r->add_relic(RelicId::ORRERY));assert(reward_count(*r)==5);
        for(int i=0;i<5;++i) {int swift=0;for(int k=0;k<r->rewardCardCounts[i];++k)
            swift+=r->rewardCards[i][k].enchantment==EnchantmentId::SWIFT;assert(swift==1);}
        assert(r->runRng[RNG_NICHE].counter==calls+5);
        const auto rewardsRng=r->playerRng[PRNG_REWARDS].counter;
        assert(r->step({RunActionType::OPEN_CARD_REWARD,0}));const Card first=r->offered[0];
        assert(r->step({RunActionType::SKIP_CARD,0}));assert(r->rewardCardPending[0]);
        assert(r->step({RunActionType::OPEN_CARD_REWARD,0}));
        assert(r->offered[0].uid==first.uid && r->playerRng[PRNG_REWARDS].counter==rewardsRng);snapshot(*r);
    }
    {
        auto r=run();assert(r->add_relic(RelicId::PRAYER_WHEEL));assert(r->add_relic(RelicId::LASTING_CANDY));
        win(*r);assert(reward_count(*r)==2 && r->rewardCardCounts[0]==3 && r->rewardCardCounts[1]==3);
        assert(r->step({RunActionType::LEAVE_REWARDS,0}));win(*r);
        assert(reward_count(*r)==2 && r->rewardCardCounts[0]==4 && r->rewardCardCounts[1]==4);
        assert(card_type(r->rewardCards[0][3])==CardType::POWER && card_type(r->rewardCards[1][3])==CardType::POWER);
        int seen=0;for(int i=0;i<r->relicCount;++i)if(r->relics[i]==static_cast<int>(RelicId::LASTING_CANDY))seen=r->relicAux[i];
        assert(seen==2);snapshot(*r);
    }
    {
        auto r=run();assert(r->add_relic(RelicId::WHITE_STAR));assert(r->add_relic(RelicId::PRAYER_WHEEL));
        win(*r,true);assert(reward_count(*r)==2);
        for(int i=0;i<r->rewardCardCounts[1];++i)assert(card_def(r->rewardCards[1][i].id).rarity==Rarity::RARE);
    }
    {
        auto r=run();assert(r->add_relic(RelicId::MINIATURE_TENT));r->screen=RunScreen::REST;r->hp=30;
        assert(r->step({RunActionType::REST_HEAL,0}));assert(r->screen==RunScreen::REST && (r->restUsedOptions&1));
        assert(!r->step({RunActionType::REST_HEAL,0}));assert(r->step({RunActionType::REST_UPGRADE,0}));
        assert(r->cardGrid.service==1);assert(r->step({RunActionType::CANCEL_GRID_SELECTION,0}));
        assert(!(r->restUsedOptions&2));assert(r->step({RunActionType::REST_UPGRADE,0}));
        assert(r->step({RunActionType::SELECT_GRID_CARD,0}));snapshot(*r);
        assert(r->step({RunActionType::CONFIRM_GRID_CARDS,0}));assert(r->restUsedOptions==3 && r->deck[0].upgraded);
        assert(r->step({RunActionType::REST_PROCEED,0}));assert(r->screen==RunScreen::MAP);
        r->screen=RunScreen::SHOP;r->gold=200;r->removalPrice=75;const int n=r->deckCount;
        assert(r->step({RunActionType::REMOVE_CARD,0}));assert(r->step({RunActionType::CANCEL_GRID_SELECTION,0}));
        assert(r->gold==200 && r->deckCount==n && !r->removalUsed);
        assert(r->step({RunActionType::REMOVE_CARD,0}));assert(r->step({RunActionType::SELECT_GRID_CARD,0}));
        assert(r->step({RunActionType::CONFIRM_GRID_CARDS,0}));assert(r->gold==125 && r->deckCount==n-1 && r->removalUsed);
    }
    {
        auto r=run();assert(r->add_relic(RelicId::GAMBLING_CHIP));r->begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
        auto &b=r->battle;assert(b.pending.op==ChoiceOp::GAMBLING_CHIP);
        const int hand=b.handCount,draw=b.drawCount,uid=b.hand[0].uid;
        assert(b.step(choose(uid)));assert(b.handCount==hand && b.drawCount==draw && b.pending.selectedCount==1);
        snapshot(*r);assert(b.step(choose(uid)));assert(b.pending.selectedCount==0);
        assert(b.step(choose(uid)));assert(b.step(confirm()));
        assert(b.pending.op==ChoiceOp::NONE && b.handCount==hand && b.drawCount==draw-1 && b.discardCount==1);
        assert(b.discard[0].uid==uid);b.start_player_turn();assert(b.pending.op==ChoiceOp::NONE);
    }
    {
        auto r=run();assert(r->add_relic(RelicId::GAMBLING_CHIP));r->begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
        auto &b=r->battle;const int hand=b.handCount;
        b.drawCount=0;b.discardCount=2;
        for(int i=0;i<2;++i)b.discard[i]=make_card(CardId::DEFEND_IRONCLAD,false,800+i);
        b.add_player_power(PowerId::STRATAGEM,1);
        const int first=b.hand[0].uid,second=b.hand[1].uid;
        assert(b.step(choose(first)) && b.step(choose(second)) && b.step(confirm()));
        assert(b.pending.op==ChoiceOp::DRAW_TO_HAND && b.pending.remaining==1);
        assert(b.handCount==hand-2 && b.silent.turnStartSelectedCount==0);snapshot(*r);
        assert(b.step(choose(b.pending.cards[0].uid)));
        assert(b.pending.op==ChoiceOp::NONE && b.handCount==hand+1 && b.pendingDrawRemainder==0);snapshot(*r);
    }
    {
        auto r=run();r->begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);auto &b=r->battle;
        b.handCount=3;b.drawCount=0;b.discardCount=4;b.player.energy=9;
        b.hand[0]=make_card(CardId::BURNING_PACT,false,600);
        for(int i=1;i<3;++i)b.hand[i]=make_card(CardId::STRIKE_IRONCLAD,false,600+i);
        for(int i=0;i<4;++i)b.discard[i]=make_card(CardId::DEFEND_IRONCLAD,false,700+i);
        b.add_player_power(PowerId::DARK_EMBRACE,1);b.add_player_power(PowerId::STRATAGEM,1);
        assert(b.step({ActionType::PLAY_CARD,0,0,0}));assert(b.pending.op==ChoiceOp::EXHAUST);
        assert(b.step(choose(601)) && b.step(confirm()));
        assert(b.pending.op==ChoiceOp::DRAW_TO_HAND && b.pending.remaining==1 && b.confirmedExhaustCount==1);
        assert(b.handCount==1 && b.activePlay.active);snapshot(*r);
        assert(b.step(choose(b.pending.cards[0].uid)));
        assert(b.pending.op==ChoiceOp::NONE && b.confirmedExhaustCount==0 && !b.activePlay.active);
        assert(b.handCount==5 && b.exhaustCount==1 && b.pendingDrawRemainder==0);snapshot(*r);
    }
    {
        auto r=run();r->begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);auto &b=r->battle;
        b.handCount=3;b.drawCount=0;b.discardCount=6;
        for(int i=0;i<3;++i)b.hand[i]=make_card(CardId::STRIKE_IRONCLAD,false,600+i);
        for(int i=0;i<6;++i)b.discard[i]=make_card(CardId::DEFEND_IRONCLAD,false,700+i);
        b.add_player_power(PowerId::DARK_EMBRACE,1);b.add_player_power(PowerId::STRATAGEM,1);
        b.start_choice(ChoiceOp::EXHAUST,ChoicePile::HAND,3,true,Card{},false);b.pending.hasSource=false;
        assert(b.step(choose(600)) && b.step(choose(601)) && b.step(confirm()));
        assert(b.pending.op==ChoiceOp::DRAW_TO_HAND && b.pending.remaining==1 && b.exhaustCount==1);
        assert(b.find_in_hand(601)!=nullptr);snapshot(*r);
        assert(b.step(choose(b.pending.cards[0].uid)));
        assert(b.pending.op==ChoiceOp::NONE && b.confirmedExhaustCount==0 && b.exhaustCount==2);
        assert(b.handCount==4 && b.pendingDrawRemainder==0);snapshot(*r);
    }
    {
        auto b=battle({RelicId::TOOLBOX,RelicId::GAMBLING_CHIP});
        assert(b->pending.op==ChoiceOp::OFFER_TO_HAND && b->handCount==0);
        assert(!b->step(confirm()));
        assert(b->step(choose(b->pending.cards[0].uid)));assert(b->pending.op==ChoiceOp::GAMBLING_CHIP && b->handCount==6);
        assert(b->step(confirm()));assert(b->pending.op==ChoiceOp::NONE);
    }
    {
        auto b=battle({RelicId::UNSETTLING_LAMP});b->activePlay.active=true;b->activePlay.card=make_card(CardId::BASH,false,600);
        b->monsters[0].power[static_cast<int>(PowerId::ARTIFACT)]=1;
        b->apply_vulnerable(0,2);assert(b->monsters[0].vulnerable==0 && relic_aux(*b,RelicId::UNSETTLING_LAMP)==0);
        b->apply_vulnerable(0,2,false);assert(b->monsters[0].vulnerable==2 && relic_aux(*b,RelicId::UNSETTLING_LAMP)==0);
        b->apply_vulnerable(0,2);b->apply_weak(0,3);
        assert(b->monsters[0].vulnerable==6 && b->monsters[0].weak==6);
        relics_card_played(*b,b->activePlay.card);assert(relic_aux(*b,RelicId::UNSETTLING_LAMP)==-1);
        b->apply_weak(0,1);assert(b->monsters[0].weak==7);
    }
    {
        auto r=run();assert(r->add_relic(RelicId::UNSETTLING_LAMP));r->begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
        auto &b=r->battle;int slot=0;while(b.relics[slot]!=static_cast<int>(RelicId::UNSETTLING_LAMP))++slot;
        b.activePlay.active=true;b.activePlay.card=make_card(CardId::BASH,false,600);b.inMonsterTurn=true;
        b.apply_weak(0,1);assert(b.monsters[0].weak==2);b.inMonsterTurn=false;
        snapshot(*r);auto restored=std::make_unique<RunContext>();
        b.relicAux2[slot]=static_cast<int>(PowerId::COUNT)+1;
        assert(!RunContext::restore(r->serialize(),*restored));
    }
    {
        auto b=battle({RelicId::UNSETTLING_LAMP});b->handCount=1;
        b->hand[0]=make_card(CardId::DARK_SHACKLES,false,600);const int base=b->monsters[0].strength;
        assert(b->step({ActionType::PLAY_CARD,0,0,0}));
        assert(b->monsters[0].strength==base-2*card_var(make_card(CardId::DARK_SHACKLES,false,600),VarId::STRENGTH_LOSS));
    }
    {
        auto b=battle({RelicId::UNSETTLING_LAMP});b->activePlay.active=true;
        b->activePlay.card=make_card(CardId::MISERY,false,600);
        // Native DoubledPowers retains the first power only: when Weak triggers
        // first, a later temporary wrapper and its internal Strength both double.
        b->apply_weak(0,1);const int base=b->monsters[0].strength;
        b->add_monster_power(0,PowerId::DARK_SHACKLES,2,true);
        assert(b->monster_power(0,PowerId::DARK_SHACKLES)==4);
        b->add_monster_power(0,PowerId::STRENGTH,-4,true);
        assert(b->monsters[0].strength==base-8);
    }
    {
        auto b=battle({RelicId::UNSETTLING_LAMP});b->activePlay.active=true;
        b->activePlay.card=make_card(CardId::MANGLE,false,600);
        const int base=b->monsters[0].strength;b->apply_strength_loss(0,3);
        assert(b->monsters[0].strength==base-6 && b->monsters[0].tempStrengthLoss==6);
    }
    {
        auto r=run();assert(r->add_relic(RelicId::PUMPKIN_CANDLE));assert(run_energy_bonus(*r)==1);
        for(int k=0;k<5;++k) {win(*r);assert(r->step({RunActionType::LEAVE_REWARDS,0}));}
        assert(run_energy_bonus(*r)==0);r->screen=RunScreen::REST;
        assert(r->step({RunActionType::REST_KINDLE,0}));assert(run_energy_bonus(*r)==1);
        assert(r->restUsedOptions==255);snapshot(*r);
    }
    {
        auto b=battle({RelicId::PENDULUM});assert(relic_aux(*b,RelicId::PENDULUM)==1);
        for(int i=0;i<b->handCount;++i)b->move_to_discard(b->hand[i]);
        b->handCount=0;b->start_player_turn();assert(relic_aux(*b,RelicId::PENDULUM)==2);
        for(int i=0;i<b->handCount;++i)b->move_to_discard(b->hand[i]);
        b->handCount=0;b->start_player_turn();assert(relic_aux(*b,RelicId::PENDULUM)==0 && b->handCount==6);
        const int before=b->handCount;relics_shuffled(*b);assert(b->handCount==before);
    }
    {
        auto b=battle({RelicId::STONE_CALENDAR});b->turn=7;
        const int hp=b->monsters[0].hp;relics_turn_start(*b);assert(b->monsters[0].hp==hp);
        relics_turn_end(*b,b->player.block==0);assert(b->monsters[0].hp==std::max(0,hp-52));
    }
    {
        auto r=run();assert(r->add_relic(RelicId::PAELS_EYE));r->begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
        auto &b=r->battle;const int hp=b.player.hp,round=b.combatRound,hand=b.handCount;
        b.end_player_turn();assert(b.turn==2 && b.combatRound==round && b.player.hp==hp);
        assert(b.exhaustCount==hand && relic_aux(b,RelicId::PAELS_EYE)==1);snapshot(*r);
        b.end_player_turn();assert(b.combatRound==round+1);
    }
    {
        auto r=run();assert(r->add_relic(RelicId::PAELS_EYE));r->begin_combat(Encounter::SETUP_CEREMONIAL_BEAST_BOSS);
        auto &b=r->battle;const int initialHand=b.handCount;
        std::copy(b.draw,b.draw+b.drawCount,b.discard);b.discardCount=b.drawCount;b.drawCount=0;
        b.player.power[static_cast<int>(PowerId::DARK_EMBRACE)]=1;
        b.player.power[static_cast<int>(PowerId::STRATAGEM)]=1;
        b.end_player_turn();assert(b.pending.op==ChoiceOp::DRAW_TO_HAND && b.turnFlow.stage==TURN_FLOW_PAELS_EYE_END);
        snapshot(*r);
        for(int guard=0;guard<20 && b.pending.op!=ChoiceOp::NONE;++guard)assert(b.step(choose(b.pending.cards[0].uid)));
        assert(b.turn==2 && b.exhaustCount==initialHand && b.pendingDrawRemainder==0);
        snapshot(*r);
    }
    {
        auto b=battle({RelicId::BRILLIANT_SCARF});b->player.energy=99;
        Card card=make_card(CardId::ANGER,false,600);b->auto_play_random(card,false);
        assert(b->manualCardsPlayedThisTurn==0 && b->cardsPlayedThisTurn>0);
        b->manualCardsPlayedThisTurn=4;Card bash=make_card(CardId::BASH,false,601);
        assert(b->energy_cost_in_combat(bash)==0);
    }
    std::cout << "15 formerly unsupported relic effects, selections, counters and snapshots passed\n";
}
