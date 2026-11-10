#include "sts2/potion_slots.h"
#include "sts2/relics.h"

namespace sts2 {
int potion_occupied_count(const int *ids, int slots) {
    int count = 0;
    for (int i = 0; i < slots; ++i) if (ids[i]) ++count;
    return count;
}
int potion_first_empty_slot(const int *ids, int slots) {
    for (int i = 0; i < slots; ++i) if (!ids[i]) return i;
    return -1;
}
bool potion_slots_valid(const int *ids, int slots, int count) {
    if (slots < 0 || slots > MAX_POTIONS || count < 0 || count > slots) return false;
    for (int i = 0; i < MAX_POTIONS; ++i)
        if (ids[i] < 0 || ids[i] >= static_cast<int>(PotionId::COUNT) || (i >= slots && ids[i])) return false;
    return potion_occupied_count(ids, slots) == count;
}
bool potion_remove_at(int *ids, int slots, int &count, int index) {
    if (index < 0 || index >= slots || ids[index] == 0) return false;
    ids[index] = 0; --count; return true;
}
namespace {
bool put_potion(int *ids, int slots, int &count, PotionId id, int slot) {
    if (id == PotionId::INVALID || static_cast<int>(id) >= static_cast<int>(PotionId::COUNT)) return false;
    if (slot < 0) slot = potion_first_empty_slot(ids, slots);
    if (slot < 0 || slot >= slots || ids[slot]) return false;
    ids[slot] = static_cast<int>(id); ++count; return true;
}
}
bool run_try_procure_potion(RunContext &rc, PotionId id, int slot) {
    if (run_has_relic(rc, RelicId::SOZU)) return false;
    return put_potion(rc.potions, rc.potionSlots, rc.potionCount, id, slot);
}
bool battle_try_procure_potion(BattleContext &bc, PotionId id, int slot) {
    if (relic_has(bc, RelicId::SOZU)) return false;
    if (!put_potion(bc.potions, bc.potionSlots, bc.potionCount, id, slot)) return false;
    relics_potion_obtained(bc); return true;
}
void potion_alchemical_coffer_on_obtain(RunContext &rc) {
    const int oldSlots = rc.potionSlots;
    if (oldSlots > MAX_POTIONS - 4) throw std::overflow_error("Alchemical Coffer exceeds physical potion slot storage");
    rc.potionSlots += 4;
    PotionId generated[4];
    const int count = random_potions_out_of_combat(rc.runRng[RNG_COMBAT_POTION_GENERATION], generated, 4);
    if (count != 4) throw std::logic_error("Native four-potion batch cannot be generated");
    for (int i = 0; i < count; ++i) run_try_procure_potion(rc, generated[i], oldSlots + i);
}
void potion_delicate_frond_before_combat(BattleContext &bc) {
    while (potion_first_empty_slot(bc.potions, bc.potionSlots) >= 0) {
        // Repeated one-potion factory calls intentionally allow duplicates.
        // Generation precedes Sozu rejection, so failure still consumes RNG.
        const auto id = random_potion_out_of_combat(bc.potionRng);
        if (!battle_try_procure_potion(bc, id)) break;
    }
}
}  // namespace sts2
