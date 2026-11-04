#pragma once
#include "sts2/run.h"

namespace sts2 {
// Starts Lead/Sea's genuine optional choice, or obtains Arcane's single card.
bool begin_relic_card_choice(RunContext &rc, RelicId source);
// Generate native ordered, distinct candidate sets, applying reward hooks.
// Returns 2 for Lead Paperweight, 1 for Arcane Scroll, 3 for Dream Catcher,
// or 15 for Sea Glass. Sea Glass's configured character pool is explicit.
// Returns -1 without mutating the run if source/pool/capacity is unsupported.
// Only candidate generation is performed: the caller must preserve selection,
// skipping, and the original screen's continuation.
int make_relic_card_reward_candidates(RunContext &rc, RelicId source,
                                     Card *out, int capacity,
                                     CardPool seaPool = CardPool::IRONCLAD);
// Darv calls setup while constructing the visible Dusty Tome option; store
// this identity with the option/relic, then pass the same identity on obtain.
CardId prepare_dusty_tome_card(RunContext &rc);
bool obtain_dusty_tome_card(RunContext &rc, CardId prepared);
// HeftyTablet.AfterObtained: three distinct Rare cards from the character
// pool (Uniform odds, NoUpgradeRoll), then an optional choose-one screen.
int make_hefty_tablet_candidates(RunContext &rc, Card *out, int capacity);
// Kaleidoscope.AfterObtained: two CardRewards of three cards from distinct
// non-character pools (StableShuffle by Rng.Niche, RegularEncounter odds).
bool queue_kaleidoscope_rewards(RunContext &rc);
// Hook.TryModifyCardRewardOptions relic pass (Eggs, Fresnel Lens, Glitter,
// Silken Tress, Silver Crucible) for non-kaleidoscope reward generation.
void apply_card_reward_hooks(RunContext &rc, Card *cards, int count,
                             bool isCardReward);
}
