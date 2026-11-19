#include "sts2/run.h"
#include "sts2/relics.h"
#include "sts2/card_candidates.h"
#include <iostream>
#include <set>
using namespace sts2;
namespace {
int checks=0,failures=0;
void check(const char *name,bool ok){++checks;failures+=!ok;std::cout<<name<<(ok?" PASS\n":" FAIL\n");}
RunContext base(std::uint64_t seed=42) {
    RunContext r;r.init(147,0);r.screen=RunScreen::SHOP;r.deckCount=0;r.relicCount=0;r.hp=30;r.maxHp=80;
    for(CardId id:{CardId::STRIKE_IRONCLAD,CardId::DEFEND_IRONCLAD,CardId::BASH,CardId::ANGER,CardId::POMMEL_STRIKE,CardId::IRON_WAVE})
        r.deck[r.deckCount++]=r.make_run_card(id,false);
    r.runRng[RNG_NICHE]=Rng(seed);r.playerRng[PRNG_REWARDS]=Rng(seed);return r;
}
bool choose(RunContext &r,std::initializer_list<int> selected){
    for(int i:selected)if(!r.step({RunActionType::SELECT_GRID_CARD,i}))return false;
    return r.step({RunActionType::CONFIRM_GRID_CARDS,0});
}
int upgrades(const RunContext&r){int n=0;for(int i=0;i<r.deckCount;++i)n+=r.deck[i].upgraded;return n;}
bool upgraded_indices(const RunContext&r,std::initializer_list<int> indices) {
    std::set<int> want(indices);for(int i=0;i<r.deckCount;++i)if(r.deck[i].upgraded!=(want.count(i)>0))return false;return true;
}
}
int main(){
    for (const auto boundary : {std::pair<int,int>{34,80},{35,80},{40,80},{41,80},{79,80},{40,81},{41,81}}) {
        auto r=base();r.hp=boundary.first;r.maxHp=boundary.second;
        r.add_relic(RelicId::BURNING_BLOOD);r.add_relic(RelicId::MEAT_ON_THE_BONE);
        relics_combat_end(r,true,false);
        const int expected=std::min(boundary.second,boundary.first+(boundary.first<=boundary.second/2?12:0)+6);
        check("MeatOnTheBone checks pre-BurningBlood HP",r.hp==expected);
    }
    {
        auto r=base();r.hp=40;r.add_relic(RelicId::BLACK_BLOOD);r.add_relic(RelicId::MEAT_ON_THE_BONE);
        relics_combat_end(r,true,false);check("MeatOnTheBone checks pre-BlackBlood HP",r.hp==64);
        r.hp=0;relics_combat_end(r,true,false);check("Victory heal cannot revive dead owner",r.hp==0);
        r.hp=40;relics_combat_end(r,false,false);check("Defeat does not trigger victory healing",r.hp==40);
    }
    {
        auto r=base();check("Pomander opens upgrade choice",r.add_relic(RelicId::POMANDER)&&r.cardGrid.kind==9&&r.cardGrid.maxSelect==1&&upgrades(r)==0);
        check("Pomander upgrades requested Bash",choose(r,{2})&&upgraded_indices(r,{2}));
        check("Pomander consumes no RNG",r.runRng[RNG_NICHE].counter==0);
    }
    {
        auto r=base();check("YummyCookie opens four-card choice",r.add_relic(RelicId::YUMMY_COOKIE)&&r.cardGrid.kind==9&&r.cardGrid.maxSelect==4);
        check("YummyCookie upgrades chosen identities",choose(r,{5,2,3,0})&&upgraded_indices(r,{0,2,3,5}));
        check("YummyCookie consumes no RNG",r.runRng[RNG_NICHE].counter==0);
    }
    {
        auto r=base();for(int i=0;i<5;++i)card_apply_upgrade(r.deck[i]);
        check("Upgrade choice auto-takes sole eligible card",r.add_relic(RelicId::POMANDER)&&!r.cardGrid.kind&&upgrades(r)==6);
        check("Empty upgrade choice consumes no RNG",r.add_relic(RelicId::YUMMY_COOKIE)&&!r.cardGrid.kind&&r.runRng[RNG_NICHE].counter==0);
    }
    {
        auto r=base();r.screen=RunScreen::MAP;
        check("Spiral grid filters nonbasic Bash",begin_deck_relic_choice(r,11,1)&&!card_grid_can_select(r,2)&&card_grid_can_select(r,0));
        check("Spiral choice keeps deck and applies amount1",choose(r,{0})&&r.deckCount==6&&r.deck[0].enchantment==EnchantmentId::SPIRAL&&r.deck[0].enchantmentAmount==1&&r.screen==RunScreen::MAP);
        check("Steady grid opens exact two choices",begin_deck_relic_choice(r,12,2)&&r.cardGrid.maxSelect==2&&!card_grid_can_select(r,0));
        check("Steady choices can wait for confirmation",r.step({RunActionType::SELECT_GRID_CARD,2})&&r.step({RunActionType::SELECT_GRID_CARD,4})&&r.cardGrid.preview&&r.deck[2].enchantment==EnchantmentId::NONE);
        RunContext saved;check("Steady selected snapshot",RunContext::restore(r.serialize(),saved));
        check("Steady choice applies both",r.step({RunActionType::CONFIRM_GRID_CARDS,0})&&r.deck[2].enchantment==EnchantmentId::STEADY&&r.deck[4].enchantment==EnchantmentId::STEADY&&r.deckCount==6);
    }
    {
        auto r=base();check("PaelTooth opens eligible choice",r.add_relic(RelicId::PAELS_TOOTH)&&r.cardGrid.kind==10);
        check("PaelTooth removes exactly selected five",choose(r,{5,4,0,2,3})&&r.deckCount==1&&r.deck[0].id==CardId::DEFEND_IRONCLAD&&r.paelsToothCount==5);
        CardId sorted[]={CardId::ANGER,CardId::BASH,CardId::IRON_WAVE,CardId::POMMEL_STRIKE,CardId::STRIKE_IRONCLAD};
        std::set<int> storedUids;for(int i=0;i<5;++i)storedUids.insert(r.paelsToothCards[i].uid);
        bool ordered=true;for(int i=0;i<5;++i)ordered&=r.paelsToothCards[i].id==sorted[i];
        check("PaelTooth saves ordinal ID order",ordered);
        RunContext restored;check("PaelTooth stored cards survive snapshot",RunContext::restore(r.serialize(),restored)&&restored.paelsToothCount==5);
        auto invalid=r;invalid.paelsToothCount=6;check("Reject oversized PaelTooth queue",!RunContext::restore(invalid.serialize(),restored));
        invalid=r;invalid.paelsToothCards[0].uid=r.deck[0].uid;check("Reject duplicate PaelTooth/deck UID",!RunContext::restore(invalid.serialize(),restored));
        r.nextUid=r.paelsToothCards[0].uid;check("UID allocator reserves stored cards",r.allocate_card_uid()!=r.paelsToothCards[0].uid);
        check("PaelTooth selection uses no RNG",r.runRng[RNG_NICHE].counter==0&&r.playerRng[PRNG_REWARDS].counter==0);
        r.add_relic(RelicId::LUCKY_FYSH);r.add_relic(RelicId::BOOK_OF_FIVE_RINGS);r.cardsAdded=4;
        CardId returned[]={CardId::ANGER,CardId::IRON_WAVE,CardId::STRIKE_IRONCLAD,CardId::POMMEL_STRIKE,CardId::BASH};
        for(int i=0;i<5;++i){
            relics_combat_end(r,true,false);
            check("PaelTooth returns one upgraded card",r.paelsToothCount==4-i&&r.deckCount==2+i&&r.deck[r.deckCount-1].upgraded);
            check("PaelTooth uses reward RNG only",r.playerRng[PRNG_REWARDS].counter==i+1&&r.runRng[RNG_NICHE].counter==0);
            check("PaelTooth exact native return identity",r.deck[r.deckCount-1].id==returned[i]);
            check("PaelTooth returns a newly reconstructed entity",storedUids.count(r.deck[r.deckCount-1].uid)==0);
        }
        check("PaelTooth return runs add hooks",r.gold==99+5*15&&r.hp==50&&r.cardsAdded==9);
        relics_combat_end(r,true,false);check("PaelTooth empty queue consumes no RNG",r.playerRng[PRNG_REWARDS].counter==5&&r.deckCount==6);
    }
    {
        auto r=base();card_apply_upgrade(r.deck[1]);
        r.deck[0]=r.make_run_card(CardId::FOLLY,false);
        check("PaelTooth auto-removes only eligible cards",r.add_relic(RelicId::PAELS_TOOTH)&&!r.cardGrid.kind&&r.paelsToothCount==4&&r.deckCount==2);
        r.hp=0;relics_combat_end(r,true,false);check("PaelTooth does not return to dead owner",r.paelsToothCount==4&&r.deckCount==2&&r.playerRng[PRNG_REWARDS].counter==0);
    }
    {
        auto r=base();check("First queued selection opens",r.add_relic(RelicId::POMANDER));
        check("Subsequent obtains suspend without ownership",r.add_relic(RelicId::YUMMY_COOKIE)&&r.add_relic(RelicId::PRECISE_SCISSORS)&&r.pendingRelicObtainCount==2&&!run_has_relic(r,RelicId::YUMMY_COOKIE));
        check("Duplicate queued relic rejected",!r.add_relic(RelicId::YUMMY_COOKIE));
        RunContext saved;check("Pending obtains snapshot",RunContext::restore(r.serialize(),saved)&&saved.pendingRelicObtainCount==2);
        auto corrupt=r;corrupt.pendingRelicObtains[1]=corrupt.pendingRelicObtains[0];check("Duplicate pending snapshot rejected",!RunContext::restore(corrupt.serialize(),saved));
        check("Finish first resumes second selector",choose(r,{2})&&r.cardGrid.kind==9&&r.cardGrid.maxSelect==4&&r.pendingRelicObtainCount==1);
        check("Finish second resumes third selector",choose(r,{0,1,3,4})&&r.cardGrid.kind==6&&r.pendingRelicObtainCount==0);
        check("Finish third completes acquisition sequence",choose(r,{2})&&!r.cardGrid.kind&&r.deckCount==5&&upgrades(r)==4);
    }
    for(bool hooks:{false,true}){
        auto r=base();r.deckCount=0;
        for(int i=0;i<5;++i)r.deck[r.deckCount++]=r.make_run_card(CardId::STRIKE_IRONCLAD,false);
        for(int i=0;i<4;++i)r.deck[r.deckCount++]=r.make_run_card(CardId::DEFEND_IRONCLAD,false);
        r.deck[r.deckCount++]=r.make_run_card(CardId::BASH,false);const auto bashUid=r.deck[9].uid;
        if(hooks){r.add_relic(RelicId::LUCKY_FYSH);r.add_relic(RelicId::BOOK_OF_FIVE_RINGS);r.add_relic(RelicId::MOLTEN_EGG);r.add_relic(RelicId::BING_BONG);r.cardsAdded=4;}
        check("Pandora obtains",r.add_relic(RelicId::PANDORAS_BOX));
        check("Pandora retains Bash entity",r.deck[0].id==CardId::BASH&&r.deck[0].uid==bashUid);
        check("Pandora transforms nine basic Strike/Defend only",r.deckCount==(hooks?19:10)&&r.runRng[RNG_NICHE].counter==9);
        CardId replacement[]={CardId::BLOOD_WALL,CardId::FIGHT_ME,CardId::PRIMAL_FORCE,CardId::TRUE_GRIT,CardId::WHIRLWIND,
            CardId::SHRUG_IT_OFF,CardId::RAMPAGE,CardId::TAUNT,CardId::SETUP_STRIKE_CARD};
        bool exact=true;for(int i=1;i<r.deckCount;++i)exact&=r.deck[i].id==replacement[(i-1)/(hooks?2:1)];
        check("Pandora exact native card sequence",exact);
        std::set<int> uids;for(int i=0;i<r.deckCount;++i)uids.insert(r.deck[i].uid);
        check("Pandora replacement UIDs unique",static_cast<int>(uids.size())==r.deckCount);
        if(hooks){
            bool eggs=true;for(int i=1;i<r.deckCount;++i)if(card_def(r.deck[i].id).type==CardType::ATTACK)eggs&=r.deck[i].upgraded;
            check("Pandora applies Egg/BingBong/Fysh/Book hooks",eggs&&r.gold==369&&r.hp==80&&r.cardsAdded==22);
        }
    }
    for(std::uint64_t seed:{0,42}){
        auto r=base(seed);r.add_relic(RelicId::WHETSTONE);
        check("Whetstone exact native identities",seed==0?upgraded_indices(r,{0,2}):upgraded_indices(r,{0,4}));
        auto duplicates=base(seed);duplicates.deckCount=0;
        for(int i=0;i<10;++i)duplicates.deck[duplicates.deckCount++]=duplicates.make_run_card(CardId::STRIKE_IRONCLAD,false);
        for(int i=0;i<8;++i)duplicates.deck[duplicates.deckCount++]=duplicates.make_run_card(CardId::DEFEND_IRONCLAD,false);
        duplicates.deck[duplicates.deckCount++]=duplicates.make_run_card(CardId::BASH,false);
        duplicates.deck[duplicates.deckCount++]=duplicates.make_run_card(CardId::ANGER,false);
        duplicates.add_relic(RelicId::SAND_CASTLE);
        check("SandCastle duplicate identity matches native List.Sort",seed==0?upgraded_indices(duplicates,{0,2,5,10,16,17}):upgraded_indices(duplicates,{0,8,14,15,16,19}));
        check("SandCastle duplicate RNG counter",duplicates.runRng[RNG_NICHE].counter==19);
    }
    for(RelicId id:{RelicId::WAR_PAINT,RelicId::WHETSTONE,RelicId::SAND_CASTLE}){
        auto r=base();check("Random upgrade relic obtains",r.add_relic(id));
        check("Random upgrade RNG consumes filtered-count minus one",r.runRng[RNG_NICHE].counter==(id==RelicId::WAR_PAINT?0:id==RelicId::WHETSTONE?4:5));
        check("Random upgrade selected count",upgrades(r)==(id==RelicId::WAR_PAINT?1:id==RelicId::WHETSTONE?2:6));
        auto empty=base();for(int i=0;i<6;++i)card_apply_upgrade(empty.deck[i]);
        check("Empty random upgrade filter consumes zero RNG",empty.add_relic(id)&&empty.runRng[RNG_NICHE].counter==0);
    }
    std::cout<<"native relic round2: "<<checks<<" checks, "<<failures<<" failures\n";return failures?1:0;
}
