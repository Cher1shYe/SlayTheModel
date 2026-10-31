// Native oracle: ../../native-run-fixtures/results.json, DLL 9cb4f1ad...
// Fixtures use the same permanent deck order and reset only the Niche RNG.
#include "sts2/run.h"
#include "sts2/card_candidates.h"
#include "sts2/relics.h"
#include <cmath>
#include <iostream>
#include <set>
using namespace sts2;
namespace {
int checks=0, failures=0;
void check(const char *name, bool result) {
    ++checks; failures += !result;
    std::cout << name << (result?" PASS\n":" FAIL\n");
}
RunContext base(std::uint64_t seed=42) {
    RunContext r; r.init(147,0); r.screen=RunScreen::SHOP;
    r.deckCount=0; r.hp=50; r.maxHp=80;
    for (CardId id:{CardId::STRIKE_IRONCLAD,CardId::DEFEND_IRONCLAD,CardId::BASH,
                    CardId::ANGER,CardId::POMMEL_STRIKE,CardId::IRON_WAVE})
        r.deck[r.deckCount++]=r.make_run_card(id,false);
    r.runRng[RNG_NICHE]=Rng(seed);
    return r;
}
bool choose(RunContext &r,std::initializer_list<int> selected) {
    for (int i:selected) if(!r.step({RunActionType::SELECT_GRID_CARD,i})) return false;
    return r.step({RunActionType::CONFIRM_GRID_CARDS,0});
}
bool same_cards(const RunContext&r,std::initializer_list<CardId> ids) {
    if(r.deckCount!=static_cast<int>(ids.size())) return false;
    int i=0; for (CardId id:ids) if(r.deck[i++].id!=id) return false;
    return true;
}
}
int main() {
    const std::uint64_t seeds[]={0,42,987654321};
    const int upgrades[3][2]={{1,4},{0,4},{3,5}};
    const int swift[3][4]={{0,1,2,4},{2,3,4,5},{0,1,2,3}};
    for(int k=0;k<3;++k) {
        auto m=base(seeds[k]); check("Mushroom obtain",m.add_relic(RelicId::FRAGRANT_MUSHROOM));
        check("Mushroom damage15",m.hp==35);
        bool exact=true; for(int i=0;i<6;++i)
            exact &= m.deck[i].upgraded==(i==upgrades[k][0]||i==upgrades[k][1]);
        check("Mushroom native exact upgraded identities",exact);
        check("Mushroom native RNG counter",m.runRng[RNG_NICHE].counter==5);
        auto b=base(seeds[k]); check("Bracelet obtain",b.add_relic(RelicId::BEAUTIFUL_BRACELET));
        exact=true; for(int i=0;i<6;++i) {
            bool enchanted=false; for(int j:swift[k]) enchanted|=i==j;
            exact &= b.deck[i].enchantment==(enchanted?EnchantmentId::SWIFT:EnchantmentId::NONE);
            if(enchanted) exact &= b.deck[i].enchantmentAmount==2;
        }
        check("Bracelet native exact enchanted identities and amount",exact);
        check("Bracelet native RNG counter",b.runRng[RNG_NICHE].counter==5);
    }
    {
        auto r=base(); const auto uid=r.deck[2].uid;
        check("PreciseScissors obtains pending choice",r.add_relic(RelicId::PRECISE_SCISSORS)&&r.cardGrid.kind==6);
        check("Choice leaves deck untouched",r.deckCount==6&&r.deck[2].uid==uid);
        check("Premature confirm rejected",!r.step({RunActionType::CONFIRM_GRID_CARDS,0}));
        check("Selection preview",r.step({RunActionType::SELECT_GRID_CARD,2})&&r.cardGrid.preview&&r.deckCount==6);
        RunContext restored; check("Selection snapshot restore",RunContext::restore(r.serialize(),restored));
        check("Cancel leaves deck and resets selection",r.step({RunActionType::CANCEL_GRID_PREVIEW,0})&&r.deckCount==6&&!r.cardGrid.selectedCount);
        check("Scissors chosen deletion",choose(r,{2})&&same_cards(r,{CardId::STRIKE_IRONCLAD,CardId::DEFEND_IRONCLAD,
            CardId::ANGER,CardId::POMMEL_STRIKE,CardId::IRON_WAVE}));
        check("Scissors no randomness",r.runRng[RNG_NICHE].counter==0);
    }
    {
        auto r=base(); check("EmptyCage chosen reverse-index deletion",r.add_relic(RelicId::EMPTY_CAGE)&&choose(r,{4,0})&&
            same_cards(r,{CardId::DEFEND_IRONCLAD,CardId::BASH,CardId::ANGER,CardId::IRON_WAVE}));
    }
    {
        auto r=base(); check("PreservedFog selected deletion then curse",r.add_relic(RelicId::PRESERVED_FOG)&&choose(r,{4,0,2})&&
            same_cards(r,{CardId::DEFEND_IRONCLAD,CardId::ANGER,CardId::IRON_WAVE,CardId::FOLLY}));
        check("PreservedFog no randomness",r.runRng[RNG_NICHE].counter==0);
    }
    for(bool book:{false,true}) {
        auto r=base(); r.hp=30;
        if(book) {check("Book obtain",r.add_relic(RelicId::BOOK_OF_FIVE_RINGS));r.cardsAdded=4;}
        check("Astrolabe obtains pending choice",r.add_relic(RelicId::ASTROLABE)&&r.cardGrid.kind==8);
        check("Astrolabe chosen transform exact native order",choose(r,{4,0,2})&&same_cards(r,{CardId::DEFEND_IRONCLAD,
            CardId::ANGER,CardId::IRON_WAVE,CardId::BLOOD_WALL,CardId::FIGHT_ME,CardId::PRIMAL_FORCE}));
        bool upgraded=true; for(int i=0;i<6;++i) upgraded&=r.deck[i].upgraded==(i>=3);
        check("Astrolabe upgrades only replacements",upgraded);
        check("Astrolabe native RNG counter",r.runRng[RNG_NICHE].counter==3);
        if(book) check("Book native heal20 and per-card count",r.hp==50&&r.cardsAdded==7);
    }
    {
        auto r=base();r.hp=15;
        check("Lethal Mushroom obtains",r.add_relic(RelicId::FRAGRANT_MUSHROOM));
        check("Lethal Mushroom terminal",r.hp==0&&r.screen==RunScreen::RUN_OVER&&!r.won);
        bool plain=true;for(int i=0;i<6;++i)plain&=!r.deck[i].upgraded;
        check("Lethal Mushroom native suppresses upgrades",plain);
        check("Lethal Mushroom still consumes RNG",r.runRng[RNG_NICHE].counter==5);
        r.finish_room();check("finish_room cannot revive dead run",r.is_over());
    }
    {
        auto r=base();r.hp=16;
        check("Shears damage deferred until confirmation",r.add_relic(RelicId::PRECARIOUS_SHEARS)&&r.hp==16);
        check("Shears removes first then dies",choose(r,{4,0})&&r.deckCount==4&&r.hp==0&&r.is_over());
        r.finish_room();check("Shears death persists through room finish",r.is_over());
    }
    {
        auto r=base();r.hp=16;r.add_relic(RelicId::TUNGSTEN_ROD);
        check("Shears respects Tungsten",r.add_relic(RelicId::PRECARIOUS_SHEARS)&&choose(r,{4,0})&&r.hp==1&&!r.is_over());
    }
    {
        auto r=base();r.hp=16;r.add_relic(RelicId::LIZARD_TAIL);r.add_potion(PotionId::FAIRY_IN_ABOTTLE);
        check("Shears fairy revives first",r.add_relic(RelicId::PRECARIOUS_SHEARS)&&choose(r,{4,0})&&r.hp==24&&r.potionCount==0);
        bool unused=false;for(int i=0;i<r.relicCount;++i)if(r.relics[i]==static_cast<int>(RelicId::LIZARD_TAIL))unused=r.relicAux[i]==0;
        check("Fairy leaves LizardTail unused",unused);
        run_take_noncombat_damage(r,24);check("LizardTail revives next",r.hp==40&&run_has_relic(r,RelicId::LIZARD_TAIL));
        run_take_noncombat_damage(r,40);check("LizardTail cannot revive twice",r.hp==0&&r.is_over());
    }
    {
        auto r=base();r.deckCount=1;r.deck[0]=r.make_run_card(CardId::FOLLY,false);
        check("No eligible removal still applies Shears damage",r.add_relic(RelicId::PRECARIOUS_SHEARS)&&r.cardGrid.kind==0&&r.hp==34&&r.deckCount==1);
        check("No eligible transform skips grid",r.add_relic(RelicId::ASTROLABE)&&r.cardGrid.kind==0&&r.deckCount==1);
    }
    {
        auto r=base();r.add_relic(RelicId::BING_BONG);
        while(r.deckCount<MAX_DECK-2)r.deck[r.deckCount++]=r.make_run_card(CardId::STRIKE_IRONCLAD,false);
        check("Astrolabe capacity rejected before deadlocked grid",!r.add_relic(RelicId::ASTROLABE)&&!r.cardGrid.kind&&!run_has_relic(r,RelicId::ASTROLABE));
    }
    {
        auto r=base();r.deckCount=0;
        while(r.deckCount<MAX_DECK)r.deck[r.deckCount++]=r.make_run_card(CardId::FOLLY,false);
        check("PreservedFog capacity rejected before curse overflow",!r.add_relic(RelicId::PRESERVED_FOG)&&!r.cardGrid.kind&&!run_has_relic(r,RelicId::PRESERVED_FOG));
    }
    {
        auto r=base(); r.deckCount=2; r.add_relic(RelicId::ASTROLABE);
        r.cardGrid.minSelect=r.cardGrid.maxSelect=3;
        RunContext out;
        check("Impossible pending selection rejected on restore",!RunContext::restore(r.serialize(),out));
    }
    {
        auto r=base();
        while(r.deckCount<MAX_DECK-2)r.deck[r.deckCount++]=r.make_run_card(CardId::STRIKE_IRONCLAD,false);
        r.add_relic(RelicId::ASTROLABE);
        // The public obtain API now queues this hook until the current grid
        // finishes, so normal acquisition is safe and should restore.
        r.add_relic(RelicId::BING_BONG);
        RunContext out;
        check("Queued duplication waits for transform completion",RunContext::restore(r.serialize(),out));
        // A genuinely malformed snapshot can still insert an active hook.
        r.pendingRelicObtainCount=0;r.pendingRelicObtains[0]=0;
        r.relics[r.relicCount]=static_cast<int>(RelicId::BING_BONG);
        r.relicAux[r.relicCount++]=0;
        check("Pending transform capacity revalidated on restore",!RunContext::restore(r.serialize(),out));
    }
    std::cout<<"native run alignment: "<<checks<<" checks, "<<failures<<" failures\n";
    return failures?1:0;
}
