// STS2 simulator core types, modeled on gamerpuppy/sts_lightspeed.
#pragma once

#include <array>
#include <cstdint>
#include <cstring>
#include <cmath>
#include <algorithm>
#include <stdexcept>
#include <vector>

namespace sts2 {

enum class CardType : std::uint8_t { ATTACK, SKILL, POWER, STATUS, CURSE };
enum class TargetType : std::uint8_t {
    ENEMY, ALL_ENEMIES, SELF, RANDOM_ENEMY, ALLY, ALL_ALLIES, NONE
};
enum class Rarity : std::uint8_t {
    BASIC, COMMON, UNCOMMON, RARE, SPECIAL, ANCIENT, EVENT, TOKEN, STATUS, CURSE
};
enum class CardPool : std::uint8_t {
    IRONCLAD, COLORLESS, EVENT, CURSE, TOKEN, STATUS
};
enum class Outcome : std::uint8_t { UNDECIDED, PLAYER_VICTORY, PLAYER_LOSS, TRUNCATED };
enum class ActionType : std::uint8_t { PLAY_CARD, END_TURN, CHOOSE, CONFIRM, USE_POTION };
enum class ChoiceKind : std::uint8_t { NONE, UPGRADE_HAND, EXHAUST_HAND, RETURN_DISCARD_TO_DRAW, PUT_HAND_ON_DRAW };

enum class PotionUsage : std::uint8_t { COMBAT_ONLY, ANY_TIME, AUTOMATIC };
enum class PotionTarget : std::uint8_t { SELF, ANY_ENEMY, ALL_ENEMIES, ANY_PLAYER };

// Powers not already represented by a dedicated scalar on Player/Monster.
enum class PowerId : std::uint8_t {
    STRENGTH, DEXTERITY, VULNERABLE, WEAK, FRAIL,
    ARTIFACT, INTANGIBLE, BUFFER, THORNS, POISON, REGEN, METALLICIZE, PLATING,
    VIGOR, RITUAL, ENRAGE, CURL_UP, HARDENED_SHELL, SLOW, SHRINK, GRAPPLE,
    MANGLE_POW, KNOCKDOWN, COLOSSUS, CRUELTY, DOUBLE_DAMAGE,
    RAGE, FLAME_BARRIER, DEMON_FORM, JUGGERNAUT, DARK_EMBRACE, FEEL_NO_PAIN,
    CORRUPTION, BARRICADE, UNMOVABLE, VICIOUS, AGGRESSION, HELLRAISER,
    STAMPEDE, JUGGLING, ONE_TWO_PUNCH, PYRE, MAYHEM, PANACHE, PREP_TIME,
    ROLLING_BOULDER, NOSTALGIA, STRATAGEM, AUTOMATION, ENTROPY, FASTEN,
    DRUM_OF_BATTLE, INFERNO, RUPTURE, CRIMSON_MANTLE,
    EQUILIBRIUM, THE_BOMB, THE_GAMBIT, NO_BLOCK, BLOCK_NEXT_TURN,
    RETAIN_HAND, SETUP_STRIKE, FREE_ATTACK, CALAMITY, COVERED, TANK,
    BEACON_OF_HOPE, COORDINATE, NO_DRAW, THE_BOMB_DAMAGE,
    HELLO_WORLD, DEMISE,
    // monster-specific powers (content expanded from the reference engine)
    ADAPTABLE, ASLEEP, BACK_ATTACK_LEFT, BACK_ATTACK_RIGHT, BURROWED,
    CHAINS_OF_BINDING, CONSTRICT, CRAB_RAGE, DAMPEN, DOOR_REVIVAL,
    ESCAPE_ARTIST, FLUTTER, GALVANIC, HARD_TO_KILL, HATCH, HEX, ILLUSION,
    IMBALANCED, INFESTED, MINION, PAINFUL_STABS, PAPER_CUTS, PERSONAL_HIVE,
    PLOW, POSSESS_SPEED, POSSESS_STRENGTH, RAMPART, RAVENOUS, REATTACH,
    RINGING, SHRIEK, SKITTISH, SLIPPERY, SLUMBER, SMOGGY, SOAR,
    STEAM_ERUPTION, STOCK, SUCK, SURPRISE, SURROUNDED, SWIPE, SANDPIT,
    TANGLED, TENDER, TERRITORIAL, TORIC_TOUGHNESS,
    THIEVERY, VITAL_SPARK, BATTLEWORN_DUMMY_TIME_LIMIT, HIGH_VOLTAGE,
    DUPLICATION, GIGANTIFICATION, DIAMOND_DIADEM, NEMESIS,
    CLARITY, RADIANCE,
    COUNT
};

#define STS2_CARD_CONTENT_ENUMS 1
#include "sts2/cards_generated.inc"
#undef STS2_CARD_CONTENT_ENUMS

#define STS2_MONSTER_CONTENT_ENUMS 1
#include "sts2/monsters_generated.inc"
#undef STS2_MONSTER_CONTENT_ENUMS

#define STS2_POTION_CONTENT_ENUMS 1
#include "sts2/potions_generated.inc"
#undef STS2_POTION_CONTENT_ENUMS

struct PotionDef {
    PotionId id;
    const char *key;
    const char *name;
    Rarity rarity;
    PotionUsage usage;
    PotionTarget target;
    bool ironclad;
    bool combatGen;
};

enum class RelicPool : std::uint8_t { SHARED, IRONCLAD, EVENT, OTHER };

#define STS2_RELIC_CONTENT_ENUMS 1
#include "sts2/relics_generated.inc"
#undef STS2_RELIC_CONTENT_ENUMS

struct RelicDef {
    RelicId id;
    const char *key;
    const char *name;
    Rarity rarity;
    RelicPool pool;
    bool implemented;
};

struct Action {
    ActionType type = ActionType::END_TURN;
    std::uint8_t hand = 0;
    std::uint8_t target = 0;
    std::uint16_t uid = 0;

    bool operator==(const Action &o) const {
        return type == o.type && hand == o.hand && target == o.target && uid == o.uid;
    }
};

// .NET System.Random compatible generator used by the game's seeded Rng.
class Rng {
public:
    static constexpr std::int32_t INT_MAX_V = 2147483647;

    Rng() { init(0); }
    explicit Rng(std::uint32_t seed) { init(static_cast<std::int32_t>(seed)); }
    Rng(std::uint32_t seed, const char *name)
        : Rng(seed + static_cast<std::uint32_t>(deterministic_hash_code(name))) {}
    Rng(std::uint32_t seed, int startCounter) : Rng(seed) { fast_forward(startCounter); }

    // Mirrors C# Rng.FastForwardCounter (advances the raw .NET sequence).
    void fast_forward(int target) {
        if (counter > target) {
            throw std::invalid_argument(
                "Cannot fast-forward an Rng counter to a lower number");
        }
        while (counter < target) {
            ++counter;
            internal_sample();
        }
    }

    static std::int32_t deterministic_hash_code(const char *text) {
        std::int32_t num = 352654597;
        std::int32_t num2 = num;
        const int n = static_cast<int>(std::strlen(text));
        for (int i = 0; i < n; i += 2) {
            num = to_int32(static_cast<std::int64_t>(to_int32(static_cast<std::int64_t>(num) * 32)) + num);
            num = to_int32(static_cast<std::int64_t>(num) ^ static_cast<unsigned char>(text[i]));
            if (i == n - 1) break;
            num2 = to_int32(static_cast<std::int64_t>(to_int32(static_cast<std::int64_t>(num2) * 32)) + num2);
            num2 = to_int32(static_cast<std::int64_t>(num2) ^ static_cast<unsigned char>(text[i + 1]));
        }
        return to_int32(static_cast<std::int64_t>(num) +
                        to_int32(static_cast<std::int64_t>(num2) * 1566083941LL));
    }

    void init(std::int32_t seed) {
        const std::int32_t subtraction = (seed == (-2147483647 - 1)) ? INT_MAX_V : std::abs(seed);
        std::int32_t mj = to_int32(161803398 - subtraction);
        seedArray[55] = mj;
        std::int32_t mk = 1;
        int ii = 0;
        for (int i = 1; i < 55; ++i) {
            ii += 21;
            if (ii >= 55) ii -= 55;
            seedArray[ii] = mk;
            mk = to_int32(static_cast<std::int64_t>(mj) - mk);
            if (mk < 0) mk += INT_MAX_V;
            mj = seedArray[ii];
        }
        for (int k = 1; k < 5; ++k) {
            for (int i = 1; i < 56; ++i) {
                int n = i + 30;
                if (n >= 55) n -= 55;
                seedArray[i] = to_int32(static_cast<std::int64_t>(seedArray[i]) - seedArray[1 + n]);
                if (seedArray[i] < 0) seedArray[i] += INT_MAX_V;
            }
        }
        inext = 0;
        inextp = 21;
        counter = 0;
    }

    int internal_sample() {
        int loc_inext = inext + 1;
        if (loc_inext >= 56) loc_inext = 1;
        int loc_inextp = inextp + 1;
        if (loc_inextp >= 56) loc_inextp = 1;
        std::int32_t ret = to_int32(static_cast<std::int64_t>(seedArray[loc_inext]) - seedArray[loc_inextp]);
        if (ret == INT_MAX_V) ret -= 1;
        if (ret < 0) ret += INT_MAX_V;
        seedArray[loc_inext] = ret;
        inext = loc_inext;
        inextp = loc_inextp;
        return ret;
    }

    double sample() {
        return static_cast<double>(internal_sample()) /
               static_cast<double>(INT_MAX_V);
    }

    // Inclusive bounds, matching python Rng.next_int.
    int next_int(int low, int high) {
        if (low > high) std::swap(low, high);
        ++counter;
        const std::int64_t range = static_cast<std::int64_t>(high) - low + 1;
        return static_cast<int>(sample() * static_cast<double>(range)) + low;
    }

    // C# Rng.NextInt(maxExclusive).
    int next_int_exclusive(int maxExclusive) {
        if (maxExclusive <= 0) return 0;
        return next_int(0, maxExclusive - 1);
    }

    // C# Rng.NextInt(minInclusive, maxExclusive).
    int next_int_range(int minInclusive, int maxExclusive) {
        if (minInclusive >= maxExclusive) return minInclusive;
        return next_int(minInclusive, maxExclusive - 1);
    }

    // C# Rng.NextFloat(min, max) (counter is advanced).
    float next_float(float lo, float hi) {
        ++counter;
        return static_cast<float>(static_cast<double>(internal_sample()) /
                                      static_cast<double>(INT_MAX_V) *
                                      static_cast<double>(hi - lo) +
                                  static_cast<double>(lo));
    }

    float next_float() { return next_float(0.0f, 1.0f); }

    // Rng.NextDouble advances the same System.Random stream and counter.
    double next_double() {
        ++counter;
        return sample();
    }

    // C# Rng.NextGaussianInt. Note the reference does not bump Counter here.
    int next_gaussian_int(int mean, int stdDev, int lo, int hi) {
        for (int guard = 0; guard < 10000; ++guard) {
            const double u1 = 1.0 - static_cast<double>(internal_sample()) / INT_MAX_V;
            const double u2 = 1.0 - static_cast<double>(internal_sample()) / INT_MAX_V;
            const double z = std::sqrt(-2.0 * std::log(u1)) *
                             std::sin(6.28318530717958647692 * u2);
            const int v = static_cast<int>(round_to_even(
                static_cast<double>(mean) + static_cast<double>(stdDev) * z));
            if (v >= lo && v <= hi) return v;
        }
        return mean < lo ? lo : (mean > hi ? hi : mean);
    }

    // C# Rng.NextItem over a count: next_int(0, count-1).
    int next_index(int count) { return count <= 0 ? -1 : next_int(0, count - 1); }

    bool next_bool() { return next_int(0, 1) == 0; }

    // Snapshot input can contain arbitrary bytes. Validate indices before the
    // generator is ever used, so internal_sample cannot index outside its
    // fixed seed array.
    [[nodiscard]] bool valid_snapshot_state() const {
        if (inext < 0 || inext >= 56 || inextp < 0 || inextp >= 56 || counter < 0)
            return false;
        for (const auto value : seedArray) {
            if (value < 0 || value > INT_MAX_V) return false;
        }
        return true;
    }

    template <typename T>
    void shuffle(T *arr, int n) {
        for (int i = n - 1; i > 0; --i) {
            int j = next_int(0, i);
            T t = arr[i]; arr[i] = arr[j]; arr[j] = t;
        }
    }

private:
    static std::int32_t to_int32(std::int64_t v) {
        std::uint32_t u = static_cast<std::uint32_t>(v & 0xFFFFFFFFu);
        return static_cast<std::int32_t>(u);
    }

    static double round_to_even(double value) {
        const double lower = std::floor(value);
        const double fraction = value - lower;
        if (fraction < 0.5) return lower;
        if (fraction > 0.5) return lower + 1.0;
        return std::fmod(lower, 2.0) == 0.0 ? lower : lower + 1.0;
    }

    std::int32_t seedArray[56]{};
    int inext = 0;
    int inextp = 21;
public:
    std::int64_t counter = 0;
};

struct CardDef {
    CardId id;
    const char *key;     // reference engine CardId name
    const char *name;    // display name
    CardPool pool;
    std::int8_t cost;
    std::int8_t costUp;
    CardType type;
    TargetType target;
    Rarity rarity;
    std::int16_t damage;
    std::int16_t damageUp;
    std::int16_t block;
    std::int16_t blockUp;
    std::int16_t var[static_cast<int>(VarId::COUNT)];
    std::int16_t varUp[static_cast<int>(VarId::COUNT)];
    std::uint16_t flags;
    std::uint16_t flagsUp;
};

enum CardFlags : std::uint16_t {
    CF_ETHEREAL = 1u << 0,
    CF_EXHAUST = 1u << 1,
    CF_INNATE = 1u << 2,
    CF_RETAIN = 1u << 3,
    CF_UNPLAYABLE = 1u << 4,
    CF_STRIKE = 1u << 5,
    CF_DEFEND = 1u << 6,
    CF_MULTIPLAYER_ONLY = 1u << 7,
    CF_CANNOT_GENERATE_IN_COMBAT = 1u << 8,
};

enum class EnchantmentId : std::uint8_t { NONE, SOWN, VIGOROUS, SWIFT, GLAM, CLONE };

struct Card {
    CardId id = CardId::INVALID;
    std::uint16_t uid = 0;
    std::int8_t costForTurn = 0;
    bool upgraded = false;
    std::int16_t bonusDamage = 0;   // Rampage / Thrash / Body Slam adjustments
    std::uint8_t replay = 0;        // extra plays from Hidden Gem
    std::uint8_t bonusReplay = 0;   // Soldiers Stew: permanent-for-combat replay
    std::int8_t storedCost = 0;     // cost to restore after a temporary change
    bool freeCombat = false;        // Touch of Insanity: costs 0 for the combat
    bool costThisTurn = false;      // temporary cost modifier, cleared at turn end
    std::int8_t combatCostCap = -1; // Enlightenment+: reduce cost for the combat
    bool etherealThisCombat = false;  // Ghost Seed / Music Box clones
    bool retainThisCombat = false;   // Choices Paradox temporary Retain
    std::int16_t galvanized = 0;   // Galvanized affliction; damage on play
    std::uint8_t guiltyCombatsSeen = 0;  // Guilty's per-card saved combat counter
    EnchantmentId enchantment = EnchantmentId::NONE;
    std::int16_t enchantmentAmount = 0;
    bool enchantmentDisabled = false;  // reset for each combat

    bool operator==(const Card &o) const { return uid == o.uid; }
};

// Temporary cost changes survive in whichever pile the card sits in, but expire
// at the end of the turn (C# CardEnergyCost).  storedCost keeps the real cost.
inline void card_set_turn_cost(Card &c, int cost) {
    if (!c.costThisTurn) c.storedCost = c.costForTurn;
    c.costForTurn = static_cast<std::int8_t>(cost);
    c.costThisTurn = true;
}

inline void card_restore_cost(Card &c) {
    if (!c.costThisTurn) return;
    c.costForTurn = c.storedCost;
    c.costThisTurn = false;
}

const CardDef &card_def(CardId id);
Card make_card(CardId id, bool upgraded, std::uint16_t uid);
// Permanent upgrade (campfire, eggs, events, relics): the upgraded card's
// energy cost must change with the flag (CardModel.OnUpgrade -> EnergyCost).
void card_apply_upgrade(Card &c);
bool card_upgradable(const Card &c);
int card_cost(const Card &c);
int card_damage(const Card &c);
int card_block(const Card &c);
int card_var(const Card &c, VarId v);
bool card_has(const Card &c, std::uint16_t flag);
bool card_is_attack(const Card &c);
bool card_is_skill(const Card &c);
bool card_is_power(const Card &c);
bool card_is_playable(const Card &c);
bool card_can_enchant(const Card &c, EnchantmentId enchantment);
bool card_apply_enchantment(Card &c, EnchantmentId enchantment, int amount);
bool card_is_strike(const Card &c);
bool card_is_defend(const Card &c);

const char *card_name(CardId id);
const char *card_key(CardId id);

const PotionDef &potion_def(PotionId id);
const char *potion_name(PotionId id);
PotionId random_potion_out_of_combat(Rng &rng);
int random_potions_out_of_combat(Rng &rng, PotionId *out, int count);

}  // namespace sts2
