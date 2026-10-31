#include "sts2/battle.h"
#include "sts2/defect.h"
#include <nlohmann/json.hpp>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <memory>
#include <map>

using namespace sts2;
using nlohmann::json;
namespace {
int checks = 0, failures = 0;
std::string context;
void check(bool condition, const std::string &label) {
    ++checks;
    if (!condition) {++failures; std::cerr << context << ": " << label << '\n';}
}
CardId card_id(const std::string &key) {
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i)
        if (key == card_key(static_cast<CardId>(i))) return static_cast<CardId>(i);
    throw std::runtime_error("Unknown fixture card " + key);
}
PowerId power_id(const std::string &key) {
#include "../../native-round4-step2-defect-fixtures/power_map.inc"
    throw std::runtime_error("Unknown fixture power " + key);
}
OrbId orb_id(const std::string &key) {
    if (key == "LIGHTNING_ORB") return OrbId::LIGHTNING;
    if (key == "FROST_ORB") return OrbId::FROST;
    if (key == "DARK_ORB") return OrbId::DARK;
    if (key == "PLASMA_ORB") return OrbId::PLASMA;
    if (key == "GLASS_ORB") return OrbId::GLASS;
    throw std::runtime_error("Unknown fixture orb " + key);
}
void load_pile(BattleContext &b, Card *pile, int &count, const json &cards, bool reverse = false) {
    count = 0;
    for (const auto &row : cards) {
        Card c = make_card(card_id(row["id"]), row["upgraded"], b.require_card_uid());
        c.bonusDamage = row["damage"].get<double>() - card_base_damage(c);
        c.bonusBlock = row["block"].get<int>() - card_block(c);
        pile[count++] = c;
    }
    if (reverse) std::reverse(pile, pile + count);
}
std::unique_ptr<BattleContext> setup(const json &state) {
    auto ptr = std::make_unique<BattleContext>(); auto &b = *ptr;
    b.player.hp = state["hp"]; b.player.maxHp = 80; b.player.block = state["block"]; b.player.energy = state["energy"];
    b.turn = 1; b.characterPool = CardPool::IRONCLAD; b.nextUid = 1;
    b.monsterCount = state["enemies"].size();
    for (int i = 0; i < b.monsterCount; ++i) {
        auto &m = b.monsters[i]; m.id = MonsterId::CALCIFIED_CULTIST; m.hp = state["enemies"][i]["hp"];
        m.maxHp = 10000; m.block = state["enemies"][i]["block"]; m.alive = true; m.intentType = 0;
        for (const auto &p : state["enemies"][i]["powers"]) b.add_monster_power(i, power_id(p["id"]), p["amount"]);
    }
    load_pile(b, b.hand, b.handCount, state["hand"]);
    load_pile(b, b.draw, b.drawCount, state["draw"], true);
    load_pile(b, b.discard, b.discardCount, state["discard"]);
    load_pile(b, b.exhaust, b.exhaustCount, state["exhaust"]);
    for (const auto &p : state["powers"]) b.add_player_power(power_id(p["id"]), p["amount"]);
    b.defect.orbCapacity = state["capacity"];
    for (const auto &orb : state["orbs"]) {
        const auto id = orb_id(orb["id"]); int value = 0;
        if (id == OrbId::DARK) value = orb["evoke"];
        if (id == OrbId::GLASS) value = 4;
        b.defect.orbs[b.defect.orbCount++] = {id,value};
        if (id == OrbId::LIGHTNING) ++b.defect.lightningChanneled;
    }
    b.targetRng = Rng(42); b.shuffleRng = Rng(42); b.cardGenerationRng = Rng(42); b.orbRng = Rng(42);
    return ptr;
}
void check_pile(const BattleContext &b, const Card *pile, int count, const json &cards,
                const char *name, bool reverse = false) {
    check(count == static_cast<int>(cards.size()), std::string(name) + " count expected=" + std::to_string(cards.size()) + " actual=" + std::to_string(count));
    for (int i = 0; i < std::min(count, static_cast<int>(cards.size())); ++i) {
        const Card &c = pile[reverse ? count - 1 - i : i]; const auto &row = cards[i];
        const std::string label = std::string(name) + "[" + std::to_string(i) + "]";
        check(c.id == card_id(row["id"]), label + " id expected=" + row["id"].get<std::string>() + " actual=" + card_key(c.id));
        check(c.upgraded == row["upgraded"], label + " upgraded");
        int cost = card_cost(c);
        if (std::string(name) == "hand" && card_is_power(c) && b.player_power(PowerId::FREE_POWER) > 0) cost = 0;
        check(cost == row["cost"], label + " cost expected=" + row["cost"].dump() + " actual=" + std::to_string(cost));
        check(card_base_damage(c) == row["damage"], label + " damage");
        check(card_block(c) == row["block"], label + " block");
    }
}
void verify(const BattleContext &b, const json &state) {
    check(b.player.hp == state["hp"], "hp"); check(b.player.block == state["block"], "block expected="+state["block"].dump()+" actual="+std::to_string(b.player.block));
    check(b.player.energy == state["energy"], "energy expected="+state["energy"].dump()+" actual="+std::to_string(b.player.energy));
    int expectedPowers[static_cast<int>(PowerId::COUNT)]{};
    for (const auto &p : state["powers"]) expectedPowers[static_cast<int>(power_id(p["id"]))] = p["amount"];
    for (int i = 0; i < static_cast<int>(PowerId::COUNT); ++i)
        check(b.player_power(static_cast<PowerId>(i)) == expectedPowers[i], "power " + std::to_string(i) + " expected=" + std::to_string(expectedPowers[i]) + " actual=" + std::to_string(b.player_power(static_cast<PowerId>(i))));
    for (int i = 0; i < b.monsterCount; ++i) {
        check(b.monsters[i].hp == state["enemies"][i]["hp"], "enemy " + std::to_string(i) + " hp expected=" + state["enemies"][i]["hp"].dump() + " actual=" + std::to_string(b.monsters[i].hp));
        int expected[static_cast<int>(PowerId::COUNT)]{};
        for (const auto &p : state["enemies"][i]["powers"]) expected[static_cast<int>(power_id(p["id"]))] = p["amount"];
        for (int j = 0; j < static_cast<int>(PowerId::COUNT); ++j)
            check(b.monster_power(i,static_cast<PowerId>(j)) == expected[j], "enemy " + std::to_string(i) + " power " + std::to_string(j));
    }
    check_pile(b,b.hand,b.handCount,state["hand"],"hand"); check_pile(b,b.draw,b.drawCount,state["draw"],"draw",true);
    check_pile(b,b.discard,b.discardCount,state["discard"],"discard"); check_pile(b,b.exhaust,b.exhaustCount,state["exhaust"],"exhaust");
    check(b.defect.orbCapacity == state["capacity"], "orb capacity");
    check(b.defect.orbCount == static_cast<int>(state["orbs"].size()), "orb count");
    for (int i = 0; i < std::min(b.defect.orbCount, static_cast<int>(state["orbs"].size())); ++i) {
        const auto &orb = b.defect.orbs[i]; const auto &expected = state["orbs"][i];
        check(orb.id == orb_id(expected["id"]), "orb " + std::to_string(i) + " type");
        int passive = orb.id == OrbId::LIGHTNING ? 3 : orb.id == OrbId::FROST ? 2 : orb.id == OrbId::DARK ? 6 : orb.id == OrbId::GLASS ? orb.value : 1;
        if (orb.id != OrbId::PLASMA) passive = std::max(0,passive + b.player_power(PowerId::FOCUS));
        int evoke = orb.id == OrbId::LIGHTNING ? std::max(0,8+b.player_power(PowerId::FOCUS)) : orb.id == OrbId::FROST ? std::max(0,5+b.player_power(PowerId::FOCUS)) : orb.id == OrbId::DARK ? orb.value : orb.id == OrbId::GLASS ? passive*2 : 2;
        check(passive == expected["passive"], "orb passive"); check(evoke == expected["evoke"], "orb evoke");
    }
    check(b.targetRng.counter == state["targets"], "target RNG expected=" + state["targets"].dump() + " actual=" + std::to_string(b.targetRng.counter));
    check(b.shuffleRng.counter == state["shuffle"], "shuffle RNG"); check(b.cardGenerationRng.counter == state["cardgen"], "cardgen RNG"); check(b.orbRng.counter == state["orbgen"], "orbgen RNG");
}
}
int main() {
    const auto path = std::filesystem::path(__FILE__).parent_path().parent_path().parent_path()/"native-round4-step2-defect-fixtures/results.json";
    std::ifstream f(path); json data; f >> data;
    check(data["status"] == "completed" && data["gameAssemblySha256"] == "9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4", "target fixture identity");
    int cases = 0;
    for (const auto &row : data["results"]) {
        ++cases; auto ptr = setup(row["before"]); auto &b = *ptr;
        if (row["test"] == "card") {
            context = row["id"].get<std::string>() + (row["upgraded"].get<bool>() ? "+" : "");
            int index = 0; while (index < b.handCount && b.hand[index].id != card_id(row["id"])) ++index;
            check(index < b.handCount && b.play_card(index,0), "play accepted");
            int choices = 0;
            while (b.pending.op != ChoiceOp::NONE && choices < 20) {
                check(choices < static_cast<int>(row["choices"].size()), "unexpected choice");
                if (choices >= static_cast<int>(row["choices"].size())) break;
                const auto &expected = row["choices"][choices++];
                check(b.pending.count == static_cast<int>(expected["candidates"].size()), "choice candidate count");
                for (int i = 0; i < std::min(b.pending.count,static_cast<int>(expected["candidates"].size())); ++i)
                    check(b.pending.cards[i].id == card_id(expected["candidates"][i]), "choice candidate order");
                const std::uint16_t uid = b.pending.cards[0].uid;
                b.resolve_choice(uid);
            }
            check(choices == static_cast<int>(row["choices"].size()), "choice count"); verify(b,row["after"]);
        } else if (row["test"] == "orbs") {
            context = "orbs focus=" + row["focus"].dump();
            for (const auto &entry : row["transitions"]) {
                if (entry["operation"] == "passive") {
                    int index = 0; while (index < b.defect.orbCount && b.defect.orbs[index].id != orb_id(entry["orb"])) ++index;
                    defect_orb_passive(b,index);
                } else defect_evoke(b,0,entry["operation"] != "evoke_first_keep");
                verify(b,entry["state"]);
            }
        }
    }
    std::cout << "Defect: " << cases << " DLL fixtures, " << checks << " checks, " << failures << " failures\n";
    return failures ? 1 : 0;
}
