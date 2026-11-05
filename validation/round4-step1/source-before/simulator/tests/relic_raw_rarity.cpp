#include "sts2/relic_raw_rarity.h"
using namespace sts2;
static_assert(relic_raw_rarity(RelicId::INVALID) == -1);
static_assert(relic_raw_rarity(RelicId::CIRCLET) == -1);
static_assert(relic_raw_rarity(RelicId::DEPRECATED_RELIC) == -1);
static_assert(relic_raw_rarity(RelicId::BURNING_BLOOD) == 0);
static_assert(relic_raw_rarity(RelicId::ANCHOR) == 1);
static_assert(relic_raw_rarity(RelicId::AKABEKO) == 2);
static_assert(relic_raw_rarity(RelicId::ART_OF_WAR) == 3);
static_assert(relic_raw_rarity(RelicId::CAULDRON) == 4);
static_assert(relic_raw_rarity(RelicId::BING_BONG) == 5);
static_assert(relic_raw_rarity(RelicId::GLASS_EYE) == 7);
static_assert(relic_raw_rarity(RelicId::COUNT) == -1);
int main() { return 0; }
