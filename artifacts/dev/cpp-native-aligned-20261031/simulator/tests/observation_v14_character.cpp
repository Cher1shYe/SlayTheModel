// v14 public combat observation: character-state tail, widened choice-op
// one-hot and the new card instance fields.
#include "sts2/observe.h"
#include <iostream>
#include <memory>

using namespace sts2;

namespace {
int failures = 0;
void check(bool ok, const char *label) {
    if (!ok) { ++failures; std::cerr << "FAIL " << label << '\n'; }
}
}  // namespace

int main() {
    auto b = std::make_unique<BattleContext>();
    b->characterPool = CardPool::DEFECT;
    b->defect.orbCapacity = 3;
    b->defect.orbCount = 2;
    b->defect.orbs[0] = {OrbId::LIGHTNING, 0};
    b->defect.orbs[1] = {OrbId::DARK, 14};
    b->necro.ostyPresent = true;
    b->necro.ostyHp = 25;
    b->regent.stars = 3;
    const auto obs = public_combat_observation(*b);
    check(static_cast<int>(obs.size()) == PUBLIC_COMBAT_OBS_DIM, "dimension");
    const std::size_t t = obs.size() - PUB_CHARACTER_FEAT;
    // Character one-hot: IRONCLAD, SILENT, DEFECT, NECROBINDER, REGENT.
    check(obs[t + 2] == 1.0f && obs[t] == 0.0f, "character one-hot");
    const std::size_t orbs = t + PUB_CHARACTER_N + 2;
    check(obs[t + PUB_CHARACTER_N] == 0.3f, "orb capacity");
    check(obs[orbs + static_cast<int>(OrbId::LIGHTNING)] == 1.0f, "orb 0 type");
    check(obs[orbs + PUB_ORB_FEAT + static_cast<int>(OrbId::DARK)] == 1.0f, "orb 1 type");
    check(obs[orbs + PUB_ORB_FEAT + PUB_ORB_FEAT - 1] == 1.4f, "orb 1 value");
    check(obs[orbs + 2 * PUB_ORB_FEAT] == 1.0f, "empty slot encodes NONE");
    const std::size_t necro = t + PUB_CHARACTER_N + 2 + MAX_ORBS * PUB_ORB_FEAT + 5;
    check(obs[necro] == 1.0f && obs[necro + 1] == 0.5f, "Osty present and hp");
    check(obs[necro + 12] == 0.3f, "regent stars");

    // Every encoded character field must change the observation.
    auto differs = [&](auto mutate) {
        auto copy = std::make_unique<BattleContext>(*b);
        mutate(*copy);
        return public_combat_observation(*copy) != obs;
    };
    check(differs([](BattleContext &c) { c.defect.orbs[0].id = OrbId::FROST; }), "orb type distinct");
    check(differs([](BattleContext &c) { c.necro.ostyStrength = 2; }), "Osty strength distinct");
    check(differs([](BattleContext &c) { c.regent.hitsGivenThisTurn[3] = 1; }), "regent hits distinct");
    check(differs([](BattleContext &c) { c.silent.discardedThisTurn = 1; }), "silent discards distinct");

    // Character selectors appended after DISCARD_ANY are distinguishable.
    check(PUB_CHOICE_OP_N == static_cast<int>(ChoiceOp::REGENT_AUTO_SKILL) + 1, "choice op width");

    // New card fields reach both card encodings.
    Card base = make_card(CardId::STRIKE_IRONCLAD, false, 1);
    const auto f0 = card_features(base);
    check(static_cast<int>(f0.size()) == CARD_FEAT_DIM, "card feature dimension");
    for (int field = 0; field < 4; ++field) {
        Card c = base;
        if (field == 0) c.bonusBlock = 3;
        if (field == 1) c.retainThisTurn = true;
        if (field == 2) c.slyThisTurn = true;
        if (field == 3) c.slyThisCombat = true;
        check(card_features(c) != f0, "card feature field distinct");
    }
    std::cout << "observation v14 character: failures=" << failures << '\n';
    return failures ? 1 : 0;
}
