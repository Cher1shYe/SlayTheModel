// Cross-effect boundaries for the round3 native rules audit.
#include "sts2/run.h"
#include "sts2/relics.h"
#include <nlohmann/json.hpp>
#include <cassert>
#include <filesystem>
#include <fstream>
#include <iostream>
using namespace sts2;
using nlohmann::json;

static BattleContext base() {
    BattleContext b;
    Card deck[]{make_card(CardId::STRIKE_IRONCLAD,false,1)};
    b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS,42,deck,1,0,80,80);
    b.handCount=b.drawCount=b.discardCount=b.exhaustCount=0;
    b.knownTopCount=0;b.player.energy=20;
    b.monsters[0].hp=b.monsters[0].maxHp=1000;
    b.monsters[0].block=0;
    return b;
}
static void relic(BattleContext &b,RelicId id) {
    b.relics[b.relicCount]=static_cast<int>(id);b.relicAux[b.relicCount++]=0;
}
int main() {
    auto path=std::filesystem::path(__FILE__).parent_path().parent_path().parent_path()
        / "native-round3-relic-fixtures/results.json";
    std::ifstream input(path);json fixtures;input>>fixtures;
    assert(fixtures["status"]=="completed" && fixtures["gameSceneLoaded"]==false);
    assert(fixtures["gameAssemblySha256"]=="9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4");
    int nativeCases=0;
    for(const auto &row:fixtures["results"]) {
        const auto test=row["test"].get<std::string>();
        if(test!="red_skull_heal_damage"&&test!="red_skull_damage")continue;
        auto b=base();relic(b,RelicId::RED_SKULL);b.player.hp=row["initial"];
        relics_current_hp_changed(b);
        assert(b.player.strength==row["initialStrength"]);
        if(test=="red_skull_heal_damage") {
            b.heal_hp(1);assert(b.player.strength==row["healedStrength"]);
            b.damage_player(2,true);
        } else b.damage_player(40,true);
        assert(b.player.hp==row["finalHp"]&&b.player.strength==row["finalStrength"]);
        ++nativeCases;
    }
    assert(nativeCases==2);
    // Blood Potion and regeneration must immediately withdraw Red Skull's
    // strength, without waiting for the following player's turn.
    {
        auto b=base();relic(b,RelicId::RED_SKULL);b.player.hp=40;
        relics_current_hp_changed(b);b.apply_potion(PotionId::BLOOD_POTION,0);
        assert(b.player.hp==56&&b.player.strength==0);
        b.lose_hp(20);assert(b.player.hp==36&&b.player.strength==3);
        b.heal_hp(5);assert(b.player.hp==41&&b.player.strength==0);
    }
    // Random multi-hit is ONE command: Vigor affects every hit, and Skittish
    // gains block only after the command finishes.
    {
        auto b=base();b.add_player_power(PowerId::VIGOR,5);
        b.monsters[0].power[static_cast<int>(PowerId::SKITTISH)]=9;
        Card c=make_card(CardId::RIP_AND_TEAR,false,b.require_card_uid());
        b.attack_random_from_card(c,7,2);
        assert(b.monsters[0].hp==976&&b.monsters[0].block==9);
        assert(b.player_power(PowerId::VIGOR)==0);
    }
    for (int mode=0;mode<3;++mode) {
        auto b=base();b.monsters[0].block=4;
        b.monsters[0].power[static_cast<int>(PowerId::SKITTISH)]=3;
        Card c=make_card(CardId::SWORD_BOOMERANG,false,b.require_card_uid());
        if(mode==0)b.attack_random_from_card(c,3,3);
        if(mode==1)b.attack_all_from_card(c,3,3);
        if(mode==2)b.attack_from_card(c,0,3,3);
        // SkittishPower.FirstOrDefault selects the fully blocked first hit.
        assert(b.monsters[0].hp==995&&b.monsters[0].block==0);
        assert(!b.monsters[0].skittishTriggeredThisTurn);
    }
    // Native lowering MaxHP uses damage before setting/clamping max HP.
    {
        auto b=base();b.player.hp=b.player.maxHp=1;relic(b,RelicId::LIZARD_TAIL);
        b.lose_max_hp(2,true);
        assert(b.player.maxHp==1&&b.player.hp==1&&b.outcome==Outcome::UNDECIDED);
        assert(relic_aux(b,RelicId::LIZARD_TAIL)==1);
    }
    {
        auto b=base();b.add_player_power(PowerId::RUPTURE,2);b.resolvingCard=true;
        b.lose_max_hp(2,true);
        assert(b.player.hp==78&&b.player.maxHp==78&&b.player.strength==2&&b.pendingRupture==0);
    }
    // Mandatory relic card additions are rejected before fixed-capacity loss.
    for(auto id:{RelicId::DISTINGUISHED_CAPE,RelicId::SERE_TALON,RelicId::NEOWS_TORMENT}) {
        RunContext r;r.init(42,0);r.relicCount=0;r.deckCount=MAX_DECK;
        for(int i=0;i<MAX_DECK;++i)r.deck[i]=make_card(CardId::STRIKE_IRONCLAD,false,i+1);
        assert(!r.add_relic(id)&&r.relicCount==0&&r.deckCount==MAX_DECK);
    }
    // Even with identical POD dimensions, pre-round3 snapshots describe old
    // rules and are rejected rather than silently relabelled.
    {
        RunContext r,out;r.init(42,0);auto blob=r.serialize();
        assert(RunContext::restore(blob,out));
        blob[4]=6;blob[5]=0;assert(!RunContext::restore(blob,out));
    }
    std::cout<<"round3 shared boundaries: 2 native RedSkull fixtures and integration cases passed\n";
}
