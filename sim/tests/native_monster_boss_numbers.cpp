// All 75 active moves of 15 boss/companion models, A0 through A10.
// Expectations are transcribed from pinned native source, not simulator tables;
// this executes C++ effects and is NOT a native-DLL execution replay.
#include "sts2/battle.h"
#include "sts2/monsters.h"
#include "port_root.h"
#include <nlohmann/json.hpp>
#include <cstdio>
#include <fstream>
#include <map>
#include <memory>
#include <string>
using namespace sts2;
using json=nlohmann::json;
static int failures=0;
static void check(bool value,const std::string &label) {
    if(!value){++failures;std::printf("FAIL %s\n",label.c_str());}
}
static MonsterId monster(const std::string &name) {
    for(int i=1;i<static_cast<int>(MonsterId::COUNT);++i)
        if(name==monster_def(static_cast<MonsterId>(i)).key)return static_cast<MonsterId>(i);
    throw std::runtime_error("unknown monster "+name);
}
static CardId card(const std::string &name) {
    for(int i=1;i<static_cast<int>(CardId::COUNT);++i)
        if(name==card_def(static_cast<CardId>(i)).key)return static_cast<CardId>(i);
    throw std::runtime_error("unknown card "+name);
}
static PowerId power(const std::string &name) {
    static const std::map<std::string,PowerId> names={
        {"CHAINS_OF_BINDING",PowerId::CHAINS_OF_BINDING},{"DEXTERITY",PowerId::DEXTERITY},
        {"FRAIL",PowerId::FRAIL},{"INTANGIBLE",PowerId::INTANGIBLE},
        {"PAINFUL_STABS",PowerId::PAINFUL_STABS},{"PLOW",PowerId::PLOW},
        {"RINGING",PowerId::RINGING},{"SANDPIT",PowerId::SANDPIT},
        {"STEAM_ERUPTION",PowerId::STEAM_ERUPTION},{"STRENGTH",PowerId::STRENGTH},
        {"VULNERABLE",PowerId::VULNERABLE},{"WEAK",PowerId::WEAK}};
    return names.at(name);
}
static int count(const Card *pile,int n,CardId id) {
    int result=0;for(int i=0;i<n;++i)result+=pile[i].id==id;return result;
}
static std::unique_ptr<BattleContext> start(MonsterId id,int asc,int state=0) {
    auto b=std::make_unique<BattleContext>();
    Card deck[10];for(int i=0;i<10;++i)deck[i]=make_card(CardId::DEFEND_IRONCLAD,false,i+1);
    b->init(Encounter::SETUP_TOADPOLES_WEAK,4242,deck,10,asc,10000,10000,nullptr,0,nullptr,0,
            BASE_POTION_SLOTS,0,3,0,0,nullptr,nullptr,nullptr,nullptr,11);
    for(auto &m:b->monsters){m=Monster();m.alive=false;}
    b->monsterCount=0;
    spawn_monster_with(*b,id,0,state,0);
    // Keep a non-minion target alive so isolated Minion/DeathBlow moves do not
    // finish the encounter before their own effects can be inspected.
    spawn_monster_with(*b,MonsterId::TOADPOLE,1,0,0);
    b->monsters[1].hp=b->monsters[1].maxHp=9999;
    // Test base attacks without the independent Surrounded damage multiplier.
    b->player.power[static_cast<int>(PowerId::SURROUNDED)]=0;
    return b;
}
int main() {
    std::ifstream input(port_root()/"tests/fixtures/monster_boss_numbers_41cef1ea.json");
    json cases;input>>cases;
    int moves=0,executions=0;
    for(const auto &model:cases.at("monsters")) {
        const auto name=model.at("id").get<std::string>();
        const auto id=monster(name);
        for(int asc=0;asc<=10;++asc) {
            auto initial=start(id,asc);
            const auto hp=model.at("hp").at(asc>=8?"A8":"A0");
            check(initial->monsters[0].maxHp>=hp[0].get<int>()&&initial->monsters[0].maxHp<=hp[1].get<int>(),name+" HP A"+std::to_string(asc));
            for(const auto &move:model.at("moves")) {
                if(asc==0)++moves;
                ++executions;
                const int state=move.at("local_state");
                const std::string label=name+"."+move.at("state").get<std::string>()+" A"+std::to_string(asc);
                const auto &expected=move.at("levels").at(asc>=9?"9":asc>=8?"8":"0");
                auto b=start(id,asc,state);auto &m=b->monsters[0];
                // Independently test action block, apart from Plating's turn-end tick.
                m.power[static_cast<int>(PowerId::PLATING)]=0;
                m.power[static_cast<int>(PowerId::ASLEEP)]=0;
                m.steamEruptionDamage=37;
                int heal=0,block=0;
                for(const auto &op:expected.at("ops")) {
                    if(op[0]=="heal")heal+=op[1].get<int>();
                    if(op[0]=="block")block+=op[1].get<int>();
                }
                if(heal){m.maxHp=2000;m.hp=1000;}
                const int hpBefore=m.hp;
                const int damage=expected.at("damage_per_hit"),hits=expected.at("hits");
                roll_intent(*b,m);
                if(hits)check(m.intentDamage==damage&&m.intentHits==hits,label+" displayed base attack");
                monster_act(*b,m);
                check(10000-b->player.hp==damage*hits,label+" actual damage");
                check(b->unblockedHitsThisCombat==hits,label+" actual hit count");
                check(m.block==block,label+" actual block");
                if(heal)check(m.hp-hpBefore==heal,label+" actual heal");
                for(const auto &op:expected.at("ops")) {
                    if(op[0]=="power") {
                        const std::string role=op[1],key=op[2];
                        int amount=op[3];
                        // Intangible 2 is applied during Fade, then loses one at
                        // the end of its owner's turn (the same native timing).
                        if(role=="S"&&key=="INTANGIBLE")--amount;
                        const int actual=role=="P"?power_ref(b->player,power(key)):
                            power_ref(b->monsters[role=="O"?1:0],power(key));
                        check(actual==amount,label+" "+role+" "+key);
                    } else if(op[0]=="card") {
                        const std::string pile=op[1];const auto cid=card(op[2]);
                        const int actual=pile=="draw"?count(b->draw,b->drawCount,cid):
                            pile=="discard"?count(b->discard,b->discardCount,cid):count(b->hand,b->handCount,cid);
                        check(actual==op[3].get<int>(),label+" generated "+op[2].get<std::string>()+" in "+pile);
                    }
                }
            }
            // Further dynamic values: second/third form HP and growing attack
            // counts must follow state changes, not just the initial intent.
            if(id==MonsterId::TEST_SUBJECT) {
                auto b=start(id,asc);auto &m=b->monsters[0];
                for(int phase=1;phase<=2;++phase) {
                    b->kill_monster(0);check(m.reviving,name+" knocked out");
                    monster_act(*b,m);
                    const int hpExpected=phase==1?(asc>=8?212:200):(asc>=8?313:300);
                    check(m.hp==hpExpected&&m.maxHp==hpExpected,name+" revival HP");
                }
                b=start(id,asc,5);auto &claw=b->monsters[0];
                for(int use=0;use<4;++use) {
                    claw.move=5;claw.pendingRoll=false;roll_intent(*b,claw);
                    const int before=b->player.hp;
                    monster_act(*b,claw);
                    check(before-b->player.hp==(asc>=9?11:10)*(3+use),name+" growing claws");
                }
            }
            if(id==MonsterId::WATERFALL_GIANT) {
                auto b=start(id,asc,4);auto &m=b->monsters[0];
                for(int use=0;use<4;++use) {
                    m.move=4;m.pendingRoll=false;roll_intent(*b,m);const int before=b->player.hp;
                    monster_act(*b,m);
                    check(before-b->player.hp==(asc>=9?23:20)+5*use,name+" pressure gun growth");
                    check(power_ref(m,PowerId::STEAM_ERUPTION)==3*(use+1),name+" steam growth");
                }
            }
            if(id==MonsterId::AEONGLASS) {
                auto b=start(id,asc,2);auto &m=b->monsters[0];
                for(int use=0;use<3;++use) {
                    const int strength=m.strength;m.move=2;m.pendingRoll=false;
                    monster_act(*b,m);
                    check(m.strength-strength==(asc>=9?4:3)+use,name+" increasing Strength");
                    check(count(b->discard,b->discardCount,CardId::WITHER)==(asc>=9?2:1)*(use+1),name+" Wither count");
                    for(int i=0;i<b->discardCount;++i)if(b->discard[i].id==CardId::WITHER)
                        check(b->discard[i].bonusDamage==3*(use+1),name+" Wither upgrade");
                }
            }
        }
    }
    // One defect affected both crab arms: native CrabRage is +6, not +5.
    for(int asc=0;asc<=10;++asc)for(auto survivor:{MonsterId::CRUSHER,MonsterId::ROCKET}) {
        auto b=start(survivor,asc);
        const auto victim=survivor==MonsterId::CRUSHER?MonsterId::ROCKET:MonsterId::CRUSHER;
        spawn_monster_with(*b,victim,1,0,0);
        b->kill_monster(1);
        check(b->monsters[0].strength==6&&b->monsters[0].block==99,"CrabRage native 6 Strength / 99 Block");
    }
    // WitheringPresence belongs to Aeonglass. Its Amount remains 6 while the
    // distinct CardsLeft display counts six actual card plays, then resets.
    for(int asc=0;asc<=10;++asc) {
        auto b=std::make_unique<BattleContext>();
        Card deck[10];for(int i=0;i<10;++i)deck[i]=make_card(CardId::DEFEND_IRONCLAD,false,i+1);
        b->init(Encounter::SETUP_AEONGLASS_BOSS,8181,deck,10,asc,10000,10000,nullptr,0,nullptr,0,
                BASE_POTION_SLOTS,0,3,0,0,nullptr,nullptr,nullptr,nullptr,11);
        check(b->monsters[0].id==MonsterId::AEONGLASS,"Aeonglass fixture identity");
        check(power_ref(b->monsters[0],PowerId::WITHERING_PRESENCE)==6,"WitheringPresence native owner and Amount");
        check(power_ref(b->player,PowerId::WITHERING_PRESENCE)==0,"WitheringPresence is absent from player");
        check(b->monsters[0].aux[2]==6,"WitheringPresence starts with CardsLeft 6");
        b->handCount=0;
        for(int played=1;played<=12;++played) {
            const int slot=b->handCount;
            b->add_card_to_hand(make_card(CardId::DEFEND_IRONCLAD,false,b->require_card_uid()));
            b->player.energy=99;
            check(b->play_card(slot,0),"play a real card for WitheringPresence");
            check(power_ref(b->monsters[0],PowerId::WITHERING_PRESENCE)==6,"WitheringPresence Amount stays 6");
            check(b->monsters[0].aux[2]==6-played%6,"WitheringPresence CardsLeft countdown/reset");
            check(count(b->hand,b->handCount,CardId::WITHER)==played/6,"exactly one Wither per six cards");
            if(played==4)b=std::make_unique<BattleContext>(*b); // cloning preserves the pending two-card countdown
        }
    }
    check(moves==75&&executions==825,"15 models / 75 moves / 11 ascensions covered");
    std::printf("Boss numbers: %d moves, %d executions, %d failures\n",moves,executions,failures);
    return failures?1:0;
}
