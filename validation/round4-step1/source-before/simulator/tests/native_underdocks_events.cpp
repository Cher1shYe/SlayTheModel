#include <cassert>
#include <cstring>
#include <iostream>
#include "sts2/run.h"
#include "sts2/relics.h"
#include "sts2/card_candidates.h"
using namespace sts2;
int event(const char *name) {
    for(int i=0;i<event_count();++i)if(!std::strcmp(event_info(i)->name,name))return i;
    assert(false);return -1;
}
RunContext start(const char *name) {
    RunContext r;r.init(42,0);r.hp=40;event_begin(r,event(name),false);return r;
}
void select(RunContext &r,std::initializer_list<int> cards) {
    for(int i:cards)assert(r.step({RunActionType::SELECT_GRID_CARD,i}));
    assert(r.step({RunActionType::CONFIRM_GRID_CARDS,0}));
}
BattleContext battle(Card c) {
    BattleContext b;b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS,42,&c,1,0,80,80);
    b.player.energy=50;b.player.strength=0;b.player.block=0;
    b.monsters[0].hp=b.monsters[0].maxHp=10000;b.monsters[0].block=0;
    b.monsters[0].vulnerable=0;return b;
}
int main() {
    {
        auto r=start("ABYSSAL_BATHS");assert(r.step({RunActionType::EVENT_CHOICE,0}));
        assert(r.maxHp==82&&r.hp==39&&r.eventData[0]==4&&r.eventPage==1);
        assert(r.step({RunActionType::EVENT_CHOICE,0}));assert(r.maxHp==84&&r.hp==37&&r.eventData[0]==5);
        RunContext copy;assert(RunContext::restore(r.serialize(),copy));
        assert(r.step({RunActionType::EVENT_CHOICE,1}));assert(r.hp==37&&r.screen==RunScreen::MAP);
        r=start("ABYSSAL_BATHS");assert(r.step({RunActionType::EVENT_CHOICE,1}));assert(r.hp==50);
        r=start("ABYSSAL_BATHS");r.add_relic(RelicId::TUNGSTEN_ROD);
        assert(r.step({RunActionType::EVENT_CHOICE,0}));assert(r.hp==40);
        r=start("ABYSSAL_BATHS");r.hp=1;assert(r.step({RunActionType::EVENT_CHOICE,0}));
        assert(r.hp==0&&r.screen==RunScreen::RUN_OVER);
    }
    {
        auto r=start("SUNKEN_TREASURY");const int small=r.eventData[0],big=r.eventData[1];
        assert(small>=52&&small<=67&&big>=303&&big<=363&&r.eventRng.counter==2);
        auto copy=r;assert(r.step({RunActionType::EVENT_CHOICE,0}));assert(r.gold==99+small);
        assert(copy.step({RunActionType::EVENT_CHOICE,1}));assert(copy.gold==99+big);
        assert(copy.deck[copy.deckCount-1].id==CardId::GREED);
    }
    {
        auto r=start("DOORS_OF_LIGHT_AND_DARK");const int count=r.deckCount;
        assert(r.step({RunActionType::EVENT_CHOICE,1})&&r.cardGrid.kind==6);
        select(r,{9});assert(r.deckCount==count-1);
        for(int i=0;i<r.deckCount;++i)assert(r.deck[i].id!=CardId::BASH);
        r=start("DOORS_OF_LIGHT_AND_DARK");assert(r.step({RunActionType::EVENT_CHOICE,0}));
        int up=0;for(int i=0;i<r.deckCount;++i)up+=r.deck[i].upgraded;assert(up==2&&r.eventRng.counter==9);
    }
    {
        auto r=start("SPIRALING_WHIRLPOOL");assert(r.step({RunActionType::EVENT_CHOICE,0}));
        assert(r.cardGrid.kind==11&&!card_grid_can_select(r,9));
        select(r,{0});assert(r.deck[0].enchantment==EnchantmentId::SPIRAL);
        RunContext restored;assert(RunContext::restore(r.serialize(),restored));
        auto b=battle(r.deck[0]);int hp=b.monsters[0].hp;assert(b.play_card(0,0));
        assert(hp-b.monsters[0].hp==12&&!b.discard[0].enchantmentDisabled);
        b.hand[b.handCount++]=b.discard[0];b.discardCount=0;
        hp=b.monsters[0].hp;assert(b.play_card(0,0));assert(hp-b.monsters[0].hp==12);
        r=start("SPIRALING_WHIRLPOOL");assert(r.step({RunActionType::EVENT_CHOICE,1}));assert(r.hp==66);
    }
    {
        auto r=start("WATERLOGGED_SCRIPTORIUM");r.gold=98;
        assert(!r.step({RunActionType::EVENT_CHOICE,2}));r.gold=99;
        assert(r.step({RunActionType::EVENT_CHOICE,2})&&r.gold==0&&r.cardGrid.kind==12);
        assert(r.step({RunActionType::SELECT_GRID_CARD,0}));
        assert(!r.step({RunActionType::CONFIRM_GRID_CARDS,0}));
        RunContext saved;assert(RunContext::restore(r.serialize(),saved));
        select(r,{5});assert(card_has(r.deck[0],CF_RETAIN)&&card_has(r.deck[5],CF_RETAIN));
        auto b=battle(r.deck[0]);b.step({ActionType::END_TURN});
        bool retained=false;for(int i=0;i<b.handCount;++i)retained|=b.hand[i].uid==r.deck[0].uid;assert(retained);
    }
    {
        auto r=start("DROWNING_BEACON");r.potionCount=r.potionSlots;
        for(int i=0;i<r.potionCount;++i)r.potions[i]=static_cast<int>(PotionId::FIRE_POTION);
        assert(r.step({RunActionType::EVENT_CHOICE,0}));assert(r.screen==RunScreen::REWARDS);
        assert(r.pendingPotions[0]==static_cast<int>(PotionId::GLOWWATER_POTION)&&r.potionCount==r.potionSlots);
        r=start("DROWNING_BEACON");assert(r.step({RunActionType::EVENT_CHOICE,1}));
        assert(r.maxHp==67&&r.hp==40&&run_has_relic(r,RelicId::FRESNEL_LENS));
        Card defend=r.make_run_card(CardId::DEFEND_IRONCLAD,false);
        assert(r.add_card_to_deck(defend));defend=r.deck[r.deckCount-1];
        assert(defend.enchantment==EnchantmentId::NIMBLE&&defend.enchantmentAmount==2);
        auto b=battle(defend);b.player.dexterity=1;b.player.frail=1;assert(b.play_card(0,0));
        assert(b.player.block==6); // floor((5+2+1)*.75)
        b=battle(defend);b.player.power[static_cast<int>(PowerId::NO_BLOCK)]=1;
        assert(b.play_card(0,0)&&b.player.block==0);
        auto fatal=start("DROWNING_BEACON");fatal.hp=fatal.maxHp=10;
        assert(fatal.step({RunActionType::EVENT_CHOICE,1}));
        assert(fatal.hp==0&&fatal.maxHp==1&&fatal.screen==RunScreen::RUN_OVER);
        auto fairy=start("DROWNING_BEACON");fairy.hp=fairy.maxHp=10;fairy.add_potion(PotionId::FAIRY_IN_ABOTTLE);
        assert(fairy.step({RunActionType::EVENT_CHOICE,1}));
        assert(fairy.hp==1&&fairy.maxHp==1&&fairy.potionCount==0);
        r.roll_shop();for(int i=0;i<r.shopCount;++i){
            Card c=r.shopCards[i];Card un=c;un.enchantment=EnchantmentId::NONE;
            if(card_can_enchant(un,EnchantmentId::NIMBLE))assert(c.enchantment==EnchantmentId::NIMBLE);
        }
    }
    {
        Card entrench=make_card(CardId::ENTRENCH,false,1);
        assert(card_apply_enchantment(entrench,EnchantmentId::NIMBLE,2));
        auto b=battle(entrench);b.player.block=7;b.player.dexterity=9;b.player.frail=1;
        b.player.power[static_cast<int>(PowerId::NO_BLOCK)]=1;
        assert(b.play_card(0,0));assert(b.player.block==16); // Unpowered still has a card source.
        b=battle(entrench);b.player.block=7;b.player.power[static_cast<int>(PowerId::UNMOVABLE)]=1;
        assert(b.play_card(0,0));assert(b.player.block==25); // 7 + (7+2)*2
        for(bool upgraded:{false,true})for(int strength:{-2,0,3}) {
            Card c=make_card(CardId::EXPECT_A_FIGHT,upgraded,1);
            assert(card_cost(c)==3);b=battle(c);b.player.strength=strength;
            assert(b.play_card(0,0));
            assert(b.player.block==(upgraded?16:15)+(upgraded?8:5)*std::max(0,strength));
            assert(b.player.energy==47);
        }
        Card c=make_card(CardId::DEFEND_IRONCLAD,true,1);
        card_apply_enchantment(c,EnchantmentId::NIMBLE,2);b=battle(c);b.player.frail=1;
        assert(b.play_card(0,0)&&b.player.block==7); // actual native fixture, (8+2)*.75
    }
    std::cout<<"Underdocks events, choices, rewards, persistent enchantments passed\n";
}
