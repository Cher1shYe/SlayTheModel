// Actual v0.111.0 DLL fixture outcomes; see native-round4-step1-card-fixtures.
// Covers the two powers and their relative order, not general hook ordering.
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <nlohmann/json.hpp>
#include "sts2/battle.h"
#include "sts2/relics.h"
using namespace sts2;
using json = nlohmann::json;
namespace {
int checks=0, failures=0;
void check(const std::string &label, double got, double want) {
    ++checks;
    if (std::abs(got-want)>1e-10) { ++failures;std::cout<<label<<": got="<<got<<" native="<<want<<" FAIL\n"; }
}
BattleContext base(int enemies) {
    BattleContext b;
    Card deck[1]={make_card(CardId::DEFEND_IRONCLAD,false,1)};
    b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS,1234,deck,1,0,80,80);
    b.handCount=b.drawCount=b.discardCount=b.exhaustCount=b.knownTopCount=0;
    b.relicCount=0;b.player.energy=10;
    b.monsterCount=enemies;
    for(int i=0;i<enemies;++i) {
        b.monsters[i]=Monster{};
        b.monsters[i].id=MonsterId::CALCIFIED_CULTIST;
        b.monsters[i].slot=i;
        b.monsters[i].hp=b.monsters[i].maxHp=10000;
    }
    return b;
}
CardId cardId(const std::string &id) {return id=="INFERNO"?CardId::INFERNO_CARD:CardId::CRIMSON_MANTLE;}
PowerId powerId(const std::string &id) {return id=="INFERNO"?PowerId::INFERNO:PowerId::CRIMSON_MANTLE;}
void play(BattleContext &b,const std::string &id,int count,bool upgraded=false) {
    b.hand[b.handCount]=make_card(cardId(id),upgraded,b.require_card_uid());
    b.hand[b.handCount].replay=count-1;
    Action a;a.type=ActionType::PLAY_CARD;a.hand=b.handCount++;a.target=0;
    check(id+" replay card accepted",b.step(a),true);
}
void modifier(BattleContext &b,const std::string &m) {
    b.add_player_power(PowerId::RUPTURE,2);
    if(m.find("tungsten")!=std::string::npos)b.relics[b.relicCount++]=int(RelicId::TUNGSTEN_ROD);
    if(m.find("buffer")!=std::string::npos)b.add_player_power(PowerId::BUFFER,1);
    if(m=="intangible")b.add_player_power(PowerId::INTANGIBLE,1);
    if(m=="revive") {b.relics[b.relicCount++]=int(RelicId::LIZARD_TAIL);b.player.hp=1;}
    if(m=="lethal")b.player.hp=1;
}
void state(const std::string &label,const BattleContext &b,const json &s) {
    check(label+" hp",b.player.hp,s["hp"]);
    check(label+" block",b.player.block,s["block"]);
    check(label+" lizard spent",relic_aux(b,RelicId::LIZARD_TAIL)>0,s["lizardUsed"].get<bool>());
    for(int i=0;i<b.monsterCount;++i)check(label+" enemy "+std::to_string(i),10000-b.monsters[i].hp,s["damage"][i]);
    // Native death tears down every power; the existing simulator retains its
    // final combat values. Compare lethal effects and outcome, not that global
    // teardown representation (outside this two-power state change).
    if(s["hp"]==0) {check(label+" terminal loss",b.outcome==Outcome::PLAYER_LOSS,true);return;}
    check(label+" strength",b.player.strength,s["strength"]);
    check(label+" buffer",b.player_power(PowerId::BUFFER),s["buffer"]);
    check(label+" crimson amount",b.player_power(PowerId::CRIMSON_MANTLE),s["crimsonAmount"]);
    check(label+" inferno amount",b.player_power(PowerId::INFERNO),s["infernoAmount"]);
    check(label+" crimson self",b.player.crimsonMantleSelfDamage,s["crimsonSelf"]);
    check(label+" inferno self",b.player.infernoSelfDamage,s["infernoSelf"]);
    if(b.player_power(PowerId::CRIMSON_MANTLE)>0&&b.player_power(PowerId::INFERNO)>0) {
        const auto &powers=s["powers"];
        auto c=std::find(powers.begin(),powers.end(),"CRIMSON_MANTLE_POWER");
        auto in=std::find(powers.begin(),powers.end(),"INFERNO_POWER");
        check(label+" power order",b.player.infernoBeforeCrimsonMantle,in<c);
    }
}
}
int main() {
    const auto root=std::filesystem::path(__FILE__).parent_path().parent_path().parent_path();
    json fixtures;std::ifstream(root/"native-round4-step1-card-fixtures/results.json")>>fixtures;
    check("native fixture completed",fixtures["status"]=="completed",true);
    check("target DLL hash",fixtures["gameAssemblySha256"]=="9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4",true);
    for(const auto &f:fixtures["results"]) {
        const std::string t=f["test"];
        const auto &initial=f.contains("before")?f["before"]:f["after"];
        auto b=base(initial["damage"].size());
        if(t=="stack") {
            const std::string id=f["id"];const int n=f["count"];const bool up=f["upgraded"];
            const std::string label=id+(up?"+":"")+" x"+std::to_string(n);
            play(b,id,n,up);modifier(b,"none");state(label+" applied",b,f["before"]);
            b.start_player_turn();state(label+" first",b,f["first"]);
            b.start_player_turn();state(label+" second",b,f["second"]);
        } else if(t=="modifier") {
            const std::string id=f["id"],m=f["modifier"];
            play(b,id,f["count"]);modifier(b,m);state(id+" "+m+" before",b,f["before"]);
            b.start_player_turn();state(id+" "+m+" after",b,f["after"]);
        } else if(t=="order") {
            const bool inFirst=f["infernoFirst"];const std::string m=f["modifier"];
            play(b,inFirst?"INFERNO":"CRIMSON_MANTLE",inFirst?3:1);
            play(b,inFirst?"CRIMSON_MANTLE":"INFERNO",inFirst?1:3);
            modifier(b,m);const std::string label=(inFirst?"Inferno first ":"Crimson first ")+m;
            state(label+" before",b,f["before"]);
            b.start_player_turn();state(label+" after",b,f["after"]);
        } else if(t=="damage_trigger") {
            const std::string mode=f["mode"];play(b,"INFERNO",2);modifier(b,"none");
            if(mode=="enemy_damage")b.inMonsterTurn=true;
            if(mode=="direct_hp")b.lose_hp(3);
            else {if(mode=="blocked")b.player.block=10;b.damage_player(3,mode!="blocked");}
            state(mode,b,f["after"]);
        } else if(t=="direct_apply"||t=="remove_reapply") {
            const std::string id=f["id"];const auto power=powerId(id);
            b.add_player_power(power,13);b.start_player_turn();
            if(t=="remove_reapply") {
                play(b,id,2);state(id+" before removal",b,f["before"]);
                b.add_player_power(power,-b.player_power(power));
                b.add_player_power(power,13);
            }
            state(t+" "+id,b,f["after"]);
        } else {check("known native fixture",false,true);}
    }
    // Amount changes from other effects neither increment nor reset SelfDamage.
    auto b=base(1);play(b,"INFERNO",3);play(b,"CRIMSON_MANTLE",2);
    b.add_player_power(PowerId::INFERNO,5);b.add_player_power(PowerId::CRIMSON_MANTLE,-1);
    check("raw amount increase preserves counter",b.player.infernoSelfDamage,3);
    check("partial decrement preserves counter",b.player.crimsonMantleSelfDamage,2);
    check("raw amount update preserves order",b.player.infernoBeforeCrimsonMantle,true);
    b.add_player_power(PowerId::INFERNO,-b.player_power(PowerId::INFERNO));
    check("removal clears inferno counter",b.player.infernoSelfDamage,0);
    play(b,"INFERNO",1);
    check("recreated inferno now second",b.player.infernoBeforeCrimsonMantle,false);
    check("recreated inferno starts at one",b.player.infernoSelfDamage,1);
    std::cout<<"Native step1 self damage: "<<fixtures["results"].size()<<" fixtures, "<<checks<<" checks, "<<failures<<" failures\n";
    return failures?1:0;
}
