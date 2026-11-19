// All active native monsters against immutable real DLL fresh-model exports.
// These check compiled table numbers; dynamic move execution has separate tests.
#include "sts2/monsters.h"
#include "port_root.h"
#include <nlohmann/json.hpp>
#include <fstream>
#include <iostream>
#include <map>
#include <stdexcept>
#include <string>
#include <vector>

namespace audit_tables {
using namespace sts2;
#include "sts2/monsters_generated.inc"
}
using Json=nlohmann::ordered_json;
using namespace sts2;
static int failures=0, numericChecks=0, attackContexts=0, modelContexts=0, moveContexts=0, dynamicErrors=0;
static void check(bool ok,const std::string &label) {
    if(!ok){++failures;std::cerr<<"FAIL "<<label<<"\n";}
}
static Json read(const std::filesystem::path &path) {
    std::ifstream stream(path);if(!stream)throw std::runtime_error("Missing fixture "+path.string());
    Json value;stream>>value;return value;
}
static int member(const Json &model,const std::string &name) {
    const std::string suffix="."+name;int found=0,value=0;
    for(auto it=model.at("members").begin();it!=model.at("members").end();++it) {
        const auto &key=it.key();
        if(key.size()>=suffix.size() && key.compare(key.size()-suffix.size(),suffix.size(),suffix)==0) {
            ++found;value=it.value().get<int>();
        }
    }
    if(found!=1)throw std::runtime_error("Missing/ambiguous inherited member "+name);
    return value;
}
int main() {
    const auto root=port_root();
    const auto path=root/"native-fixtures/native-monster-numbers-41cef1ea";
    const auto content=read(root/"content/monsters.json").at("monsters");
    const auto first=read(path/"monster-numbers-a7.json");
    std::vector<Json> contexts{first.at("beforeRun"),first.at("run")};
    for(int asc:{8,9,10})contexts.push_back(read(path/("monster-numbers-a"+std::to_string(asc)+".json")).at("run"));
    const int levels[]={0,7,8,9,10};
    for(int contextIndex=0;contextIndex<5;++contextIndex) {
        const auto &context=contexts[contextIndex];const int asc=context.at("ascension");
        check(asc==levels[contextIndex],"actual native ascension context");
        check(context.at("monsters").size()==107,"all 107 active native models present");
        for(const auto &native:context.at("monsters")) {
            ++modelContexts;
            const std::string nativeId=native.at("id");
            const std::string id=nativeId.rfind("DECIMILLIPEDE_SEGMENT_",0)==0?"DECIMILLIPEDE_SEGMENT":nativeId;
            const MonsterDef *definition=nullptr;
            for(int i=1;i<static_cast<int>(MonsterId::COUNT);++i)
                if(id==audit_tables::MONSTER_DEFS[i].key)definition=&audit_tables::MONSTER_DEFS[i];
            const std::string label=nativeId+" A"+std::to_string(asc);
            check(definition!=nullptr,label+" mapped model");if(!definition)continue;
            const int tier=asc>=8?1:0;
            check(definition->hpLo[tier]==member(native,"MinInitialHp"),label+" min HP");
            check(definition->hpHi[tier]==member(native,"MaxInitialHp"),label+" max HP");numericChecks+=2;
            std::map<std::string,int> stateIndices;
            if(id=="AEONGLASS")stateIndices={{"EBB_MOVE",0},{"EYE_LASERS_MOVE",1},{"INCREASING_INTENSITY_MOVE",2}};
            else {
                int index=0;
                for(auto it=content.at(id).at("states").begin();it!=content.at(id).at("states").end();++it)
                    stateIndices[it.key()]=index++;
            }
            for(const auto &move:native.at("moves")) {
                ++moveContexts;const std::string moveId=move.at("id");
                auto found=stateIndices.find(moveId);check(found!=stateIndices.end(),label+" "+moveId+" mapped move");
                if(found==stateIndices.end())continue;
                const auto &state=audit_tables::MON_STATES[definition->stateOff+found->second];
                std::vector<const MonIntentDef*> ours;
                for(int i=0;i<state.intentN[tier];++i) {
                    const auto &intent=audit_tables::MON_INTENTS[state.intentOff[tier]+i];
                    if(intent.type==0)ours.push_back(&intent);
                }
                int index=0;
                for(const auto &intent:move.at("intents")) {
                    const std::string type=intent.at("type");
                    if(type!="SingleAttackIntent" && type!="MultiAttackIntent" && type!="DeathBlowIntent")continue;
                    check(index<static_cast<int>(ours.size()),label+" "+moveId+" missing attack intent");
                    if(index>=static_cast<int>(ours.size())){++index;continue;}
                    const auto &actual=*ours[index++];++attackContexts;
                    const int damage=asc>=9 && actual.deadlyDamage>=0?actual.deadlyDamage:actual.damage;
                    const int hits=asc>=9 && actual.deadlyHits>=0?actual.deadlyHits:actual.hits;
                    check(hits==intent.at("hits").get<int>(),label+" "+moveId+" hit count");++numericChecks;
                    const auto &expected=intent.at("damage");
                    if(nativeId=="THE_FORGOTTEN" && moveId=="DREAD" && expected.is_object() &&
                       expected.value("error","")=="InvalidOperationException") {
                        ++dynamicErrors;continue; // target Dexterity needs a Creature; runtime test required
                    }
                    int nativeDamage=expected.get<int>();
                    if(nativeId=="WATERFALL_GIANT" && moveId=="PRESSURE_GUN_MOVE") {
                        check(nativeDamage==0,label+" fresh PressureGun has no assigned combat damage");
                        nativeDamage=member(native,"BasePressureGunDamage"); // table is the base, runtime uses aux[2]
                    }
                    check(damage==nativeDamage,label+" "+moveId+" damage "+std::to_string(damage)+" vs "+std::to_string(nativeDamage));++numericChecks;
                }
                check(index==static_cast<int>(ours.size()),label+" "+moveId+" attack intent count");
            }
        }
    }
    check(dynamicErrors==5,"only five Forgotten Dread damage reads require combat context");
    std::cout<<modelContexts<<" model contexts, "<<moveContexts<<" move contexts, "<<attackContexts
             <<" attack contexts, "<<numericChecks<<" numeric checks; "<<dynamicErrors<<" explicit dynamic errors\n";
    return failures?1:0;
}
