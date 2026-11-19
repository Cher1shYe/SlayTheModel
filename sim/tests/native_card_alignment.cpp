// Differential fixtures anchored to native DLL 9cb4f1ad... (v0.111.0/41cef1ea).
// Integer fixtures were executed against that DLL. Modifier/clone edge cases
// additionally lock the corresponding decompiled native call sequence.
#include <cmath>
#include <cstring>
#include <iostream>
#include "sts2/battle.h"
#include "sts2/monsters.h"
#include "sts2/relics.h"
using namespace sts2;
namespace {
int failures = 0, checks = 0;
void check(const char *name, double actual, double expected) {
    ++checks;
    const bool ok = std::abs(actual - expected) < 1e-10;
    failures += !ok;
    std::cout << name << " actual=" << actual << " expected=" << expected
              << (ok ? " PASS\n" : " FAIL\n");
}
BattleContext base() {
    BattleContext b;
    Card deck[20];
    for (int i=0; i<20; ++i) deck[i]=make_card(CardId::STRIKE_IRONCLAD,false,i+1);
    b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS,1234,deck,20,0,500,500);
    b.handCount=b.drawCount=b.discardCount=b.exhaustCount=0;
    b.knownTopCount=0; b.player.energy=50;
    b.monsters[0].hp=b.monsters[0].maxHp=10000; b.monsters[0].block=0;
    std::memset(b.monsters[0].power,0,sizeof(b.monsters[0].power));
    b.monsters[0].vulnerable=b.monsters[0].weak=b.monsters[0].strength=0;
    return b;
}
void hand(BattleContext &b, CardId id, bool up=false) {
    b.hand[b.handCount++]=make_card(id,up,b.require_card_uid());
}
void play(BattleContext &b) {
    Action a; a.type=ActionType::PLAY_CARD; a.hand=0; a.target=0; b.step(a);
}
Card &discarded(BattleContext &b, CardId id) {
    for(int i=0;i<b.discardCount;++i) if(b.discard[i].id==id) return b.discard[i];
    throw std::runtime_error("expected discarded card missing");
}
void relic(BattleContext &b, RelicId id, int counter) {
    b.relics[b.relicCount]=static_cast<int>(id); b.relicAux[b.relicCount++]=counter;
}
}
int main() {
    for (bool upgraded : {false,true}) {
        auto b=base(); hand(b,CardId::SETUP_STRIKE_CARD,upgraded); hand(b,CardId::STRIKE_IRONCLAD);
        play(b);
        check("Setup Strike native damage",10000-b.monsters[0].hp,upgraded?9:7);
        check("Setup Strike native temporary strength",b.player.strength,upgraded?4:3);
        const int hp=b.monsters[0].hp;play(b);
        check("Setup Strike strengthens following Strike",hp-b.monsters[0].hp,upgraded?10:9);
        Action end;end.type=ActionType::END_TURN;b.step(end);
        check("Setup Strike strength expires after turn",b.player.strength,0);
    }
    for (bool upgraded : {false,true}) {
        auto b=base(); hand(b,CardId::CINDER,upgraded); hand(b,CardId::DEFEND_IRONCLAD);
        b.draw[b.drawCount++]=make_card(CardId::STRIKE_IRONCLAD,false,b.require_card_uid());
        play(b);
        check(upgraded?"Cinder+ damage":"Cinder damage",10000-b.monsters[0].hp,upgraded?24:18);
        check("Cinder exhausts remaining hand",b.handCount,0);
        check("Cinder preserves draw",b.drawCount,1);
        check("Cinder exhausted Defend",static_cast<int>(b.exhaust[0].id),static_cast<int>(CardId::DEFEND_IRONCLAD));
    }
    {
        auto b=base(); hand(b,CardId::CINDER);
        b.discard[b.discardCount++]=make_card(CardId::DEFEND_IRONCLAD,false,b.require_card_uid());
        const auto counter=b.cardSelectionRng.counter; play(b);
        check("Cinder empty hand consumes no selection RNG",b.cardSelectionRng.counter,counter);
        check("Cinder empty hand does not shuffle",b.drawCount,0);
        check("Cinder empty hand exhausts nothing",b.exhaustCount,0);
    }
    {
        auto b=base(); hand(b,CardId::CINDER); hand(b,CardId::DEFEND_IRONCLAD);
        b.draw[b.drawCount++]=make_card(CardId::STRIKE_IRONCLAD,false,b.require_card_uid());
        b.add_player_power(PowerId::DARK_EMBRACE,1); play(b);
        check("Cinder exhaust hooks draw",b.handCount,1);
        check("Cinder hook-drawn card stays",static_cast<int>(b.hand[0].id),static_cast<int>(CardId::STRIKE_IRONCLAD));
    }
    {
        auto b=base(); hand(b,CardId::ANGER);
        auto &a=b.hand[0]; a.enchantment=EnchantmentId::SOWN; a.enchantmentAmount=8;
        a.bonusDamage=4.5; a.freeCombat=true; a.bonusReplay=0;
        a.costThisTurn=true; a.costForTurn=0; a.storedCost=2;
        a.retainThisCombat=true; const auto uid=a.uid; play(b);
        int originals=0, copies=0;
        for (int i=0;i<b.discardCount;++i) {
            const auto &c=b.discard[i];
            if(c.uid==uid) { ++originals; check("Anger original enchantment used",c.enchantmentDisabled,1); }
            else if(c.id==CardId::ANGER) {
                ++copies;
                check("Anger clone enchantment",static_cast<int>(c.enchantment),static_cast<int>(EnchantmentId::SOWN));
                check("Anger clone amount",c.enchantmentAmount,8);
                check("Anger clone has independent active enchantment",c.enchantmentDisabled,0);
                check("Anger clone fractional damage",c.bonusDamage,4.5);
                check("Anger clone combat cost",c.freeCombat,1);
                check("Anger clone temporary cost",c.costThisTurn,1);
                check("Anger clone stored cost",c.storedCost,2);
                check("Anger clone retain",c.retainThisCombat,1);
            }
        }
        check("Anger original count",originals,1); check("Anger unique clone",copies,1);
    }
    {
        auto b=base(); hand(b,CardId::THRASH); hand(b,CardId::STRIKE_IRONCLAD);
        b.player.strength=5; play(b);
        check("Thrash with Strength initial attack",10000-b.monsters[0].hp,18);
        check("Thrash with Strength growth",discarded(b,CardId::THRASH).bonusDamage,11);
    }
    {
        auto b=base(); hand(b,CardId::THRASH); hand(b,CardId::BODY_SLAM);
        b.player.block=10; play(b);
        check("Thrash Body Slam growth",discarded(b,CardId::THRASH).bonusDamage,10);
    }
    {
        auto b=base(); hand(b,CardId::THRASH); hand(b,CardId::STRIKE_IRONCLAD);
        b.player.weak=1; play(b);
        const Card first=discarded(b,CardId::THRASH);
        check("Thrash Weak fractional growth",first.bonusDamage,4.5);
        b.discardCount=0; b.hand[b.handCount++]=first; hand(b,CardId::STRIKE_IRONCLAD);
        const int hp=b.monsters[0].hp; play(b);
        check("Thrash fractional base used in next attack",hp-b.monsters[0].hp,12);
        check("Thrash fractional growth accumulates",discarded(b,CardId::THRASH).bonusDamage,9);
    }
    {
        auto b=base(); hand(b,CardId::THRASH); hand(b,CardId::STRIKE_IRONCLAD);
        b.monsters[0].vulnerable=3; b.monsters[0].power[static_cast<int>(PowerId::SLOW)]=1;
        b.monsters[0].slowCardsThisTurn=4; play(b);
        check("Thrash growth has no enemy modifiers",discarded(b,CardId::THRASH).bonusDamage,6);
    }
    {
        auto b=base(); hand(b,CardId::THRASH); hand(b,CardId::BULLY);
        b.monsters[0].vulnerable=5; play(b);
        check("Thrash Bully has null target",discarded(b,CardId::THRASH).bonusDamage,card_var(make_card(CardId::BULLY,false,1),VarId::CALC_BASE));
    }
    {
        auto b=base(); hand(b,CardId::THRASH); hand(b,CardId::ASHEN_STRIKE);
        b.exhaust[b.exhaustCount++]=make_card(CardId::DEFEND_IRONCLAD,false,b.require_card_uid());
        play(b); check("Thrash Ashen counts before exhaustion",discarded(b,CardId::THRASH).bonusDamage,9);
    }
    {
        auto b=base(); hand(b,CardId::THRASH); hand(b,CardId::PERFECTED_STRIKE);
        play(b); check("Thrash Perfected includes selected card",discarded(b,CardId::THRASH).bonusDamage,8);
    }
    {
        auto b=base(); hand(b,CardId::THRASH); hand(b,CardId::GOLD_AXE);
        b.cardsPlayedThisCombat=b.cardsFinishedThisCombat=3; play(b);
        check("Thrash Gold Axe counts completed plays",discarded(b,CardId::THRASH).bonusDamage,3);
        check("Thrash increments finished history afterwards",b.cardsFinishedThisCombat,4);
    }
    for(int counter : {8,9}) {
        auto b=base(); hand(b,CardId::THRASH); hand(b,CardId::STRIKE_IRONCLAD);
        relic(b,RelicId::PEN_NIB,counter); play(b);
        check(counter==8?"Thrash ninth attack hand-preview Pen Nib":"Thrash tenth attack does not double selected card",
              discarded(b,CardId::THRASH).bonusDamage,counter==8?12:6);
    }
    for(int stacks : {1,2}) {
        auto b=base(); hand(b,CardId::THRASH); hand(b,CardId::STRIKE_IRONCLAD);
        b.add_player_power(PowerId::GIGANTIFICATION,stacks); play(b);
        check("Thrash growth sees Gigantification after attack",discarded(b,CardId::THRASH).bonusDamage,stacks==1?6:18);
    }
    {
        auto b=base(); hand(b,CardId::THRASH); hand(b,CardId::DEFEND_IRONCLAD);
        const auto counter=b.cardSelectionRng.counter; play(b);
        check("Thrash no attacks consumes no RNG",b.cardSelectionRng.counter,counter);
        check("Thrash no attacks grows zero",discarded(b,CardId::THRASH).bonusDamage,0);
    }
    {
        auto b=base(); hand(b,CardId::THRASH); hand(b,CardId::STRIKE_IRONCLAD); hand(b,CardId::BASH);
        auto expected=b.cardSelectionRng;
        const int chosen=expected.next_int(0,1);
        play(b);
        check("Thrash consumes one native selection draw",b.cardSelectionRng.counter,expected.counter);
        check("Thrash picks randomized candidate",static_cast<int>(b.exhaust[0].id),
              static_cast<int>(chosen==0?CardId::STRIKE_IRONCLAD:CardId::BASH));
    }
    std::cout << checks << " checks, " << failures << " failures\n";
    return failures?1:0;
}
