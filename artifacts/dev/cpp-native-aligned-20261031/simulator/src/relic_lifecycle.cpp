#include "sts2/relics.h"

namespace sts2 {

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
    // Native ToyBox.AfterCombatEnd (after victory hooks) counts completed
    // combats and melts the first still-active wax relic in inventory order.
    if (!run_has_relic(rc, RelicId::TOY_BOX) || rc.toyBoxCombats >= 15) return;
    ++rc.toyBoxCombats;
    if (rc.toyBoxCombats % 3 != 0) return;
    for (int i = 0; i < rc.relicCount; ++i) {
        if (!rc.relicWax[i] || rc.relicMelted[i]) continue;
        // Player.MeltRelicInternal retains the physical relic and saved state.
        // Hook enumeration excludes IsMelted. No target RelicModel overrides
        // AfterRemoved, so this transition has no extra removal-side effects.
        rc.relicMelted[i] = true;
        return;
    }
}

} // namespace sts2
