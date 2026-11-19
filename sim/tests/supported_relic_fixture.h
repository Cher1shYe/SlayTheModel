#pragma once
// Deterministic test input for contracts about prices, selection, rewards or
// snapshots. This deliberately is NOT a native/random relic-pool fixture;
// native_relic_pool_alignment separately checks the complete native pools and
// explicit unsupported boundary. No RNG is consumed and no seed is changed.
#include "sts2/run.h"
#include "sts2/relics.h"
#include "sts2/relic_raw_rarity.h"
#include <cassert>

inline void use_supported_relic_fixture(sts2::RunContext &run) {
    using namespace sts2;
    static constexpr RelicId ids[] = {
        RelicId::AMETHYST_AUBERGINE, RelicId::ANCHOR, RelicId::BAG_OF_PREPARATION, RelicId::BLOOD_VIAL,
        RelicId::BRONZE_SCALES, RelicId::CENTENNIAL_PUZZLE, RelicId::LANTERN,
        RelicId::MEAL_TICKET, RelicId::ODDLY_SMOOTH_STONE, RelicId::POTION_BELT,
        RelicId::REGAL_PILLOW, RelicId::STRAWBERRY, RelicId::VAJRA,
        RelicId::WAR_PAINT, RelicId::WHETSTONE,
        RelicId::AKABEKO, RelicId::BAG_OF_MARBLES, RelicId::BELLOWS,
        RelicId::BOWLER_HAT, RelicId::ETERNAL_FEATHER, RelicId::GREMLIN_HORN,
        RelicId::LETTER_OPENER, RelicId::LUCKY_FYSH, RelicId::NUNCHAKU,
        RelicId::ORICHALCUM, RelicId::PEAR, RelicId::PEN_NIB,
        RelicId::ART_OF_WAR, RelicId::CAPTAINS_WHEEL, RelicId::FROZEN_EGG,
        RelicId::GIRYA, RelicId::SHOVEL, RelicId::ICE_CREAM, RelicId::KUNAI,
        RelicId::LIZARD_TAIL, RelicId::MANGO, RelicId::MOLTEN_EGG,
        RelicId::MUMMIFIED_HAND, RelicId::OLD_COIN, RelicId::POCKETWATCH,
        RelicId::SHURIKEN, RelicId::THE_COURIER, RelicId::TOXIC_EGG,
        RelicId::TUNGSTEN_ROD, RelicId::WHITE_BEAST_STATUE,
        RelicId::CAULDRON, RelicId::CHEMICAL_X, RelicId::DINGY_RUG,
        RelicId::LAVA_LAMP, RelicId::LEES_WAFFLE, RelicId::MEMBERSHIP_CARD,
        RelicId::THE_ABACUS, RelicId::TOOLBOX
    };
    run.playerRelicBag = RelicBagState{};
    run.sharedRelicBag = RelicBagState{};
    for (RelicId id : ids) {
        assert(relic_implemented(id) && relic_def(id).pool == RelicPool::SHARED);
        const int slot = relic_raw_rarity(id) - 1;
        assert(slot >= 0 && slot < RELIC_BAG_SLOTS);
        if (!relic_epoch_unlocked(run.nativeProgress.revealedEpochs, id) || run_has_relic(run, id)) continue;
        for (auto *bag : {&run.playerRelicBag, &run.sharedRelicBag})
            bag->entries[slot][bag->counts[slot]++] = static_cast<std::uint16_t>(id);
    }
    run.relicBagsInitialized = true;
}
