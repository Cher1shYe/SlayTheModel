// Native v0.111.0 / 41cef1ea, sts2.dll SHA-256 9cb4f1ad8c9f284a...
// Metadata comes from all canonical DLL models; effect outcomes from controlled
// DLL executions. This is targeted evidence, not full-run equivalence.
#include <cmath>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <nlohmann/json.hpp>
#include "sts2/battle.h"
#include "sts2/monsters.h"
#include "sts2/relics.h"
using namespace sts2;
using json=nlohmann::json;
namespace {
int checks=0, failures=0;
void check(const std::string &label,double got,double want) {
    ++checks;
    if(std::abs(got-want)>1e-10) { ++failures;std::cout<<label<<" got="<<got<<" native="<<want<<" FAIL\n"; }
}
BattleContext base() {
    BattleContext b;Card deck[20];
    for(int i=0;i<20;++i)deck[i]=make_card(CardId::STRIKE_IRONCLAD,false,i+1);
    b.init(Encounter::SETUP_CEREMONIAL_BEAST_BOSS,1234,deck,20,0,80,80);
    b.handCount=b.drawCount=b.discardCount=b.exhaustCount=b.knownTopCount=0;
    b.relicCount=0;b.player.energy=3;
    b.monsters[0].hp=b.monsters[0].maxHp=10000;b.monsters[0].block=0;
    std::memset(b.monsters[0].power,0,sizeof(b.monsters[0].power));
    b.monsters[0].vulnerable=b.monsters[0].weak=b.monsters[0].strength=0;
    return b;
}
void hand(BattleContext &b,CardId id,bool upgraded=false) { b.hand[b.handCount++]=make_card(id,upgraded,b.require_card_uid()); }
void draw(BattleContext &b,CardId id) { b.draw[b.drawCount++]=make_card(id,false,b.require_card_uid()); }
bool play(BattleContext &b) { Action a;a.type=ActionType::PLAY_CARD;a.hand=0;a.target=0;return b.step(a); }
std::string key(CardId id) {
    std::string s=card_key(id);if(s.size()>5&&s.substr(s.size()-5)=="_CARD")s.resize(s.size()-5);
    if(s=="SLOTH_STATUS")s="SLOTH";return s;
}
std::string norm(std::string s) {std::string r;for(char c:s)if(std::isalnum(c))r+=std::tolower(c);return r;}
#include "native_card_round3_vars.inc"
}
int main() {
    const auto repo=std::filesystem::path(__FILE__).parent_path().parent_path().parent_path();
    json metadata,effects,content;
    std::ifstream(repo/"native-round3-card-fixtures/metadata-results.json")>>metadata;
    std::ifstream(repo/"native-round3-card-fixtures/results.json")>>effects;
    std::ifstream(repo/"simulator/content/cards.json")>>content;
    check("native metadata target DLL",metadata["gameAssemblySha256"]=="9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4",true);
    check("native effect target DLL",effects["gameAssemblySha256"]==metadata["gameAssemblySha256"],true);
    std::map<std::string,json> models;for(auto &n:metadata["results"])models[n["id"]]=n;
    std::map<std::string,CardId> ids;
    for(int i=1;i<static_cast<int>(CardId::COUNT);++i) {
        const auto id=static_cast<CardId>(i);ids[key(id)]=id;
        if(!card_native_available(id))continue;
        check(key(id)+" native model exists",models.count(key(id)),1);
        if(!models.count(key(id))||id==CardId::MAD_SCIENCE)continue;
        const auto &n=models.at(key(id));const auto &d=card_def(id);const auto &local=content[i-1];
        const std::map<std::string,CardType> types={{"Attack",CardType::ATTACK},{"Skill",CardType::SKILL},{"Power",CardType::POWER},{"Status",CardType::STATUS},{"Curse",CardType::CURSE}};
        const std::map<std::string,Rarity> rarities={{"Basic",Rarity::BASIC},{"Common",Rarity::COMMON},{"Uncommon",Rarity::UNCOMMON},{"Rare",Rarity::RARE},{"Ancient",Rarity::ANCIENT},{"Event",Rarity::EVENT},{"Token",Rarity::TOKEN},{"Status",Rarity::STATUS},{"Curse",Rarity::CURSE}};
        check(key(id)+" type",int(d.type),int(types.at(n["type"])));
        check(key(id)+" rarity",int(d.rarity),int(rarities.at(n["rarity"])));
        check(key(id)+" combat generation",!(d.flags&CF_CANNOT_GENERATE_IN_COMBAT),bool(n["generated"]));
        for(bool up:{false,true}) {
            const auto c=make_card(id,up,1);const auto &v=n["variants"][up?1:0];const auto &vars=v["vars"];
            const std::string label=key(id)+(up?"+":"");
            check(label+" cost",card_cost(c),bool(v["xCost"])?-1:int(v["cost"]));
            if(card_is_attack(c)&&vars.contains("Damage"))check(label+" damage",card_base_damage(c),vars["Damage"]);
            if(vars.contains("Block"))check(label+" block",card_block(c),vars["Block"]);
            for(const auto &[flag,name]:std::vector<std::pair<int,std::string>>{{CF_EXHAUST,"Exhaust"},{CF_ETHEREAL,"Ethereal"},{CF_RETAIN,"Retain"},{CF_INNATE,"Innate"}}) {
                const bool expected=std::find(v["keywords"].begin(),v["keywords"].end(),name)!=v["keywords"].end();
                check(label+" "+name,card_has(c,flag),expected);
            }
            for(auto it=local["variants"][up?"upgraded":"base"]["effect_vars"].begin();it!=local["variants"][up?"upgraded":"base"]["effect_vars"].end();++it) {
                auto normalized=norm(it.key());if(normalized=="calcbase")normalized="calculationbase";if(normalized=="calcextra")normalized="calculationextra";
                for(auto nativeVar=vars.begin();nativeVar!=vars.end();++nativeVar) {
                    auto nn=norm(nativeVar.key());
                    if(nn!=normalized&&nn!=normalized+"power"&&normalized!=nn+"power")continue;
                    check(label+" "+it.key(),card_var(c,varIds.at(it.key())),nativeVar.value());break;
                }
            }
        }
    }
    for(const auto &f:effects["results"]) {
        const std::string test=f["test"];
        if(test=="card_effect") {
            const auto id=ids.at(f["id"]);bool up=f["upgraded"],powered=f["powered"];
            auto b=base();hand(b,id,up);hand(b,CardId::DEFEND_IRONCLAD);draw(b,CardId::STRIKE_IRONCLAD);draw(b,CardId::BASH);
            if(id==CardId::NOT_YET)b.player.hp=40;
            if(powered&&id==CardId::SPITE)b.damage_player(1,true);
            if(powered&&(id==CardId::CONFLAGRATION||id==CardId::VOLLEY||id==CardId::RIP_AND_TEAR||id==CardId::SWORD_BOOMERANG)) {b.add_player_power(PowerId::STRENGTH,3);b.add_player_power(PowerId::VIGOR,4);}
            if(powered&&id==CardId::DOMINATE)b.apply_vulnerable(0,2);
            const std::string label=key(id)+(up?"+":"")+(powered?" powered":" plain");
            check(label+" playable",play(b),1);
            const bool random=id==CardId::VOLLEY||id==CardId::RIP_AND_TEAR||id==CardId::SWORD_BOOMERANG;
            check(label+" damage",10000-b.monsters[0].hp,f[random?"totalDamage":"damage"]);
            check(label+" energy",b.player.energy,f["energy"]);check(label+" strength",b.player.strength,f["strength"]);
            check(label+" vulnerable",b.monsters[0].vulnerable,f["vulnerable"]);
            check(label+" hand count",b.handCount,f["hand"].size());check(label+" exhaust count",b.exhaustCount,f["exhaust"].size());
            if(id==CardId::NOT_YET)check(label+" healing",b.player.hp,f["hp"]);
        } else if(test=="drum_exhaust") {
            auto b=base();const bool up=f["upgraded"],dupe=f["duplicate"];
            if(dupe)b.add_player_power(PowerId::DUPLICATION,1);
            b.move_to_exhaust(make_card(CardId::DRUM_OF_BATTLE_CARD,up,b.require_card_uid()));
            check("Drum exhaust energy",b.player.energy,f["energy"]);check("Drum consumes duplication",b.player_power(PowerId::DUPLICATION),f["duplication"]);
        } else if(test=="brightest_max_hp") {
            auto b=base();bool up=f["upgraded"];const std::string modifier=f["modifier"];
            b.player.maxHp=modifier=="small_max"?2:80;b.player.hp=modifier=="small_max"?2:modifier=="injured"?40:80;
            hand(b,CardId::BRIGHTEST_FLAME,up);hand(b,CardId::DEFEND_IRONCLAD);
            if(modifier=="rupture")b.add_player_power(PowerId::RUPTURE,2);
            if(modifier=="tungsten")b.relics[b.relicCount++]=int(RelicId::TUNGSTEN_ROD);
            if(modifier=="buffer")b.add_player_power(PowerId::BUFFER,1);
            play(b);check("Brightest "+modifier+" hp",b.player.hp,f["hp"]);check("Brightest "+modifier+" max",b.player.maxHp,f["max"]);
            check("Brightest "+modifier+" strength",b.player.strength,f["strength"]);check("Brightest "+modifier+" buffer",b.player_power(PowerId::BUFFER),f["buffer"]);
        } else if(test=="maul_self_growth_replay") {
            auto b=base();hand(b,CardId::MAUL,f["upgraded"]);b.hand[0].replay=1;draw(b,CardId::MAUL);play(b);
            check("Maul replay damage",10000-b.monsters[0].hp,f["damage"]);
            check("Maul self growth",card_base_damage(b.discard[0]),f["selfDamage"]);
            check("Maul other copy growth",card_base_damage(b.draw[0]),f["otherDamage"]);
        } else if(test=="rend_debuff") {
            auto b=base();hand(b,CardId::REND);const std::string modifier=f["modifier"];
            if(modifier=="negative_strength")b.monsters[0].strength=-2;
            if(modifier=="mangle")b.apply_strength_loss(0,2);
            if(modifier=="dampen")b.add_monster_power(0,PowerId::DAMPEN,1);
            if(modifier=="plow")b.add_monster_power(0,PowerId::PLOW,1);
            if(modifier=="imbalanced")b.add_monster_power(0,PowerId::IMBALANCED,1);
            play(b);check("Rend "+modifier,10000-b.monsters[0].hp,f["damage"]);
        }
    }
    {
        auto b=base();hand(b,CardId::SECOND_WIND);hand(b,CardId::SHRUG_IT_OFF);hand(b,CardId::DEFEND_IRONCLAD);draw(b,CardId::BASH);draw(b,CardId::STRIKE_IRONCLAD);b.add_player_power(PowerId::DARK_EMBRACE,1);play(b);
        check("Second Wind block",b.player.block,10);check("Second Wind snapshot count",b.exhaustCount,2);check("Second Wind snapshot first",int(b.exhaust[0].id),int(CardId::SHRUG_IT_OFF));check("Second Wind keeps drawn cards",b.handCount,2);
    }
    {
        auto b=base();hand(b,CardId::ANOINTED);for(int i=0;i<8;++i)hand(b,CardId::DEFEND_IRONCLAD);draw(b,CardId::FEED);draw(b,CardId::FIEND_FIRE);draw(b,CardId::IMPERVIOUS);
        const auto rngBefore=b.cardSelectionRng.counter;play(b);check("Anointed fills free slots",b.handCount,10);check("Anointed leaves remaining rare",b.drawCount,1);check("Anointed never discards overflow",b.discardCount,0);check("Anointed shuffles whole candidate list",b.cardSelectionRng.counter-rngBefore,2);
    }
    {
        auto b=base();hand(b,CardId::HIDDEN_GEM);draw(b,CardId::STRIKE_IRONCLAD);b.draw[0].replay=1;draw(b,CardId::BASH);draw(b,CardId::SLIMED);play(b);
        check("Hidden Gem excludes prior replay",b.draw[0].replay,1);check("Hidden Gem prefers ordinary card",b.draw[1].replay,2);check("Hidden Gem skips playable status while normal candidate exists",b.draw[2].replay,0);
        b.handCount=b.discardCount=0;hand(b,CardId::HIDDEN_GEM);play(b);check("Hidden Gem fallback playable status",b.draw[2].replay,2);
    }
    {
        auto b=base();hand(b,CardId::CATASTROPHE);draw(b,CardId::WOUND);draw(b,CardId::STRIKE_IRONCLAD);draw(b,CardId::BASH);const auto selection=b.cardSelectionRng.counter,shuffle=b.shuffleRng.counter;play(b);
        check("Catastrophe leaves unplayable",b.drawCount,1);check("Catastrophe remaining Wound",int(b.draw[0].id),int(CardId::WOUND));check("Catastrophe uses Shuffle RNG",b.shuffleRng.counter-shuffle,1);check("Catastrophe leaves selection RNG",b.cardSelectionRng.counter,selection);
    }
    for(auto id:{CardId::ARMAMENTS,CardId::CASCADE,CardId::PRIMAL_FORCE,CardId::STOKE,CardId::SPLASH,CardId::ENLIGHTENMENT}) {auto c=make_card(id,false,1);check(key(id)+" behavior-only upgrade",card_upgradable(c),1);card_apply_upgrade(c);check(key(id)+" only one upgrade",card_upgradable(c),0);}
    check("legacy Grapple unavailable",card_native_available(CardId::GRAPPLE),false);
    std::cout<<checks<<" checks, "<<failures<<" failures\n";return failures?1:0;
}
