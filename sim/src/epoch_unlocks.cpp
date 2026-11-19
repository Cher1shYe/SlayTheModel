#include "sts2/common.h"
#include "sts2/relics.h"

#include <cstring>
#include <stdexcept>

namespace sts2 {
namespace {
#include "sts2/epoch_unlocks.inc"

// Lock epoch per content ID (-1: never epoch-gated). Built once from the
// generated native table; an unresolved key is a generator/content mismatch.
struct EpochTables {
    std::int8_t card[static_cast<int>(CardId::COUNT)];
    std::int8_t relic[static_cast<int>(RelicId::COUNT)];
    std::int8_t potion[static_cast<int>(PotionId::COUNT)];
    EpochTables() {
        std::memset(card, -1, sizeof(card));
        std::memset(relic, -1, sizeof(relic));
        std::memset(potion, -1, sizeof(potion));
        for (const auto &lock : NATIVE_CARD_EPOCH_LOCKS) card[resolve(lock.key, static_cast<int>(CardId::COUNT),
            [](int i) { return card_key(static_cast<CardId>(i)); })] = static_cast<std::int8_t>(lock.epoch);
        for (const auto &lock : NATIVE_RELIC_EPOCH_LOCKS) relic[resolve(lock.key, static_cast<int>(RelicId::COUNT),
            [](int i) { return relic_def(static_cast<RelicId>(i)).key; })] = static_cast<std::int8_t>(lock.epoch);
        for (const auto &lock : NATIVE_POTION_EPOCH_LOCKS) potion[resolve(lock.key, static_cast<int>(PotionId::COUNT),
            [](int i) { return potion_def(static_cast<PotionId>(i)).key; })] = static_cast<std::int8_t>(lock.epoch);
    }
    template <class KeyOf>
    static int resolve(const char *key, int count, KeyOf keyOf) {
        for (int i = 1; i < count; ++i) if (std::strcmp(keyOf(i), key) == 0) return i;
        throw std::logic_error(std::string("epoch lock for unknown content ") + key);
    }
};

const EpochTables &tables() {
    static const EpochTables t;
    return t;
}

bool revealed(std::uint64_t mask, int epoch) { return epoch < 0 || ((mask >> epoch) & 1u) != 0; }
}  // namespace

int native_epoch_count() { return NATIVE_EPOCH_COUNT; }
const char *native_epoch_name(int epoch) {
    return epoch >= 0 && epoch < NATIVE_EPOCH_COUNT ? NATIVE_EPOCH_NAMES[epoch] : nullptr;
}
int card_unlock_epoch(CardId id) { return tables().card[static_cast<int>(id)]; }
int relic_unlock_epoch(RelicId id) { return tables().relic[static_cast<int>(id)]; }
int potion_unlock_epoch(PotionId id) { return tables().potion[static_cast<int>(id)]; }
bool card_epoch_unlocked(std::uint64_t mask, CardId id) { return revealed(mask, card_unlock_epoch(id)); }
bool relic_epoch_unlocked(std::uint64_t mask, RelicId id) { return revealed(mask, relic_unlock_epoch(id)); }
bool potion_epoch_unlocked(std::uint64_t mask, PotionId id) { return revealed(mask, potion_unlock_epoch(id)); }
}  // namespace sts2
