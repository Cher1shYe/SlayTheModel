#include "sts2/relic_card_rewards.h"
#include "sts2/relics.h"
#include <nlohmann/json.hpp>
#include <cassert>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <string>
using namespace sts2;
using json=nlohmann::json;
namespace {
int checks=0,failures=0;
void check(const std::string &label,bool ok){++checks;if(!ok){++failures;std::cerr<<label<<" FAIL\n";}}
CardId card(const std::string &key) {
    for(int i=1;i<static_cast<int>(CardId::COUNT);++i){const CardId id=static_cast<CardId>(i);const std::string cpp=card_key(id);if(cpp==key||cpp==key+"_CARD")return id;}
    std::cerr<<"unmapped native card: "<<key<<"\n";return CardId::INVALID;
}
EnchantmentId enchantment(const std::string &key) {
    if(key=="NIMBLE")return EnchantmentId::NIMBLE;if(key=="GLAM")return EnchantmentId::GLAM;if(key=="SWIFT")return EnchantmentId::SWIFT;
    return EnchantmentId::NONE;
}
void card_matches(const Card &c,const json &v,const std::string &label) {
    check(label+" identity "+card_key(c.id)+" expected "+v["card"].get<std::string>(),c.id==card(v["card"]));
    check(label+" upgrade",c.upgraded==v["upgraded"]);
    check(label+" cost",card_cost(c)==v["cost"] || (card_cost(c)==-1&&v["cost"]==0)); // native X displays canonical 0
    check(label+" enchantment",c.enchantment==(v["enchantment"].is_null()?EnchantmentId::NONE:enchantment(v["enchantment"])));
    check(label+" enchantment amount",c.enchantmentAmount==(v["amount"].is_null()?0:v["amount"].get<int>()));
}
void add_relic_silent(RunContext &r,RelicId id) {r.relics[r.relicCount]=static_cast<int>(id);r.relicAux[r.relicCount]=0;r.relicMelted[r.relicCount]=false;++r.relicCount;if(id==RelicId::SILVER_CRUCIBLE)r.silverCrucibleUses=3;}
void hooks(RunContext &r,const std::string &hook) {
    if(hook=="eggs"){add_relic_silent(r,RelicId::MOLTEN_EGG);add_relic_silent(r,RelicId::TOXIC_EGG);add_relic_silent(r,RelicId::FROZEN_EGG);}
    if(hook=="lens"||hook=="lens_glitter")add_relic_silent(r,RelicId::FRESNEL_LENS);
    if(hook=="glitter"||hook=="lens_glitter"||hook=="glitter_lens")add_relic_silent(r,RelicId::GLITTER);
    if(hook=="glitter_lens")add_relic_silent(r,RelicId::FRESNEL_LENS);
    if(hook=="wing")add_relic_silent(r,RelicId::WING_CHARM);
    if(hook=="silver")add_relic_silent(r,RelicId::SILVER_CRUCIBLE);
    if(hook=="silken")add_relic_silent(r,RelicId::SILKEN_TRESS);
    if(hook=="dingy")add_relic_silent(r,RelicId::DINGY_RUG);
    if(hook=="prismatic")add_relic_silent(r,RelicId::PRISMATIC_GEM);
}
CardPool sea_pool(const std::string &kind) {
    if(kind=="sea_SILENT")return CardPool::SILENT;if(kind=="sea_REGENT")return CardPool::REGENT;
    if(kind=="sea_NECROBINDER")return CardPool::NECROBINDER;if(kind=="sea_DEFECT")return CardPool::DEFECT;
    return CardPool::IRONCLAD;
}
}
int main() {
    const auto root=std::filesystem::path(__FILE__).parent_path().parent_path().parent_path();json fixture;
    std::ifstream(root/"native-round4-step2-card-reward-fixtures/results.json")>>fixture;
    check("native fixture completed",fixture["status"]=="completed");
    check("target DLL",fixture["gameAssemblySha256"]=="9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4");
    for(const auto &f:fixture["results"]) {
        const std::string kind=f["test"],hook=f["hook"];
        const std::string label=kind+" "+hook+" seed="+std::to_string(f["seed"].get<std::uint64_t>());
        auto owner=std::make_unique<RunContext>();auto &r=*owner;r.init(42,f["ascension"]);r.act=f["act"];r.screen=RunScreen::REST;
        r.deckCount=0;r.relicCount=0;add_relic_silent(r,RelicId::BURNING_BLOOD);hooks(r,hook);
        r.playerRng[PRNG_REWARDS]=Rng(f["seed"].get<std::uint64_t>());r.runRng[RNG_NICHE]=Rng(f["seed"].get<std::uint64_t>());
        r.cardRarityOdds=f["pityBefore"];Card generated[15]{};int count=0;
        if(kind=="tome") {
            const CardId prepared=prepare_dusty_tome_card(r);
            check(label+" prepared card",prepared==card(f["prepared"]));
            check(label+" setup RNG",r.playerRng[PRNG_REWARDS].counter==f["preparedCounter"]);
            check(label+" obtain",obtain_dusty_tome_card(r,prepared));
            check(label+" obtain count",r.deckCount==static_cast<int>(f["added"].size()));
            if(r.deckCount)card_matches(r.deck[0],f["added"][0],label);
        } else {
            const RelicId source=kind=="lead"?RelicId::LEAD_PAPERWEIGHT:kind=="arcane"?RelicId::ARCANE_SCROLL:kind=="dream"?RelicId::DREAM_CATCHER:RelicId::SEA_GLASS;
            count=make_relic_card_reward_candidates(r,source,generated,15,sea_pool(kind));
            const auto &expected=kind=="arcane"?f["added"]:f["offered"];
            check(label+" candidate count",count==static_cast<int>(expected.size()));
            for(int i=0;i<std::min(count,static_cast<int>(expected.size()));++i)card_matches(generated[i],expected[i],label+" #"+std::to_string(i));
            check(label+" generation does not acquire automatically",r.deckCount==0);
            for(int i=0;i<count;++i)for(int j=0;j<i;++j)check(label+" distinct candidates",generated[i].id!=generated[j].id);
        }
        check(label+" reward RNG",r.playerRng[PRNG_REWARDS].counter==f["rewardsCounter"]);
        check(label+" niche RNG",r.runRng[RNG_NICHE].counter==f["nicheCounter"]);
        check(label+" rarity pity",std::abs(r.cardRarityOdds-f["pityAfter"].get<float>())<1e-7);
        if(hook=="silver")check(label+" silver uses",3-r.silverCrucibleUses==f["silverUsed"]);
        if(hook=="silken")check(label+" silken state",(r.relicAux[1]!=0)==f["silkenUsed"]);
    }
    // Invalid source/capacity requests must not consume RNG or mutate state.
    auto owner=std::make_unique<RunContext>();owner->init(42,0);Card out[15];const auto before=owner->serialize();
    check("small output rejected",make_relic_card_reward_candidates(*owner,RelicId::SEA_GLASS,out,14)==-1);
    check("unknown source rejected",make_relic_card_reward_candidates(*owner,RelicId::BURNING_BLOOD,out,15)==-1);
    check("invalid requests atomic",owner->serialize()==before);
    check("Dusty cannot invent an unprepared card",!obtain_dusty_tome_card(*owner,CardId::INVALID));
    std::cout<<"native step2 card rewards: "<<fixture["results"].size()<<" DLL cases, "<<checks<<" checks, "<<failures<<" failures\n";
    return failures?1:0;
}
