#include "sts2/relics.h"

namespace sts2 {
namespace {
// FishingRod checks Encounter.RoomType, not the map node containing a fight:
// event fights such as the Battleworn Dummy still count as Monster rooms.
bool fishing_rod_monster_encounter(Encounter encounter) {
    switch (encounter) {
        case Encounter::INVALID:
        case Encounter::SETUP_BYGONE_EFFIGY_ELITE:
        case Encounter::SETUP_BYRDONIS_ELITE:
        case Encounter::SETUP_DECIMILLIPEDE_ELITE:
        case Encounter::SETUP_ENTOMANCER_ELITE:
        case Encounter::SETUP_INFESTED_PRISMS_ELITE:
        case Encounter::SETUP_KNIGHTS_ELITE:
        case Encounter::SETUP_MECHA_KNIGHT_ELITE:
        case Encounter::SETUP_PHANTASMAL_GARDENERS_ELITE:
        case Encounter::SETUP_PHROG_PARASITE_ELITE:
        case Encounter::SETUP_SKULKING_COLONY_ELITE:
        case Encounter::SETUP_SOUL_NEXUS_ELITE:
        case Encounter::SETUP_TERROR_EEL_ELITE:
        case Encounter::SETUP_AEONGLASS_BOSS:
        case Encounter::SETUP_CEREMONIAL_BEAST_BOSS:
        case Encounter::SETUP_KAISER_CRAB_BOSS:
        case Encounter::SETUP_KNOWLEDGE_DEMON_BOSS:
        case Encounter::SETUP_LAGAVULIN_MATRIARCH_BOSS:
        case Encounter::SETUP_QUEEN_BOSS:
        case Encounter::SETUP_SOUL_FYSH_BOSS:
        case Encounter::SETUP_TEST_SUBJECT_BOSS:
        case Encounter::SETUP_THE_INSATIABLE_BOSS:
        case Encounter::SETUP_THE_KIN_BOSS:
        case Encounter::SETUP_VANTOM_BOSS:
        case Encounter::SETUP_WATERFALL_GIANT_BOSS:
            return false;
        default: return true;
    }
}
}

void relics_resume_lifecycle(RunContext &rc) {
    // LargeCapsule awaits each Obtain, including any choices/rewards it opens,
    // before consuming the next rarity draw or adding the two basic cards.
    if (!rc.largeCapsuleCardsPending || rc.cardGrid.kind || rc.deferredCustomRewards) return;
    while (rc.largeCapsuleRelicsRemaining > 0) {
        const float roll = rc.playerRng[PRNG_REWARDS].next_float();
        const Rarity rarity = roll < 0.5f ? Rarity::COMMON :
                              (roll < 0.83f ? Rarity::UNCOMMON : Rarity::RARE);
        const RelicId next = rc.pull_relic(rarity);
        --rc.largeCapsuleRelicsRemaining;
        bool obtained = false;
        {
            // Do not consume the child's deferred-reward marker in add_relic.
            // The outer acquisition/action activates that reward screen once
            // this continuation has paused. An existing parent reward screen
            // alone is not a reason to delay the capsule's immediate effects.
            struct NestedObtainGuard {
                RunContext &run; bool previous;
                explicit NestedObtainGuard(RunContext &r) : run(r), previous(r.processingAction) { run.processingAction = true; }
                ~NestedObtainGuard() { run.processingAction = previous; }
            } guard(rc);
            obtained = rc.add_relic(next);
        }
        if (!obtained) throw std::logic_error("Large Capsule obtain cannot complete");
        if (rc.cardGrid.kind || rc.deferredCustomRewards) return;
    }
    rc.largeCapsuleCardsPending = false;
    for (CardId id : {CardId::STRIKE_IRONCLAD, CardId::DEFEND_IRONCLAD})
        if (!rc.add_card_to_deck(rc.make_run_card(id, false)))
            throw std::logic_error("Large Capsule basic-card storage exhausted");
}

void relics_after_combat_end_lifecycle(RunContext &rc) {
    // Native IterateHookListeners snapshots non-melted relics before dispatch,
    // then Contains checks removal rather than IsMelted. A relic melted by Toy
    // Box during this dispatch therefore still gets its final hook this time.
    bool active[MAX_RELICS]{};
    for (int slot = 0; slot < rc.relicCount; ++slot)
        active[slot] = run_relic_active_at(rc, slot);
    for (int slot = 0; slot < rc.relicCount; ++slot) {
        if (!active[slot]) continue;
        const auto id = static_cast<RelicId>(rc.relics[slot]);
        if (id == RelicId::FISHING_ROD && fishing_rod_monster_encounter(rc.battle.encounter)) {
            ++rc.relicAux[slot];
            if (rc.relicAux[slot] % 3 != 0) continue;
            int candidates[MAX_DECK], count = 0;
            for (int i = 0; i < rc.deckCount; ++i)
                if (card_upgradable(rc.deck[i])) candidates[count++] = i;
            // Rng.NextItem returns null without a draw for an empty list.
            if (count > 0)
                card_apply_upgrade(rc.deck[candidates[rc.runRng[RNG_NICHE].next_int(0, count - 1)]]);
        } else if (id == RelicId::TOY_BOX && rc.toyBoxCombats < 15) {
            ++rc.toyBoxCombats;
            if (rc.toyBoxCombats % 3 != 0) continue;
            for (int i = 0; i < rc.relicCount; ++i) {
                if (!rc.relicWax[i] || rc.relicMelted[i]) continue;
                // Melting retains the physical relic and saved state.
                rc.relicMelted[i] = true;
                break;
            }
        }
    }
}

} // namespace sts2
