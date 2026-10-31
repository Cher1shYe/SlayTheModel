#include "sts2/run.h"
#include "sts2/relics.h"
#include "sts2/relic_raw_rarity.h"

#include <algorithm>
#include <iostream>
#include <memory>
#include <vector>

using namespace sts2;
namespace {
int checks = 0, failures = 0;
void check(const char *name, bool ok) {
    ++checks;
    failures += !ok;
    if (!ok) std::cerr << name << " FAIL\n";
}
std::unique_ptr<RunContext> base() {
    auto r = std::make_unique<RunContext>();
    r->init(147, 0);
    r->screen = RunScreen::SHOP;
    r->relicCount = 0;
    std::fill(std::begin(r->relics), std::end(r->relics), 0);
    std::fill(std::begin(r->relicAux), std::end(r->relicAux), 0);
    r->hp = r->maxHp = 80;
    return r;
}
struct NativeRelicReplacementCase {
    const char *name;
    RelicId before[4];
    int beforeAux[4];
    RelicId after[5];
    int afterAux[5];
};
#include "../../native-round4-step1-relic-fixtures/replacement_cases.inc"
bool bag_contains(const RelicBagState &bag, RelicId id) {
    for (int slot = 0; slot < RELIC_BAG_SLOTS; ++slot)
        for (int i = 0; i < bag.counts[slot]; ++i)
            if (bag.entries[slot][i] == static_cast<int>(id)) return true;
    return false;
}
}

int main() {
    for (const auto &fixture : nativeReplacementCases) {
        auto owned = base(); auto &r = *owned;
        r.relicCount = 4;
        for (int i = 0; i < 4; ++i) {
            r.relics[i] = static_cast<int>(fixture.before[i]);
            r.relicAux[i] = fixture.beforeAux[i];
            if (relic_raw_rarity(fixture.before[i]) == static_cast<int>(RelicRawRarity::STARTER))
                r.relicAux[i] = 91; // synthetic stale state must not survive replacement
        }
        r.relicAux[4] = 89; // a fresh Touch must not inherit an unused slot's counter
        std::uint64_t runCounters[RNG_COUNT], playerCounters[PRNG_COUNT];
        for (int i = 0; i < RNG_COUNT; ++i) runCounters[i] = r.runRng[i].counter;
        for (int i = 0; i < PRNG_COUNT; ++i) playerCounters[i] = r.playerRng[i].counter;
        check(fixture.name, r.add_relic(RelicId::TOUCH_OF_OROBAS));
        check("Touch appends only itself", r.relicCount == 5);
        for (int i = 0; i < 5; ++i) {
            check("Native ordered replacement identity", r.relics[i] == static_cast<int>(fixture.after[i]));
            check("Native sibling counters and new state", r.relicAux[i] == fixture.afterAux[i]);
        }
        for (int i = 0; i < RNG_COUNT; ++i) check("No run RNG consumed", r.runRng[i].counter == runCounters[i]);
        for (int i = 0; i < PRNG_COUNT; ++i) check("No player RNG consumed", r.playerRng[i].counter == playerCounters[i]);
        check("Ordinary starter refinement does not change HP", r.hp == 80 && r.maxHp == 80);

        auto clone = std::make_unique<RunContext>(r);
        clone->relicAux[0] += 1;
        check("Clone relic counters are independent", clone->relicAux[0] == r.relicAux[0] + 1);
        auto restored = std::make_unique<RunContext>();
        check("Replacement snapshot restores", RunContext::restore(r.serialize(), *restored));
        check("Replacement snapshot preserves state", restored->serialize() == r.serialize());
    }
    {
        auto owned = base(); auto &r = *owned;
        r.add_relic(RelicId::PEN_NIB); r.add_relic(RelicId::BLACK_BLOOD); r.add_relic(RelicId::BURNING_BLOOD);
        check("First Starter fallback obtains", r.add_relic(RelicId::TOUCH_OF_OROBAS));
        check("BlackBlood is the first Starter and refines to Circlet", r.relics[1] == static_cast<int>(RelicId::CIRCLET));
        check("Later BurningBlood remains in place", r.relics[2] == static_cast<int>(RelicId::BURNING_BLOOD));
    }
    for (bool queued : {false, true}) {
        auto owned = base(); auto &r = *owned;
        r.add_relic(RelicId::PEN_NIB);
        if (queued) r.cardGrid.kind = 6;
        const auto before = r.serialize();
        check("Missing Starter is unavailable before queueing", !r.add_relic(RelicId::TOUCH_OF_OROBAS));
        check("Missing Starter rejection is atomic", r.serialize() == before);
    }
    {
        auto owned = base(); auto &r = *owned;
        r.add_relic(RelicId::PEN_NIB); r.add_relic(RelicId::BURNING_BLOOD); r.add_relic(RelicId::HAPPY_FLOWER);
        r.hp = 30; r.relicAux[0] = 7; r.relicAux[1] = 91; r.relicAux[2] = 2;
        check("Replacement traverses obtain hook", r.replace_starter_relic(1, RelicId::STRAWBERRY));
        check("Native Strawberry acquisition HP effect", r.hp == 37 && r.maxHp == 87);
        check("Replacement obtains at original index", r.relicCount == 3 && r.relics[1] == static_cast<int>(RelicId::STRAWBERRY));
        check("Replacement resets only original state", r.relicAux[0] == 7 && r.relicAux[1] == 0 && r.relicAux[2] == 2);
        check("Replacement removes obtained relic from both bags", !bag_contains(r.playerRelicBag, RelicId::STRAWBERRY) && !bag_contains(r.sharedRelicBag, RelicId::STRAWBERRY));
        const auto before = r.serialize();
        check("Helper rejects non-Starter source", !r.replace_starter_relic(1, RelicId::PEAR));
        check("Helper invalid index rejects", !r.replace_starter_relic(-1, RelicId::PEAR));
        check("Rejected replacements are atomic", r.serialize() == before);
    }
    {
        auto owned = base(); auto &r = *owned;
        r.relicCount = MAX_RELICS - 1;
        std::fill(std::begin(r.relics), std::end(r.relics), static_cast<int>(RelicId::CIRCLET));
        r.relics[3] = static_cast<int>(RelicId::BURNING_BLOOD);
        check("Full-after-Touch inventory replaces without extra capacity", r.add_relic(RelicId::TOUCH_OF_OROBAS));
        check("Full inventory replacement retains index and count", r.relicCount == MAX_RELICS && r.relics[3] == static_cast<int>(RelicId::BLACK_BLOOD));
    }
    {
        auto owned = base(); auto &r = *owned;
        r.add_relic(RelicId::PEN_NIB); r.add_relic(RelicId::BURNING_BLOOD);
        r.add_relic(RelicId::HAPPY_FLOWER); r.add_relic(RelicId::LIZARD_TAIL);
        r.relicAux[0] = 7; r.relicAux[2] = 1; r.relicAux[3] = 1;
        r.add_relic(RelicId::TOUCH_OF_OROBAS);
        r.begin_combat(Encounter::INVALID);
        check("Combat preserves PenNib association", r.battle.relics[0] == static_cast<int>(RelicId::PEN_NIB) && r.battle.relicAux[0] == 7);
        check("Combat advances the correct HappyFlower counter", r.battle.relics[2] == static_cast<int>(RelicId::HAPPY_FLOWER) && r.battle.relicAux[2] == 2);
        check("Combat preserves used LizardTail state", r.battle.relics[3] == static_cast<int>(RelicId::LIZARD_TAIL) && r.battle.relicAux[3] == 1);
        r.sync_relics_from_battle();
        check("Combat-to-run counters remain aligned", r.relicAux[0] == 7 && r.relicAux[2] == 2 && r.relicAux[3] == 1);
    }
    // Toy Box's overall native rule is still unsupported. This checks only the
    // shared ID/counter storage invariant of its existing deletion path.
    for (std::uint64_t seed : {0, 42, 123}) {
        auto owned = base(); auto &r = *owned;
        const RelicId ids[] = {RelicId::BURNING_BLOOD, RelicId::PEN_NIB, RelicId::HAPPY_FLOWER, RelicId::LIZARD_TAIL, RelicId::TOY_BOX};
        const int aux[] = {0, 7, 2, 1, 0};
        r.relicCount = 5; r.toyBoxCombats = 2; r.runRng[RNG_NICHE] = Rng(seed);
        for (int i = 0; i < 5; ++i) { r.relics[i] = static_cast<int>(ids[i]); r.relicAux[i] = aux[i]; }
        auto expectedRng = r.runRng[RNG_NICHE]; const int drop = 1 + expectedRng.next_int(0, 2);
        relics_combat_end(r, true, false);
        check("Existing deletion changes count once", r.relicCount == 4);
        for (int i = 0, j = 0; i < 5; ++i) if (i != drop) {
            check("Deletion retains surviving ID/counter pairs", r.relics[j] == static_cast<int>(ids[i]) && r.relicAux[j] == aux[i]); ++j;
        }
        check("Deletion clears unused slot", r.relics[4] == 0 && r.relicAux[4] == 0);
        check("Storage fix adds no RNG draws", r.runRng[RNG_NICHE].counter == expectedRng.counter);
        r.relicAux[4] = 99;
        check("New acquisition resets stale unused state", r.add_relic(RelicId::ANCHOR) && r.relicAux[4] == 0);
    }
    std::cout << "native step1 relic replacement: " << checks << " checks, " << failures << " failures\n";
    return failures ? 1 : 0;
}
