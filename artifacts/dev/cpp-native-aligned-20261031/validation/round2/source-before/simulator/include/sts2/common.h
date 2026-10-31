// STS2 simulator core types, modeled on gamerpuppy/sts_lightspeed.
#pragma once

#include <array>
#include <cstdint>
#include <cstring>
#include <cmath>
#include <algorithm>
#include <stdexcept>
#include <string>
#include <string_view>
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

// Native v0.111.0 / 41cef1ea: xxHash64 string seeds and MegaRandom (xoshiro256**).
// Search also uses this class; changing the game RNG changes search sampling.
class Rng {
public:
    Rng() { init(0); }
    explicit Rng(std::uint64_t seed) { init(seed); }
    Rng(std::uint64_t seed, const char *name)
        : Rng(seed + deterministic_hash_code(name)) {}
    Rng(std::uint64_t seed, int startCounter) : Rng(seed) { fast_forward(startCounter); }

    // Convenience retained for simulator tests; native restores all four words.
    void fast_forward(int target) {
        if (target < counter) throw std::invalid_argument("Rng counter cannot move backwards");
        while (counter < target) { bump_counter(); raw_next(); }
    }

    // xxHash64 over UTF-8 bytes, seed zero, matching StringHelper. Byte loads are
    // explicit little endian so neither host alignment nor byte order matters.
    static std::uint64_t deterministic_hash_code(const char *text) {
        return deterministic_hash_code(std::string_view(text));
    }
    static std::uint64_t deterministic_hash_code(std::string_view text) {
        constexpr std::uint64_t p1 = 11400714785074694791ull;
        constexpr std::uint64_t p2 = 14029467366897019727ull;
        constexpr std::uint64_t p3 = 1609587929392839161ull;
        constexpr std::uint64_t p4 = 9650029242287828579ull;
        constexpr std::uint64_t p5 = 2870177450012600261ull;
        const auto read64 = [&](std::size_t offset) {
            std::uint64_t value = 0;
            for (int i = 0; i < 8; ++i)
                value |= std::uint64_t(static_cast<unsigned char>(text[offset + i])) << (8 * i);
            return value;
        };
        const auto read32 = [&](std::size_t offset) {
            std::uint32_t value = 0;
            for (int i = 0; i < 4; ++i)
                value |= std::uint32_t(static_cast<unsigned char>(text[offset + i])) << (8 * i);
            return value;
        };
        const auto round = [&](std::uint64_t acc, std::uint64_t value) {
            return rotate_left(acc + value * p2, 31) * p1;
        };
        std::size_t offset = 0;
        std::uint64_t hash;
        if (text.size() >= 32) {
            std::uint64_t v1 = p1 + p2, v2 = p2, v3 = 0, v4 = 0 - p1;
            do {
                v1 = round(v1, read64(offset));
                v2 = round(v2, read64(offset + 8));
                v3 = round(v3, read64(offset + 16));
                v4 = round(v4, read64(offset + 24));
                offset += 32;
            } while (text.size() - offset >= 32);
            hash = rotate_left(v1, 1) + rotate_left(v2, 7) +
                   rotate_left(v3, 12) + rotate_left(v4, 18);
            for (const auto value : {v1, v2, v3, v4})
                hash = (hash ^ round(0, value)) * p1 + p4;
        } else {
            hash = p5;
        }
        hash += text.size();
        while (text.size() - offset >= 8) {
            hash = rotate_left(hash ^ round(0, read64(offset)), 27) * p1 + p4;
            offset += 8;
        }
        if (text.size() - offset >= 4) {
            hash = rotate_left(hash ^ (std::uint64_t(read32(offset)) * p1), 23) * p2 + p3;
            offset += 4;
        }
        while (offset < text.size())
            hash = rotate_left(hash ^ (std::uint64_t(static_cast<unsigned char>(text[offset++])) * p5), 11) * p1;
        hash ^= hash >> 33;
        hash *= p2;
        hash ^= hash >> 29;
        hash *= p3;
        return hash ^ (hash >> 32);
    }

    // Generated game seeds are ASCII. Reject unsupported Unicode case-folding
    // rather than silently disagreeing with .NET ToUpperInvariant/Trim.
    static std::string canonicalize_seed(std::string text) {
        for (char &c : text) {
            if (static_cast<unsigned char>(c) >= 128)
                throw std::invalid_argument("Run seed canonicalization currently requires ASCII");
            if (c >= 'a' && c <= 'z') c = static_cast<char>(c - 'a' + 'A');
            if (c == 'O') c = '0';
            else if (c == 'I') c = '1';
        }
        const auto space = [](char c) { return c == ' ' || (c >= '\t' && c <= '\r'); };
        std::size_t begin = 0, end = text.size();
        while (begin < end && space(text[begin])) ++begin;
        while (end > begin && space(text[end - 1])) --end;
        return text.substr(begin, end - begin);
    }

    void init(std::uint64_t seed) {
        for (auto &word : words_) word = splitmix64(seed);
        counter = 0;
        reserved_ = 0;
    }

    // Inclusive adapter used by existing C++ game rules. Width is computed in
    // int64 so the entire signed-int interval and high==INT_MAX remain valid.
    int next_int(int low, int high) {
        if (low > high) throw std::invalid_argument("Rng inclusive minimum exceeds maximum");
        bump_counter();
        const std::int64_t width = std::int64_t(high) - low + 1;
        return static_cast<int>(std::int64_t(sample() * static_cast<double>(width)) + low);
    }
    int next_int_exclusive(int maxExclusive) {
        // Native one-argument Rng increments its counter before MegaRandom
        // rejects an invalid maximum, without advancing the random state.
        bump_counter();
        if (maxExclusive < 1) throw std::invalid_argument("Rng maximum must be positive");
        return static_cast<int>(sample() * static_cast<double>(maxExclusive));
    }
    int next_int_range(int minInclusive, int maxExclusive) {
        if (minInclusive >= maxExclusive) throw std::invalid_argument("Rng minimum must be below maximum");
        bump_counter();
        const std::int64_t width = std::int64_t(maxExclusive) - minInclusive;
        return static_cast<int>(std::int64_t(sample() * static_cast<double>(width)) + minInclusive);
    }
    float next_float(float lo, float hi) {
        if (lo > hi) throw std::invalid_argument("Rng float minimum exceeds maximum");
        bump_counter();
        // Native Rng uses MegaRandom.NextDouble, NOT its 24-bit NextFloat.
        const volatile double scaled = sample() * static_cast<double>(hi - lo);
        return static_cast<float>(scaled + static_cast<double>(lo));
    }
    float next_float() { return next_float(0.0f, 1.0f); }
    double next_double() { bump_counter(); return sample(); }
    double next_double(double lo, double hi) {
        if (lo > hi) throw std::invalid_argument("Rng double minimum exceeds maximum");
        bump_counter();
        const volatile double scaled = sample() * (hi - lo);
        return scaled + lo;
    }
    std::uint64_t next_unsigned_long() { bump_counter(); return raw_next(); }

    int next_gaussian_int(int mean, int stdDev, int lo, int hi) {
        if (lo > hi || mean < lo || mean > hi)
            throw std::invalid_argument("Rng Gaussian mean/bounds invalid");
        for (;;) {
            const double u1 = 1.0 - next_double();
            const double u2 = 1.0 - next_double();
            const double z = std::sqrt(-2.0 * std::log(u1)) *
                             std::sin(6.28318530717958647692 * u2);
            const int value = static_cast<int>(round_to_even(double(mean) + double(stdDev) * z));
            if (value >= lo && value <= hi) return value;
        }
    }
    int next_index(int count) { return count <= 0 ? -1 : next_int_exclusive(count); }
    bool next_bool() { return next_int_exclusive(2) == 0; }

    [[nodiscard]] const std::array<std::uint64_t, 4> &state() const { return words_; }
    void restore_state(const std::array<std::uint64_t, 4> &words, std::int32_t count) {
        if ((words[0] | words[1] | words[2] | words[3]) == 0)
            throw std::invalid_argument("Rng all-zero state is not a seeded state");
        words_ = words;
        counter = count;
        reserved_ = 0;
    }
    [[nodiscard]] bool valid_snapshot_state() const {
        return reserved_ == 0 && (words_[0] | words_[1] | words_[2] | words_[3]) != 0;
    }
    template <typename T>
    void shuffle(T *arr, int n) {
        for (int i = n - 1; i > 0; --i) {
            const int j = next_int_exclusive(i + 1);
            std::swap(arr[i], arr[j]);
        }
    }

private:
    static std::uint64_t rotate_left(std::uint64_t value, int bits) {
        return (value << bits) | (value >> (64 - bits));
    }
    static std::uint64_t splitmix64(std::uint64_t &seed) {
        std::uint64_t value = (seed += 11400714819323198485ull);
        value = (value ^ (value >> 30)) * 13787848793156543929ull;
        value = (value ^ (value >> 27)) * 10723151780598845931ull;
        return value ^ (value >> 31);
    }
    std::uint64_t raw_next() {
        const std::uint64_t result = rotate_left(words_[1] * 5, 7) * 9;
        const std::uint64_t t = words_[1] << 17;
        words_[2] ^= words_[0];
        words_[3] ^= words_[1];
        words_[1] ^= words_[2];
        words_[0] ^= words_[3];
        words_[2] ^= t;
        words_[3] = rotate_left(words_[3], 45);
        return result;
    }
    double sample() { return double(raw_next() >> 11) * 0x1p-53; }
    void bump_counter() {
        const std::uint32_t bits = static_cast<std::uint32_t>(counter) + 1u;
        std::memcpy(&counter, &bits, sizeof(counter));
    }
    static double round_to_even(double value) {
        const double lower = std::floor(value), fraction = value - lower;
        if (fraction < 0.5) return lower;
        if (fraction > 0.5) return lower + 1.0;
        return std::fmod(lower, 2.0) == 0.0 ? lower : lower + 1.0;
    }
    std::array<std::uint64_t, 4> words_{};
public:
    std::int32_t counter = 0;
private:
    // Fill tail alignment explicitly: snapshots hash this trivially-copyable object.
    std::uint32_t reserved_ = 0;
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
    // Thrash stores Hook.ModifyDamage's unrounded result (e.g. Weak + Strike
    // contributes 4.5). Keep fractional growth until actual damage is dealt.
    double bonusDamage = 0;
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
double card_base_damage(const Card &c);
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
// Native CardModel.CompareTo: ordinal model entry, then upgrade level.
// Deliberately does not use UID or mutable bonus damage as a tie breaker.
inline bool native_card_less(const Card &a, const Card &b) {
    const int order = std::strcmp(card_key(a.id), card_key(b.id));
    return order != 0 ? order < 0 : a.upgraded < b.upgraded;
}

const PotionDef &potion_def(PotionId id);
const char *potion_name(PotionId id);
PotionId random_potion_out_of_combat(Rng &rng);
int random_potions_out_of_combat(Rng &rng, PotionId *out, int count);

}  // namespace sts2
