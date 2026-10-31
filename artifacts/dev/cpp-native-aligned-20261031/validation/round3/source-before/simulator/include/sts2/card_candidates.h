#pragma once
#include "sts2/run.h"

namespace sts2 {
// Reference non-combat reward creation: distinct candidates, no upgrade roll,
// base rarity odds without changing the run's combat-reward rarity offset.
int make_noncombat_card_candidates(RunContext &rc, Card *out, int count,
                                   CardPool pool, bool commonOnly);
bool card_can_transform_from_deck(const Card &card);
bool card_eligible_for_deck_choice(const Card &card, int kind);
void native_sort_card_indices(const RunContext &rc, int *indices, int count);
bool transform_basic_strikes_and_defends(RunContext &rc);
Card make_maul_transformation(RunContext &rc, const Card &original);
bool begin_card_grid(RunContext &rc, int kind);
bool begin_deck_relic_choice(RunContext &rc, int kind, int count,
                             int damageAfter = 0, CardId curseAfter = CardId::INVALID);
bool can_begin_deck_relic_choice(const RunContext &rc, int kind, int count,
                                CardId curseAfter = CardId::INVALID);
bool can_generate_scroll_boxes(const RunContext &rc);
bool card_grid_can_select(const RunContext &rc, int index);
bool select_card_grid(RunContext &rc, int index);
bool confirm_card_grid(RunContext &rc);
bool cancel_card_grid_preview(RunContext &rc);
bool card_grid_valid(const RunContext &rc);
}
