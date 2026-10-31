// Actual native DLL controlled event results, not source-derived expected values.
#include "sts2/run.h"
#include <nlohmann/json.hpp>
#include <cassert>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iostream>
using namespace sts2;
using nlohmann::json;
int main() {
    auto path = std::filesystem::path(__FILE__).parent_path().parent_path().parent_path()
        / "native-event-round2-fixtures/results.json";
    std::ifstream input(path); json fixture; input >> fixture;
    assert(fixture["status"] == "completed");
    assert(fixture["gameAssemblySha256"] == "9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4");
    assert(fixture["gameSceneLoaded"] == false);
    int cases = 0;
    for (const auto &expected : fixture["results"]) {
        const auto kind = expected["test"].get<std::string>();
        const auto seed = expected["seed"].get<std::uint64_t>();
        const char *name = kind.find("baths") == 0 ? "ABYSSAL_BATHS"
            : kind.find("treasury") == 0 ? "SUNKEN_TREASURY" : "DOORS_OF_LIGHT_AND_DARK";
        int id = -1;
        for (int i = 0; i < event_count(); ++i) if (std::strcmp(event_info(i)->name, name) == 0) id = i;
        assert(id >= 0);
        RunContext r; r.init(42, 0); r.hp = 40; r.maxHp = 80; r.deckCount = 0;
        for (CardId card : {CardId::STRIKE_IRONCLAD, CardId::DEFEND_IRONCLAD, CardId::BASH,
                           CardId::ANGER, CardId::POMMEL_STRIKE, CardId::IRON_WAVE})
            r.deck[r.deckCount++] = r.make_run_card(card, false);
        // Native fixture explicitly reseeds the event RNG. Arrange the same
        // stream through EventModel.BeginEvent's seed derivation, so the actual
        // simulator CalculateVars path is exercised without injecting its data.
        r.seed = seed - Rng::deterministic_hash_code(std::string_view(name));
        event_begin(r, id, false);
        const auto choose = [&](int option) { assert(r.step({RunActionType::EVENT_CHOICE, option})); };
        int goldBefore = r.gold;
        if (kind == "baths_immerse") {
            for (const auto &step : expected["steps"]) {
                choose(0); assert(r.hp == step["hp"] && r.maxHp == step["maxHp"]);
            }
            choose(1);
        } else if (kind == "baths_abstain") choose(1);
        else if (kind.find("treasury") == 0) {
            assert(r.eventData[0] == expected["steps"][0]["small"]);
            assert(r.eventData[1] == expected["steps"][0]["large"]);
            choose(kind == "treasury_small" ? 0 : 1);
        } else choose(0);
        assert(r.hp == expected["hp"] && r.maxHp == expected["maxHp"]);
        assert(r.gold - goldBefore == expected["goldDelta"]);
        assert(r.screen == RunScreen::MAP && r.eventId == -1);
        assert(r.eventRng.counter == expected["rngCounter"]);
        assert(r.deckCount == static_cast<int>(expected["deck"].size()));
        for (int i = 0; i < r.deckCount; ++i) {
            assert(std::string(card_key(r.deck[i].id)) == expected["deck"][i]["card"]);
            assert(r.deck[i].upgraded == expected["deck"][i]["upgraded"]);
        }
        ++cases;
    }
    assert(cases == 15);
    std::cout << "actual native event oracle: " << cases << " Baths/Treasury/Doors cases passed\n";
}
