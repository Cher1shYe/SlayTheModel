#include "sts2/card_candidates.h"
#include "sts2/relics.h"

namespace sts2 {
bool card_can_transform_from_deck(const Card &card) {
    // These are the Eternal cards in the bundled single-player card data.
    switch (card.id) {
        case CardId::INVALID:
        case CardId::ASCENDERS_BANE:
        case CardId::BAD_LUCK:
        case CardId::CURSE_OF_THE_BELL:
        case CardId::ENTHRALLED:
        case CardId::FOLLY:
        case CardId::GREED: return false;
        default: return true;
    }
}

Card make_maul_transformation(RunContext &rc, const Card &original) {
    Card replacement = rc.make_run_card(CardId::MAUL, original.upgraded);
    if (original.enchantment != EnchantmentId::NONE)
        card_apply_enchantment(replacement, original.enchantment, original.enchantmentAmount);
    return replacement;
}

int make_noncombat_card_candidates(RunContext &rc, Card *out, int count,
                                   CardPool pool, bool commonOnly) {
    Rng &rng = rc.playerRng[PRNG_REWARDS];
    int made = 0;
    while (made < count) {
        CardId candidates[static_cast<int>(CardId::COUNT)];
        int total = 0;
        for (int id = 1; id < static_cast<int>(CardId::COUNT); ++id) {
            const CardDef &d = card_def(static_cast<CardId>(id));
            if (d.pool != pool || (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY))) continue;
            if (d.rarity != Rarity::COMMON && d.rarity != Rarity::UNCOMMON && d.rarity != Rarity::RARE) continue;
            if (commonOnly && d.rarity != Rarity::COMMON) continue;
            bool used = false;
            for (int i = 0; i < made; ++i) used |= out[i].id == d.id;
            if (!used) candidates[total++] = d.id;
        }
        if (!total) break;
        Rarity rarity = Rarity::COMMON;
        if (!commonOnly) {
            // RollWithBaseOdds checks uncommon against the absolute threshold.
            const float u = rng.next_float();
            const float rare = rc.ascension >= 7 ? 0.0149f : 0.03f;
            rarity = u < rare ? Rarity::RARE : u < 0.37f ? Rarity::UNCOMMON : Rarity::COMMON;
            for (;;) {
                bool present = false;
                for (int i = 0; i < total; ++i) present |= card_def(candidates[i]).rarity == rarity;
                if (present) break;
                if (rarity == Rarity::COMMON) rarity = Rarity::UNCOMMON;
                else if (rarity == Rarity::UNCOMMON) rarity = Rarity::RARE;
                else return made;
            }
            int kept = 0;
            for (int i = 0; i < total; ++i)
                if (card_def(candidates[i]).rarity == rarity) candidates[kept++] = candidates[i];
            total = kept;
        }
        out[made++] = rc.make_run_card(candidates[rng.next_int(0, total - 1)], false);
    }
    return made;
}

bool can_generate_scroll_boxes(const RunContext &rc) {
    if (rc.cardGrid.kind) return false;
    const int copies = run_has_relic(rc, RelicId::BING_BONG) ? 2 : 1;
    if (rc.deckCount > MAX_DECK - 3 * copies) return false;
    int common = 0, uncommon = 0;
    for (int i = 1; i < static_cast<int>(CardId::COUNT); ++i) {
        const CardDef &d = card_def(static_cast<CardId>(i));
        if (d.pool != CardPool::IRONCLAD || (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY))) continue;
        common += d.rarity == Rarity::COMMON;
        uncommon += d.rarity == Rarity::UNCOMMON;
    }
    return common >= 4 && uncommon >= 2;
}

bool begin_card_grid(RunContext &rc, int kind) {
    if (rc.cardGrid.kind || kind < 1 || kind > 5) return false;
    RunCardGrid grid;
    grid.kind = static_cast<std::uint8_t>(kind);
    if (kind == 5) {
        if (!can_generate_scroll_boxes(rc)) return false;
        Rng &rng = rc.playerRng[PRNG_REWARDS];
        for (int i = 0; i < 6; ++i) {
            const Rarity wanted = i % 3 == 2 ? Rarity::UNCOMMON : Rarity::COMMON;
            CardId candidates[static_cast<int>(CardId::COUNT)];
            int count = 0;
            for (int j = 1; j < static_cast<int>(CardId::COUNT); ++j) {
                const CardId id = static_cast<CardId>(j);
                const CardDef &d = card_def(id);
                if (d.pool != CardPool::IRONCLAD || d.rarity != wanted ||
                    (d.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY))) continue;
                bool used = false;
                for (int k = 0; k < i; ++k) used |= grid.cards[k].id == id;
                if (!used) candidates[count++] = id;
            }
            grid.cards[i] = rc.make_run_card(candidates[rng.next_int(0, count - 1)], false);
        }
        grid.count = 6;
        grid.minSelect = grid.maxSelect = 1;
    } else if (kind == 3 || kind == 4) {
        grid.count = rc.deckCount;
        grid.minSelect = kind == 4 ? 1 : 0;
        grid.maxSelect = kind == 4 ? 1 : 6;
        if (kind == 4) {
            bool any = false;
            for (int i = 0; i < rc.deckCount; ++i)
                any |= card_can_enchant(rc.deck[i], EnchantmentId::CLONE);
            if (!any) return false;
        }
    } else {
        const int desired = kind == 1 ? 5 : 8;
        grid.count = make_noncombat_card_candidates(rc, grid.cards, desired, CardPool::IRONCLAD, kind == 2);
        grid.minSelect = grid.maxSelect = kind == 1 ? 1 : 2;
        if (grid.count < grid.minSelect) return false;
    }
    rc.cardGrid = grid;
    return true;
}

bool card_grid_can_select(const RunContext &rc, int index) {
    const RunCardGrid &grid = rc.cardGrid;
    if (!grid.kind || grid.preview || index < 0 || index >= grid.count) return false;
    if (grid.kind == 5) return index < 2 &&
        rc.deckCount <= MAX_DECK - 3 * (run_has_relic(rc, RelicId::BING_BONG) ? 2 : 1);
    if (grid.selected[index]) return true;
    if (grid.selectedCount >= grid.maxSelect) return false;
    if (grid.kind == 3 && !card_can_transform_from_deck(rc.deck[index])) return false;
    if (grid.kind == 4) return card_can_enchant(rc.deck[index], EnchantmentId::CLONE);
    const int copies = run_has_relic(rc, RelicId::BING_BONG) ? 2 : 1;
    const int net = grid.kind == 3 ? copies - 1 : copies;
    return rc.deckCount + (grid.selectedCount + 1) * net <= MAX_DECK;
}

bool select_card_grid(RunContext &rc, int index) {
    if (!card_grid_can_select(rc, index)) return false;
    RunCardGrid &grid = rc.cardGrid;
    if (grid.selected[index]) {
        grid.selected[index] = false;
        --grid.selectedCount;
        for (int slot = 0; slot < grid.slotCount; ++slot) {
            if (grid.orderSlots[slot] != index) continue;
            grid.orderSlots[slot] = -1;
            grid.freeNext[slot] = grid.freeHead;
            grid.freeHead = slot;
            break;
        }
        return true;
    }
    int slot = grid.freeHead;
    if (slot >= 0) {
        grid.freeHead = grid.freeNext[slot];
        grid.freeNext[slot] = -1;
    } else {
        slot = grid.slotCount++;
    }
    grid.orderSlots[slot] = index;
    grid.selected[index] = true;
    ++grid.selectedCount;
    if (grid.selectedCount == grid.maxSelect) {
        if (grid.kind == 3 || grid.kind == 5) grid.preview = true;
        else return confirm_card_grid(rc);
    }
    return true;
}

bool confirm_card_grid(RunContext &rc) {
    RunCardGrid &grid = rc.cardGrid;
    if (!grid.kind || grid.selectedCount < grid.minSelect || grid.selectedCount > grid.maxSelect)
        return false;
    const int kind = grid.kind;
    if (kind == 4) {
        for (int i = 0; i < grid.count; ++i) {
            if (!grid.selected[i]) continue;
            if (!card_apply_enchantment(rc.deck[i], EnchantmentId::CLONE, 4)) return false;
            rc.cardGrid = RunCardGrid{};
            return true;
        }
        return false;
    }
    if (kind == 3 && !grid.preview) {
        grid.preview = true;
        return true;
    }
    Card selected[8];
    int originalIndices[8];
    int n = 0;
    for (int slot = 0; slot < grid.slotCount; ++slot) {
        const int i = grid.orderSlots[slot];
        if (i < 0) continue;
        if (kind == 5) {
            for (int j = 0; j < 3; ++j) selected[n++] = grid.cards[i * 3 + j];
        } else selected[n++] = kind == 3 ? make_maul_transformation(rc, rc.deck[i]) : grid.cards[i];
    }
    if (kind == 3) {
        int item = 0;
        for (int slot = 0; slot < grid.slotCount; ++slot) {
            const int index = grid.orderSlots[slot];
            if (index < 0) continue;
            int removedEarlier = 0;
            for (int prior = 0; prior < slot; ++prior)
                if (grid.orderSlots[prior] >= 0 && grid.orderSlots[prior] < index) ++removedEarlier;
            originalIndices[item++] = index - removedEarlier;
        }
        int dst = 0;
        for (int i = 0; i < rc.deckCount; ++i)
            if (!grid.selected[i]) rc.deck[dst++] = rc.deck[i];
        rc.deckCount = dst;
        for (int i = 1; i < n; ++i) {
            Card card = selected[i];
            int index = originalIndices[i], j = i;
            while (j > 0 && originalIndices[j - 1] > index) {
                selected[j] = selected[j - 1];
                originalIndices[j] = originalIndices[j - 1];
                --j;
            }
            selected[j] = card;
            originalIndices[j] = index;
        }
    }
    rc.cardGrid = RunCardGrid{};
    for (int i = 0; i < n; ++i) {
        Card card = selected[i];
        const CardType type = card_def(card.id).type;
        if (!card.upgraded && card_upgradable(card) &&
            ((type == CardType::ATTACK && run_has_relic(rc, RelicId::MOLTEN_EGG)) ||
             (type == CardType::SKILL && run_has_relic(rc, RelicId::TOXIC_EGG)) ||
             (type == CardType::POWER && run_has_relic(rc, RelicId::FROZEN_EGG))))
            card_apply_upgrade(card);
        if (!rc.add_card_to_deck(card)) return false; // capacity was checked on selection
    }
    if (kind == 1 || kind == 2) event_finish_card_grid(rc);
    return true;
}

bool cancel_card_grid_preview(RunContext &rc) {
    RunCardGrid &grid = rc.cardGrid;
    if ((grid.kind != 3 && grid.kind != 5) || !grid.preview) return false;
    grid.preview = false;
    grid.selectedCount = grid.slotCount = 0;
    grid.freeHead = -1;
    for (bool &selected : grid.selected) selected = false;
    for (int i = 0; i < 8; ++i) grid.orderSlots[i] = grid.freeNext[i] = -1;
    return true;
}

bool card_grid_valid(const RunContext &rc) {
    const RunCardGrid &grid = rc.cardGrid;
    if (!grid.kind) return grid.count == 0 && grid.selectedCount == 0 && !grid.preview &&
                           grid.slotCount == 0 && grid.freeHead == -1;
    if (grid.kind > 5 || grid.count < 0 || grid.count > ((grid.kind == 3 || grid.kind == 4) ? rc.deckCount : 8) ||
        grid.minSelect < 0 || grid.maxSelect < grid.minSelect || grid.maxSelect > 6 ||
        grid.selectedCount < 0 || grid.selectedCount > grid.maxSelect) return false;
    if (grid.slotCount < 0 || grid.slotCount > 8 || grid.freeHead < -1 ||
        grid.freeHead >= grid.slotCount || (grid.preview && grid.kind != 3 && grid.kind != 5)) return false;
    if (grid.kind == 3 && (grid.count != rc.deckCount || grid.minSelect != 0 || grid.maxSelect != 6)) return false;
    if (grid.kind == 4 && (grid.count != rc.deckCount || grid.minSelect != 1 || grid.maxSelect != 1)) return false;
    if (grid.kind == 5 && (grid.count != 6 || grid.minSelect != 1 || grid.maxSelect != 1 ||
                           (grid.preview != (grid.selectedCount == 1)))) return false;
    if (grid.kind == 5) {
        for (int i = 0; i < 6; ++i) {
            const Card &card = grid.cards[i];
            if (card.id == CardId::INVALID || static_cast<int>(card.id) >= static_cast<int>(CardId::COUNT)) return false;
            const CardDef &def = card_def(card.id);
            if (def.pool != CardPool::IRONCLAD ||
                def.rarity != (i % 3 == 2 ? Rarity::UNCOMMON : Rarity::COMMON) ||
                (def.flags & (CF_UNPLAYABLE | CF_MULTIPLAYER_ONLY))) return false;
            for (int j = 0; j < i; ++j)
                if (grid.cards[j].id == card.id || grid.cards[j].uid == card.uid) return false;
        }
    }
    if (grid.kind < 3 && (rc.screen != RunScreen::EVENT || grid.minSelect != (grid.kind == 1 ? 1 : 2) ||
                           grid.maxSelect != grid.minSelect)) return false;
    int selected = 0;
    for (int i = 0; i < MAX_DECK; ++i) {
        if (grid.selected[i]) {
            if (i >= grid.count || (grid.kind == 5 && i >= 2) || (grid.kind == 3 && !card_can_transform_from_deck(rc.deck[i])) ||
                (grid.kind == 4 && !card_can_enchant(rc.deck[i], EnchantmentId::CLONE))) return false;
            ++selected;
        }
    }
    bool seen[MAX_DECK]{};
    int activeSlots = 0;
    for (int i = 0; i < grid.slotCount; ++i) {
        const int index = grid.orderSlots[i];
        if (index < -1 || index >= grid.count) return false;
        if (index >= 0) {
            if (seen[index] || !grid.selected[index] || grid.freeNext[i] != -1) return false;
            seen[index] = true;
            ++activeSlots;
        }
    }
    bool freeSlots[8]{};
    int free = grid.freeHead;
    while (free >= 0) {
        if (free >= grid.slotCount || freeSlots[free] || grid.orderSlots[free] != -1) return false;
        freeSlots[free] = true;
        free = grid.freeNext[free];
        if (free < -1) return false;
    }
    for (int i = 0; i < grid.slotCount; ++i)
        if ((grid.orderSlots[i] == -1) != freeSlots[i]) return false;
    return selected == grid.selectedCount && activeSlots == selected;
}
}
