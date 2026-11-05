#include "sts2/run.h"
#include "sts2/relics.h"
#include <nlohmann/json.hpp>
#include <cassert>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>

using namespace sts2;
using nlohmann::json;

namespace {
RelicId relic_id(const std::string &key) {
    for (int i = 1; i < static_cast<int>(RelicId::COUNT); ++i)
        if (key == relic_def(static_cast<RelicId>(i)).key) return static_cast<RelicId>(i);
    assert(false && "fixture relic must be represented"); return RelicId::INVALID;
}
CardId card_id(const std::string &key) {
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i)
        if (key == card_key(static_cast<CardId>(i))) return static_cast<CardId>(i);
    assert(false); return CardId::INVALID;
}
void load_bag(RelicBagState &bag, const json &source) {
    bag = RelicBagState{};
    const char *names[] = {"Common", "Uncommon", "Rare", "Shop"};
    for (int slot = 0; slot < RELIC_BAG_SLOTS; ++slot)
        for (const auto &key : source[names[slot]])
            bag.entries[slot][bag.counts[slot]++] = static_cast<int>(relic_id(key));
}
std::unique_ptr<RunContext> base(std::uint64_t seed, const json &bag) {
    auto r = std::make_unique<RunContext>();r->init(147, 0);r->screen = RunScreen::SHOP;
    r->relicCount=1;r->relics[0]=static_cast<int>(RelicId::BURNING_BLOOD);
    std::fill(std::begin(r->relicAux),std::end(r->relicAux),0);
    std::fill(std::begin(r->relicWax),std::end(r->relicWax),false);
    std::fill(std::begin(r->relicMelted),std::end(r->relicMelted),false);
    r->deckCount=0;
    for(auto id:{CardId::STRIKE_IRONCLAD,CardId::DEFEND_IRONCLAD,CardId::BASH})r->deck[r->deckCount++]=r->make_run_card(id,false);
    r->hp=r->maxHp=80;
    load_bag(r->playerRelicBag,bag);load_bag(r->sharedRelicBag,bag);r->relicBagsInitialized=true;
    r->playerRng[PRNG_REWARDS]=Rng(seed);r->runRng[RNG_NICHE]=Rng(123);
    return r;
}
void check_relics(const RunContext &r,const json &expected) {
    assert(r.relicCount==static_cast<int>(expected.size()));
    for(int i=0;i<r.relicCount;++i) {
        assert(r.relics[i]==static_cast<int>(relic_id(expected[i]["id"])));
        assert(r.relicWax[i]==expected[i]["wax"]);
        assert(r.relicMelted[i]==expected[i]["melted"]);
        assert(r.relicAux[i]==expected[i]["counter"]);
    }
}
void check_deck(const RunContext &r,const json &expected) {
    assert(r.deckCount==static_cast<int>(expected.size()));
    for(int i=0;i<r.deckCount;++i) {
        assert(r.deck[i].id==card_id(expected[i]["id"]));
        assert(r.deck[i].upgraded==expected[i]["upgraded"]);
    }
}
void check_bag(const RelicBagState &bag,const json &expected) {
    const char *names[]={"Common","Uncommon","Rare","Shop"};
    for(int slot=0;slot<RELIC_BAG_SLOTS;++slot) {
        const auto &ids=expected[names[slot]];assert(bag.counts[slot]==static_cast<int>(ids.size()));
        for(int i=0;i<bag.counts[slot];++i)assert(bag.entries[slot][i]==static_cast<int>(relic_id(ids[i])));
    }
}
void check_rewards(const RunContext &r,const json &offered) {
    assert(r.screen==RunScreen::REWARDS&&r.pendingRelicCount==static_cast<int>(offered.size()));
    for(int i=0;i<r.pendingRelicCount;++i) {
        assert(r.pendingRelics[i]==static_cast<int>(relic_id(offered[i]["id"])));
        assert(r.pendingRelicWax[i]==offered[i]["wax"]&&!r.pendingRelicClaimed[i]);
    }
}
void roundtrip(RunContext &r) {
    auto restored=std::make_unique<RunContext>();
    const auto bytes=r.serialize();assert(RunContext::restore(bytes,*restored));assert(restored->serialize()==bytes);
    r=*restored;
}
}

int main() {
    const auto path=std::filesystem::path(__FILE__).parent_path().parent_path().parent_path()/"native-round4-step2-relic-lifecycle-fixtures/results.json";
    std::ifstream input(path);json data;input>>data;
    assert(data["status"]=="completed"&&data["gameAssemblySha256"]=="9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4");
    const json standardBag=data["results"][0]["bagBefore"];
    int cases=0;
    for(const auto &row:data["results"]) {
        const std::string kind=row["test"];
        if(kind=="toy_box") {
            auto owned=base(row["seed"],row["bagBefore"]);auto &r=*owned;
            assert(r.add_relic(RelicId::TOY_BOX));check_rewards(r,row["offered"]);check_relics(r,row["inventoryAtOffer"]);
            roundtrip(r);
            for(const auto &selected:row["selected"])assert(r.step({RunActionType::TAKE_RELIC_REWARD,selected.get<int>()}));
            assert(r.step({RunActionType::LEAVE_REWARDS,0}));check_relics(r,row["afterObtain"]);
            for(int i=0;i<r.relicCount;++i)r.relicAux[i]=row["beforeCombats"][i]["counter"];
            for(const auto &turn:row["turns"]) {
                relics_after_combat_end_lifecycle(r);
                assert(r.toyBoxCombats==turn["combatsSeen"]);
                check_relics(r,turn["relics"]);
                for(int i=0;i<r.relicCount;++i) {
                    const auto id=static_cast<RelicId>(r.relics[i]);
                    assert(run_owns_relic(r,id));assert(run_relic_active_at(r,i)==!r.relicMelted[i]);
                    const auto &hooks=turn["activeHookRelics"];
                    const bool nativeActive=std::find(hooks.begin(),hooks.end(),relic_def(id).key)!=hooks.end();
                    assert(run_has_relic(r,id)==nativeActive);
                }
                if(turn["combat"].get<int>()%3==0)roundtrip(r);
            }
            check_bag(r.playerRelicBag,row["bagAfter"]);
            assert(r.playerRng[PRNG_REWARDS].counter==row["rewardCounter"]&&r.runRng[RNG_NICHE].counter==row["nicheCounter"]);
        } else if(kind=="small_capsule") {
            auto owned=base(row["seed"],row["bagBefore"]);auto &r=*owned;
            assert(r.add_relic(RelicId::SMALL_CAPSULE));check_rewards(r,row["offered"]);check_relics(r,row["inventoryAtOffer"]);
            if(row["claim"])assert(r.step({RunActionType::TAKE_RELIC_REWARD,0}));
            assert(r.step({RunActionType::LEAVE_REWARDS,0}));check_relics(r,row["after"]);check_bag(r.playerRelicBag,row["bagAfter"]);
            assert(r.playerRng[PRNG_REWARDS].counter==row["rewardCounter"]&&r.runRng[RNG_NICHE].counter==0);
        } else if(kind=="large_capsule") {
            auto owned=base(row["seed"],row["bagBefore"]);auto &r=*owned;
            if(row["hooks"]){assert(r.add_relic(RelicId::MOLTEN_EGG));assert(r.add_relic(RelicId::BING_BONG));}
            assert(r.add_relic(RelicId::LARGE_CAPSULE));check_relics(r,row["after"]);check_deck(r,row["deckAfter"]);check_bag(r.playerRelicBag,row["bagAfter"]);
            assert(!r.largeCapsuleCardsPending&&r.largeCapsuleRelicsRemaining==0);
            assert(r.playerRng[PRNG_REWARDS].counter==row["rewardCounter"]&&r.runRng[RNG_NICHE].counter==0);
        } else if(kind=="empty_bag") {
            const json empty={{"Common",json::array()},{"Uncommon",json::array()},{"Rare",json::array()},{"Shop",json::array()}};
            auto owned=base(42,empty);auto &r=*owned;
            const bool toy=row["kind"]=="toy";assert(r.add_relic(toy?RelicId::TOY_BOX:RelicId::LARGE_CAPSULE));
            if(toy){check_rewards(r,row["offered"]);for(int i=0;i<5;++i)assert(r.step({RunActionType::TAKE_RELIC_REWARD,i}));assert(r.step({RunActionType::LEAVE_REWARDS,0}));}
            check_relics(r,row["after"]);assert(r.playerRng[PRNG_REWARDS].counter==row["rewardCounter"]);
        } else if(kind=="large_waits_for_child_reward") {
            auto owned=base(42,standardBag);auto &r=*owned;
            // Equivalent controlled override to native TestRngInjector: place
            // SmallCapsule first in the rolled bucket only for this fixture.
            Rng predict(42);float roll=predict.next_float();const int slot=roll<.5f?0:(roll<.83f?1:2);
            auto &bag=r.playerRelicBag;
            for(int i=bag.counts[slot];i>0;--i)bag.entries[slot][i]=bag.entries[slot][i-1];
            bag.entries[slot][0]=static_cast<int>(RelicId::SMALL_CAPSULE);++bag.counts[slot];
            assert(r.add_relic(RelicId::LARGE_CAPSULE));check_relics(r,row["paused"]["relics"]);
            assert(row["wasPaused"]==true&&r.deckCount==row["paused"]["deckCount"]);
            assert(r.largeCapsuleRelicsRemaining==1&&r.largeCapsuleCardsPending);
            assert(r.playerRng[PRNG_REWARDS].counter==row["paused"]["rewardCounter"]);
            assert(r.pendingRelicCount==1&&r.pendingRelics[0]==static_cast<int>(relic_id(row["offered"][0])));
            roundtrip(r);assert(r.step({RunActionType::LEAVE_REWARDS,0}));
            check_relics(r,row["after"]);check_deck(r,row["deckAfter"]);
            assert(!r.largeCapsuleCardsPending&&r.playerRng[PRNG_REWARDS].counter==row["rewardCounter"]);
        } else {assert(false);}
        ++cases;
    }
    assert(cases==24);
    {
        BattleContext b{};b.player.hp=b.player.maxHp=80;b.relicCount=3;
        b.relics[0]=static_cast<int>(RelicId::VAJRA);b.relics[1]=static_cast<int>(RelicId::PEN_NIB);b.relics[2]=static_cast<int>(RelicId::LIZARD_TAIL);
        for(int i=0;i<3;++i)b.relicWax[i]=b.relicMelted[i]=true;
        b.relicAux[1]=9;relics_combat_start(b);
        assert(b.player.strength==0&&b.relicAux[1]==9&&!relic_has(b,RelicId::PEN_NIB));
        b.player.hp=0;assert(!relics_try_revive(b));
    }
    {
        auto owned=base(42,standardBag);auto &r=*owned;
        // A capsule claimed from an already-open parent reward page still
        // resolves its immediate obtains and cards before that page is left.
        r.screen=RunScreen::REWARDS;
        assert(r.add_relic(RelicId::LARGE_CAPSULE));
        assert(r.deckCount==5&&r.relicCount==4&&!r.largeCapsuleCardsPending);
    }
    std::cout<<"native step2 relic lifecycle: "<<cases<<" DLL fixtures plus melted-hook, snapshot and parent-reward checks passed\n";
}
