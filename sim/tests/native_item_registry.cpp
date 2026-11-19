// Compare the actual compiled item tables with the immutable native DLL export.
#include "sts2/relics.h"
#include "sts2/relic_raw_rarity.h"
#include "port_root.h"
#include <nlohmann/json.hpp>
#include <cassert>
#include <fstream>
#include <map>
#include <string>
using namespace sts2;
int main() {
    std::ifstream input(port_root() / "native-fixtures/native-registry-41cef1ea.json");
    nlohmann::json native; input >> native;
    assert(native.at("gameDllSha256") == "9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4");
    const std::map<std::string, int> rarity = {{"None",-1},{"Starter",0},{"Common",1},
        {"Uncommon",2},{"Rare",3},{"Shop",4},{"Event",5},{"Ancient",7}};
    const std::map<std::string, PotionTarget> targets = {{"Self",PotionTarget::SELF},
        {"AnyEnemy",PotionTarget::ANY_ENEMY},{"AllEnemies",PotionTarget::ALL_ENEMIES},
        {"AnyPlayer",PotionTarget::ANY_PLAYER},{"TargetedNoCreature",PotionTarget::TARGETED_NO_CREATURE}};
    const std::map<std::string, PotionUsage> usage = {{"CombatOnly",PotionUsage::COMBAT_ONLY},
        {"AnyTime",PotionUsage::ANY_TIME},{"Automatic",PotionUsage::AUTOMATIC}};
    int checked = 0;
    for (const auto &row : native.at("relics")) {
        int found = 0;
        for (int i=1;i<static_cast<int>(RelicId::COUNT);++i) {
            const auto id=static_cast<RelicId>(i);
            const auto &def=relic_def(id);
            if (row.at("className") != def.name) continue;
            ++found;
            const int raw=rarity.at(row.at("rarityName").get<std::string>());
            assert(relic_raw_rarity(id)==raw);
            assert(def.rarity==(raw>=1&&raw<=3?static_cast<Rarity>(raw):Rarity::SPECIAL));
        }
        assert(found==1); ++checked;
    }
    assert(checked==static_cast<int>(RelicId::COUNT)-1);
    checked=0;
    for (const auto &row : native.at("potions")) {
        const auto name=row.at("className").get<std::string>();
        if (name=="MockDiscardAndAddShivsPotion") continue;
        int found=0;
        for (int i=1;i<static_cast<int>(PotionId::COUNT);++i) {
            const auto id=static_cast<PotionId>(i);
            const auto &def=potion_def(id);
            if (name!=def.key) continue;
            ++found;
            const auto target=targets.at(row.at("targetName").get<std::string>());
            assert(potion_target(id,false)==target);
            assert(potion_target(id,true)==(name=="FoulPotion"?PotionTarget::ALL_ENEMIES:target));
            assert(def.usage==usage.at(row.at("usageName").get<std::string>()));
            assert(def.combatGen==row.at("canBeGeneratedInCombat").get<bool>());
        }
        assert(found==1); ++checked;
    }
    assert(checked==static_cast<int>(PotionId::COUNT)-1);
    // These Ancient relics remain supported after correcting their pool metadata.
    assert(relic_implemented(RelicId::FRESNEL_LENS));
    assert(relic_implemented(RelicId::LOOMING_FRUIT));
    assert(relic_implemented(RelicId::VERY_HOT_COCOA));
}
