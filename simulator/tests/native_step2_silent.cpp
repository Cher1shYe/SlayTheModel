#include "sts2/silent.h"
#include <nlohmann/json.hpp>
#include <algorithm>
#include <array>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <memory>
#include <set>
#include <string>
using namespace sts2;
using json=nlohmann::json;
namespace {
int checks=0,failures=0;
std::string label;
void check(bool ok,const std::string &what){++checks;if(!ok){++failures;std::cerr<<label<<" "<<what<<" FAIL\n";}}
template<class A,class B>void eq(const A &a,const B &b,const std::string &what){++checks;if(a!=b){++failures;std::cerr<<label<<" "<<what<<" got="<<a<<" expected="<<b<<"\n";}}
const std::map<std::string,PowerId> powers={
#include "../../native-round4-step2-silent-fixtures/native_power_test_ids.inc"
};
CardId card_id(const std::string &key){for(int i=1;i<static_cast<int>(CardId::COUNT);++i){const auto id=static_cast<CardId>(i);if(key==card_key(id)||key+"_CARD"==card_key(id))return id;}throw std::runtime_error("Unmapped native card "+key);}
Card parse_card(BattleContext &b,const json &v){
    Card c=make_card(card_id(v["id"]),v["upgraded"],b.require_card_uid());c.replay=v["replay"];
    if(v["retain"]&&!card_has(c,CF_RETAIN))c.retainThisCombat=true;
    if(v["sly"]&&!card_has(c,CF_SLY))c.slyThisCombat=true;
    if(!v["enchantment"].is_null()){
        if(v["enchantment"]=="INKY")c.enchantment=EnchantmentId::INKY;
        else throw std::runtime_error("Unmapped fixture enchantment");
        c.enchantmentAmount=v["amount"];
    }
    return c;
}
void card_matches(const Card &c,const json &v,const std::string &where){
    eq(std::string(card_key(c.id)),v["id"].get<std::string>(),where+" id");eq(c.upgraded,v["upgraded"].get<bool>(),where+" upgrade");
    eq(v["x"].get<bool>()&&card_cost(c)<0?0:card_cost(c),v["cost"].get<int>(),where+" cost");
    eq(card_has(c,CF_RETAIN),v["retain"].get<bool>(),where+" retain");eq(card_has(c,CF_SLY),v["sly"].get<bool>(),where+" sly");
    eq(static_cast<int>(c.replay),v["replay"].get<int>(),where+" replay");
    eq(c.enchantment==EnchantmentId::INKY?std::string("INKY"):std::string(),v["enchantment"].is_null()?std::string():v["enchantment"].get<std::string>(),where+" enchantment");
    eq(static_cast<int>(c.enchantmentAmount),v["amount"].is_null()?0:v["amount"].get<int>(),where+" enchantment amount");
}
void pile_matches(const Card *cards,int count,const json &v,const std::string &name,bool reverse=false){
    eq(count,static_cast<int>(v.size()),name+" count");
    for(int i=0;i<std::min(count,static_cast<int>(v.size()));++i)card_matches(cards[reverse?count-i-1:i],v[i],name+" #"+std::to_string(i));
}
std::array<int,static_cast<int>(PowerId::COUNT)> expected_powers(const json &v){
    std::array<int,static_cast<int>(PowerId::COUNT)> result{};
    for(const auto &p:v)result[static_cast<int>(powers.at(p["id"].get<std::string>()))]+=p["amount"].get<int>();return result;
}
void state_matches(BattleContext &b,const json &v,const std::string &phase){
    const auto saved=label;label+=" "+phase;
    eq(b.player.hp,v["hp"].get<int>(),"hp");eq(b.player.maxHp,v["maxHp"].get<int>(),"max hp");eq(b.player.block,v["block"].get<int>(),"block");eq(b.player.energy,v["energy"].get<int>(),"energy");
    const auto expected=expected_powers(v["powers"]);
    for(int i=0;i<static_cast<int>(PowerId::COUNT);++i)eq(b.player_power(static_cast<PowerId>(i)),expected[i],"player power "+std::to_string(i));
    eq(b.monsterCount,static_cast<int>(v["enemies"].size()),"monster count");
    for(int i=0;i<std::min(b.monsterCount,static_cast<int>(v["enemies"].size()));++i){
        const auto &e=v["enemies"][i];const auto expectedEnemy=expected_powers(e["powers"]);
        eq(b.monsters[i].hp,e["hp"].get<int>(),"enemy "+std::to_string(i)+" hp");eq(b.monsters[i].block,e["block"].get<int>(),"enemy block");
        for(int p=0;p<static_cast<int>(PowerId::COUNT);++p)eq(b.monster_power(i,static_cast<PowerId>(p)),expectedEnemy[p],"enemy "+std::to_string(i)+" power "+std::to_string(p));
    }
    pile_matches(b.hand,b.handCount,v["hand"],"hand");pile_matches(b.draw,b.drawCount,v["draw"],"draw",true);
    pile_matches(b.discard,b.discardCount,v["discard"],"discard");pile_matches(b.exhaust,b.exhaustCount,v["exhaust"],"exhaust");
    eq(b.silent.drawnThisCombat,v["drawnCombat"].get<int>(),"cards drawn combat");
    eq(b.silent.discardedThisTurn,v["discardedTurn"].get<int>(),"cards discarded turn");
    eq(b.silent.attacksFinishedThisTurn,v["attacksFinishedTurn"].get<int>(),"attacks finished turn");
    eq(b.silent.skillsFinishedThisTurn,v["skillsFinishedTurn"].get<int>(),"skills finished turn");
    eq(b.silent.shivsFinishedThisTurn,v["shivsFinishedTurn"].get<int>(),"shivs finished turn");
    eq(b.targetRng.counter,v["targetCounter"].get<int>(),"target RNG");eq(b.shuffleRng.counter,v["shuffleCounter"].get<int>(),"shuffle RNG");label=saved;
}
std::unique_ptr<BattleContext> setup(const json &v){
    auto b=std::make_unique<BattleContext>();Card deck[]={make_card(CardId::STRIKE_IRONCLAD,false,1),make_card(CardId::DEFEND_IRONCLAD,false,2)};
    b->init(Encounter::SETUP_CULTISTS_NORMAL,42,deck,2,0,80,80);
    b->handCount=b->drawCount=b->discardCount=b->exhaustCount=b->playCount=0;b->nextUid=1;b->clear_card_uid_reservations();
    b->player=Player();b->player.hp=v["hp"];b->player.maxHp=v["maxHp"];b->player.block=v["block"];b->player.energy=v["energy"];
    const auto pp=expected_powers(v["powers"]);for(int i=0;i<static_cast<int>(PowerId::COUNT);++i)power_ref(b->player,static_cast<PowerId>(i))=pp[i];
    for(int i=0;i<b->monsterCount;++i){auto &m=b->monsters[i];const auto &e=v["enemies"][i];m.hp=e["hp"];m.maxHp=e["maxHp"];m.block=e["block"];m.alive=e["alive"];m.strength=m.weak=m.vulnerable=0;std::fill(std::begin(m.power),std::end(m.power),0);const auto ep=expected_powers(e["powers"]);for(int j=0;j<static_cast<int>(PowerId::COUNT);++j)power_ref(m,static_cast<PowerId>(j))=ep[j];}
    for(const auto &c:v["hand"])b->hand[b->handCount++]=parse_card(*b,c);
    for(auto i=v["draw"].rbegin();i!=v["draw"].rend();++i)b->draw[b->drawCount++]=parse_card(*b,*i);
    for(const auto &c:v["discard"])b->discard[b->discardCount++]=parse_card(*b,c);
    for(const auto &c:v["exhaust"])b->exhaust[b->exhaustCount++]=parse_card(*b,c);
    b->silent=SilentState();b->silent.drawnThisCombat=v["drawnCombat"];b->silent.discardedThisTurn=v["discardedTurn"];b->silent.attacksFinishedThisTurn=v["attacksFinishedTurn"];b->silent.skillsFinishedThisTurn=v["skillsFinishedTurn"];b->silent.shivsFinishedThisTurn=v["shivsFinishedTurn"];
    b->targetRng=Rng(42);b->shuffleRng=Rng(42);return b;
}
void selections(BattleContext &b,const json &rows,int &index){
    int guard=0;
    while(b.pending.op!=ChoiceOp::NONE&&guard++<100){
        if(index>=static_cast<int>(rows.size())){check(false,"unexpected choice");b.resolve_choice(b.pending.cards[0].uid);continue;}
        const auto &row=rows[index++];eq(b.pending.count,static_cast<int>(row["options"].size()),"choice count");eq(b.pending.remaining,row["maxSelect"].get<int>(),"choice max");
        for(int i=0;i<std::min(b.pending.count,static_cast<int>(row["options"].size()));++i)eq(std::string(card_key(b.pending.cards[i].id)),row["options"][i].get<std::string>(),"choice option "+std::to_string(i));
        for(const auto &key:row["chosen"]){
            int found=-1;for(int i=0;i<b.pending.count;++i)if(b.pending.cards[i].id==card_id(key)){found=i;break;}
            check(found>=0,"chosen native card exists");if(found<0)break;
            b.resolve_choice(b.pending.cards[found].uid);
        }
    }
    check(guard<100,"choice continuation bounded");
}
bool turn_followup(const std::string &id){static const std::set<std::string> ids={"NOXIOUS_FUMES","INFINITE_BLADES","NIGHTMARE","TOOLS_OF_THE_TRADE","WRAITH_FORM","BLUR","WELL_LAID_PLANS","SHADOW_STEP","ANTICIPATE","DODGE_AND_ROLL","PREDATOR","SIDESTEP"};return ids.count(id)>0;}
}
int main(){
    const auto root=std::filesystem::path(__FILE__).parent_path().parent_path().parent_path();json fixtures;std::ifstream(root/"native-round4-step2-silent-fixtures/results.json")>>fixtures;
    check(fixtures["status"]=="completed","DLL fixtures completed");check(fixtures["gameAssemblySha256"]=="9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4","target DLL identity");
    for(const auto &f:fixtures["results"]){
        const std::string id=f["id"],mode=f["mode"];label=id+(f["upgraded"].get<bool>()?"+":"")+" "+mode;
        auto owner=setup(f["before"]);auto &b=*owner;int choiceIndex=0;
        const Card main=b.hand[0];b.auto_play_cards(&main,1,0,false);selections(b,f["selections"],choiceIndex);state_matches(b,f["immediate"],"immediate");
        if(mode=="followup"){
            if(id=="CORROSIVE_WAVE"||id=="SPEEDSTER")b.draw_cards(2);
            else if(turn_followup(id))b.end_player_turn();
            else{
                const auto next=id=="BURST"?CardId::DEFEND_SILENT:id=="SHIV"||id=="FAN_OF_KNIVES"||id=="PHANTOM_BLADES"?CardId::SHIV:CardId::STRIKE_SILENT;
                Card c=make_card(next,false,b.require_card_uid());silent_card_entered_combat(b,c,false);b.add_card_to_hand(c);b.auto_play_cards(&c,1,0,false);
            }
            selections(b,f["selections"],choiceIndex);state_matches(b,f["after"],"followup");
        }
        eq(choiceIndex,static_cast<int>(f["selections"].size()),"native choice calls consumed");
    }
    std::cout<<"Silent native fixtures: "<<fixtures["results"].size()<<" cases, "<<checks<<" checks, "<<failures<<" failures\n";return failures?1:0;
}
