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
// CardFactory.CreateForReward(player, count,
// CardCreationOptions.ForNonCombatWithDefaultOdds(pool, filter)): base-odds
// rarity roll with wrap, PlayerRng.Rewards pick, no upgrade roll, non-card-
// reward modify hooks. Returns -1 (run unchanged) if the pool is empty.
enum class EventCardFilter : std::uint8_t { ANY, POWER, CANONICAL_ZERO_COST };
int make_default_odds_event_cards(RunContext &rc, CardPool pool, EventCardFilter filter,
                                  Card *out, int count);
// new CardReward(options(pool, Uniform, rarity filter), count): uniform pick of
// distinct cards of one rarity, upgrade roll, IsCardReward modify hooks.
// new CardReward(ForNonCombatWithDefaultOdds(character pool), count): base-odds
// rarity (no pity), no upgrade roll, IsCardReward pool and modify hooks.
int make_default_odds_card_reward(RunContext &rc, Card *out, int count);
// CrystalSphereCardReward.ToReward: uniform rarity, 3 cards, RNG override.
int make_crystal_sphere_card_reward(RunContext &rc, Rarity rarity, Rng &rng, Card *out);
int make_uniform_rarity_card_reward(RunContext &rc, CardPool pool, Rarity rarity,
                                    Card *out, int count, int typeFilter = -1);
bool obtain_dusty_tome_card(RunContext &rc, CardId prepared);
// Hook.ModifyCardRewardCreationOptions for an IsCardReward reward without
// NoCardPoolModifications, in owned-relic order: Prismatic Gem puts every
// unlocked character pool in front (unless all pools are colorless), Dingy Rug
// appends Colorless. Writes the native GetPossibleCards order; returns count.
int native_card_reward_pool(const RunContext &rc, CardPool base, CardId *out);
bool card_reward_pool_widened(const RunContext &rc);
// Hook.TryModifyCardRewardOptions (+Late) for an IsCardReward reward: Lasting
// Candy's extra Power (combat rewards; encounterOdds 0 regular, 1 elite, 2 boss;
// -1 = not from combat), then the Late hooks in owned-relic order (Lava Lamp
// only when lavaLampEligible). Returns the new option count.
int apply_card_reward_hooks(RunContext &rc, Card *cards, int count, int capacity, int encounterOdds,
                            bool lavaLampEligible = false);
}
