// Differential assertions against the actual target DLL, plus selection boundaries.
#include "sts2/run.h"
#include "sts2/relics.h"
#include <nlohmann/json.hpp>
#include <cassert>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <cctype>
using namespace sts2;
using nlohmann::json;
int event3(const char *name) {
    for (int i=0;i<event_count();++i) if (!std::strcmp(event_info(i)->name,name)) return i;
    assert(false); return -1;
}
void deck_matches(const RunContext &r, const json &expected) {
    assert(r.deckCount==static_cast<int>(expected.size()));
    for (int i=0;i<r.deckCount;++i) {
        if (std::string(card_key(r.deck[i].id))!=expected[i]["card"])
            std::cerr<<"card "<<i<<": "<<card_key(r.deck[i].id)<<" != "<<expected[i]["card"]<<"\n";
        assert(std::string(card_key(r.deck[i].id))==expected[i]["card"]);
        assert(r.deck[i].upgraded==expected[i]["upgraded"]);
    }
}
std::string potion_key_normalized(std::string name) {
    std::string out;for(char c:name)if(c!='_')out.push_back(static_cast<char>(std::tolower(c)));return out;
}
int main() {
    auto path=std::filesystem::path(__FILE__).parent_path().parent_path().parent_path()
        / "native-round3-event-fixtures/results.json";
    std::ifstream input(path); json fixture; input>>fixture;
    assert(fixture["status"]=="completed");
    assert(fixture["gameAssemblySha256"]=="9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4");
    assert(fixture["gameSceneLoaded"]==false);
    int cases=0;
    for (const auto &expected:fixture["results"]) {
        const auto kind=expected["test"].get<std::string>();
        const auto seed=expected["seed"].get<std::uint64_t>();
        const auto starts=[&](const char *p){return kind.rfind(p,0)==0;};
        if(kind=="wellspring_bottle_full"||starts("courier_")) {
            RunContext r;r.init(42,0);r.hp=40;r.maxHp=80;r.potionCount=0;
            for(int i=0;i<3;++i)r.add_potion(PotionId::FIRE_POTION);
            r.playerRng[PRNG_REWARDS]=Rng(seed);
            event_begin(r,event3(starts("wellspring")?"WELLSPRING":"POTION_COURIER"),false);
            assert(r.step({RunActionType::EVENT_CHOICE,kind=="courier_ransack_full"?1:0}));
            assert(r.hp==expected["hp"]&&r.maxHp==expected["maxHp"]);
            assert(r.screen==RunScreen::REWARDS&&r.rewardResumeScreen==RunScreen::MAP);
            assert(r.potionCount==3&&r.pendingPotionCount==static_cast<int>(expected["offered"].size()));
            assert(r.playerRng[PRNG_REWARDS].counter==expected["rewardCounter"]);
            for(int i=0;i<r.pendingPotionCount;++i)
                assert(potion_key_normalized(potion_def(static_cast<PotionId>(r.pendingPotions[i])).key)==
                    potion_key_normalized(expected["offered"][i].get<std::string>()));
            RunContext copy;assert(RunContext::restore(r.serialize(),copy));r=copy;
            assert(!r.step({RunActionType::TAKE_POTION_REWARD,0}));
            assert(r.step({RunActionType::DISCARD_POTION,0}));
            assert(r.step({RunActionType::TAKE_POTION_REWARD,0}));
            assert(r.potionCount==3);++cases;continue;
        }
        if(starts("rest_") || kind=="dense_rest_feather") {
            RunContext r;r.init(42,0);r.relicCount=0;r.deckCount=0;
            for(CardId c:{CardId::STRIKE_IRONCLAD,CardId::DEFEND_IRONCLAD,CardId::BASH,CardId::ANGER,
                          CardId::POMMEL_STRIKE,CardId::IRON_WAVE})r.deck[r.deckCount++]=r.make_run_card(c,false);
            if(starts("rest_mailbox")) {
                r.add_relic(RelicId::TINY_MAILBOX);
                for(int i=0;i<3;++i)r.add_potion(PotionId::FIRE_POTION);
            } else if(kind=="dense_rest_feather")r.add_relic(RelicId::ETERNAL_FEATHER);
            else for(RelicId id:{RelicId::ETERNAL_FEATHER,RelicId::VENERABLE_TEA_SET,RelicId::REGAL_PILLOW,RelicId::STONE_HUMIDIFIER})r.add_relic(id);
            r.hp=30;r.maxHp=80;r.playerRng[PRNG_REWARDS]=Rng(42);
            if(kind=="dense_rest_feather") {
                event_begin(r,event3("DENSE_VEGETATION"),false);
                assert(r.step({RunActionType::EVENT_CHOICE,1}));
            } else {
                r.map.nodes[r.map.startIdx].type=static_cast<std::int8_t>(MapPointType::REST);
                r.enter_map_point(r.map.startIdx);
                if(kind=="rest_heal"||kind=="rest_mailbox_full")assert(r.step({RunActionType::REST_HEAL,0}));
                if(kind=="rest_upgrade"||kind=="rest_mailbox_upgrade")assert(r.step({RunActionType::REST_UPGRADE,2}));
            }
            assert(r.hp==expected["hp"]&&r.maxHp==expected["maxHp"]);
            assert(r.teaSetPending==expected["teaPending"]);
            assert(r.potionCount==static_cast<int>(expected["potions"].size()));
            assert(r.pendingPotionCount==static_cast<int>(expected["offered"].size()));
            assert(r.playerRng[PRNG_REWARDS].counter==expected["rewardCounter"]);
            if(kind=="rest_mailbox_full") {
                assert(r.pendingPotions[0]==static_cast<int>(PotionId::FAIRY_IN_ABOTTLE));
                assert(r.pendingPotions[1]==static_cast<int>(PotionId::VULNERABLE_POTION));
                assert(r.screen==RunScreen::REWARDS&&r.rewardResumeScreen==RunScreen::MAP);
                RunContext copy;assert(RunContext::restore(r.serialize(),copy));
                assert(r.step({RunActionType::DISCARD_POTION,0}));
                assert(r.step({RunActionType::TAKE_POTION_REWARD,0}));
                assert(r.potionCount==3);
            }
            deck_matches(r,expected["deck"]);++cases;continue;
        }
        const char *name=starts("dense")?"DENSE_VEGETATION":starts("aroma")?"AROMA_OF_CHAOS":
            starts("wellspring")?"WELLSPRING":starts("spirit")?"SPIRIT_GRAFTER":
            starts("tablet")?"TABLET_OF_TRUTH":starts("sunken")?"SUNKEN_STATUE":
            starts("this")?"THIS_OR_THAT":"LOST_WISP";
        RunContext r;r.init(42,0);r.hp=kind=="dense_fairy"||kind=="dense_tail"?3:40;r.maxHp=80;r.deckCount=0;
        for(CardId c:{CardId::STRIKE_IRONCLAD,CardId::DEFEND_IRONCLAD,CardId::BASH,CardId::ANGER,
                      CardId::POMMEL_STRIKE,CardId::IRON_WAVE}) r.deck[r.deckCount++]=r.make_run_card(c,false);
        if(kind.find("tungsten")!=std::string::npos)r.add_relic(RelicId::TUNGSTEN_ROD);
        if(kind=="dense_tail")r.add_relic(RelicId::LIZARD_TAIL);
        if(kind=="dense_fairy")r.add_potion(PotionId::FAIRY_IN_ABOTTLE);
        r.seed=seed-Rng::deterministic_hash_code(std::string_view(name));
        event_begin(r,event3(name),false);
        const int goldBefore=r.gold;
        const auto choose=[&](int opt){assert(r.step({RunActionType::EVENT_CHOICE,opt}));};
        if(starts("tablet")) {
            for(const auto &step:expected["steps"]) {
                choose(0);assert(r.hp==step["hp"]&&r.maxHp==step["maxHp"]);
                assert(r.eventRng.counter==step["rngCounter"]);deck_matches(r,step["deck"]);
            }
            if(kind=="tablet_giveup")choose(1);
        } else if(starts("aroma")||starts("wellspring")||starts("spirit")) {
            choose(kind=="aroma_transform"?0:1);
            assert(r.eventCardSelection&&r.screen==RunScreen::EVENT);
            assert(r.deckCount==6&&!r.deck[2].upgraded);
            assert(r.eventRng.counter==0);
            // Choice is player controlled and persists through snapshots.
            RunContext restored;assert(RunContext::restore(r.serialize(),restored));
            r = restored;
            assert(event_card_selectable(r,2));
            assert(r.step({RunActionType::EVENT_SELECT_CARD,2}));
        } else choose(starts("sunken")||starts("lost")?1:0);
        assert(r.hp==expected["hp"]&&r.maxHp==expected["maxHp"]);
        assert(r.gold-goldBefore==expected["goldDelta"]);
        assert(r.eventRng.counter==expected["rngCounter"]);
        assert(r.potionCount==static_cast<int>(expected["potions"].size()));
        assert(r.screen==RunScreen::MAP&&r.eventId==-1);
        deck_matches(r,expected["deck"]);++cases;
    }
    assert(cases==57);
    // Eternal cards cannot be selected; a sole eligible card auto-selects.
    for(const char *name:{"AROMA_OF_CHAOS","WELLSPRING"}) {
        RunContext r;r.init(42,0);r.deckCount=2;r.deck[0]=r.make_run_card(CardId::GREED,false);
        r.deck[1]=r.make_run_card(CardId::BASH,false);event_begin(r,event3(name),false);
        assert(r.step({RunActionType::EVENT_CHOICE,std::strcmp(name,"WELLSPRING")==0?1:0}));
        assert(!r.eventCardSelection&&r.deck[0].id==CardId::GREED);
    }
    std::cout<<"actual native round3 event oracle: "<<cases<<" cases plus selection boundaries passed\n";
}
