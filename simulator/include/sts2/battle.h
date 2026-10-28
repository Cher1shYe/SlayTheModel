#pragma once

#include "sts2/common.h"

namespace sts2 {

constexpr int MAX_HAND = 10;
constexpr int MAX_PILE = 160;
constexpr int MAX_MONSTERS = 4;
constexpr int MAX_POTIONS = 5;
constexpr int BASE_POTION_SLOTS = 3;
constexpr int MAX_RELICS = 32;

enum class ChoiceOp : std::uint8_t {
    NONE,
    UPGRADE,            // upgrade a hand card
    EXHAUST,            // exhaust a hand card
    RETURN_DISCARD_TOP, // discard card -> top of draw
    PUT_HAND_TOP,       // hand card -> top of draw
    DRAW_TO_HAND,       // draw-pile card -> hand
    DISCARD_TO_HAND,    // discard-pile card -> hand
    OFFER_TO_HAND,      // one of the offered cards -> hand
    GIVE_REPLAY,        // draw-pile card gains replay
    TRANSFORM,          // replace card with a random one
    MAKE_FREE,          // hand card costs 0 for the combat
    DISCARD_ANY,        // discard any number of hand cards (then draw as many)
};
enum class ChoicePile : std::uint8_t { NONE, HAND, DISCARD, DRAW, OFFER };

struct Player {
    int hp = 80;
    int maxHp = 80;
    int block = 0;
    int energy = 3;
    int energyPerTurn = 3;
    int drawPerTurn = 5;

    int strength = 0;
    int dexterity = 0;
    int tempStrength = 0;
    int tempDexterity = 0;
    int vulnerable = 0;
    int weak = 0;
    int frail = 0;

    int power[static_cast<int>(PowerId::COUNT)]{};
    bool tookUnblockedDamageThisTurn = false;
    bool tookUnblockedAttackDamageThisCombat = false;
};

struct Monster {
    MonsterId id = MonsterId::INVALID;
    int hp = 0;
    int maxHp = 0;
    int block = 0;
    int strength = 0;
    int vulnerable = 0;
    int weak = 0;
    int turn = 0;
    bool alive = true;

    std::uint8_t move = 0;
    std::uint8_t lastMove = 0;
    std::uint8_t slot = 0;
    std::uint8_t stateLog[8]{};
    std::uint8_t stateLogN = 0;

    int power[static_cast<int>(PowerId::COUNT)]{};
    int tempStrengthLoss = 0;
    // Per-monster AI counters referenced by conditional branches (respawn count,
    // extra multi-claw hits, charged flags, curse counters).
    std::int16_t aux[4]{};
    bool reviving = false;  // Test Subject: between death and RESPAWN_MOVE
    bool stunned = false;   // skips its next action (e.g. waking up)

    // intent for the coming monster turn
    std::uint8_t intentType = 0;  // 0 attack, 1 block, 2 buff, 3 debuff, 4 status
    int intentDamage = 0;
    int intentHits = 1;
};

struct PendingChoice {
    ChoiceOp op = ChoiceOp::NONE;
    ChoicePile pile = ChoicePile::NONE;
    Card cards[MAX_HAND]{};
    int count = 0;
    int remaining = 1;     // how many more cards may be chosen (multi-select)
    bool optional = false;
    Card sourceCard{};
    bool hasSource = false;
    bool sourceExhaust = false;
    int payload = 0;
};

struct BattleContext {
    Rng rng;
    // Combat potion generation stream (Rng.CombatPotionGeneration); separate from
    // the monster-AI stream so Alchemize and similar effects don't perturb AI rolls.
    Rng potionRng;
    Player player;
    Monster monsters[MAX_MONSTERS]{};
    int monsterCount = 0;

    Card hand[MAX_HAND]{};
    int handCount = 0;
    Card draw[MAX_PILE]{};
    int drawCount = 0;
    Card discard[MAX_PILE]{};
    int discardCount = 0;
    Card exhaust[MAX_PILE]{};
    int exhaustCount = 0;
    Card playPile[MAX_PILE]{};
    int playCount = 0;

    int turn = 0;
    int ascension = 0;
    int xCost = 0;
    Encounter encounter = Encounter::INVALID;
    Outcome outcome = Outcome::UNDECIDED;
    PendingChoice pending;
    std::uint16_t nextUid = 1;

    // per-turn / per-combat counters used by card triggers
    int cardsPlayedThisTurn = 0;
    int attacksPlayedThisTurn = 0;
    int cardsPlayedThisCombat = 0;
    int hpLostThisTurn = 0;
    int hpLostThisCombat = 0;
    int exhaustedThisTurn = 0;
    int exhaustedThisCombat = 0;
    int cardsDrawnThisTurn = 0;
    int skillsPlayedThisTurn = 0;
    int skillsPlayedThisCombat = 0;
    int attacksPlayedThisCombat = 0;
    int cardsPlayedLastTurn = 0;
    int attacksPlayedLastTurn = 0;
    int unblockedHitsThisCombat = 0;
    int combatGold = 0;
    Card returnNextTurn[MAX_HAND]{};
    int returnNextTurnCount = 0;
    bool gainedBlockFromCardThisTurn = false;
    bool playedAttackOrSkillThisTurn = false;
    bool jugglingTriggeredThisTurn = false;
    bool nostalgiaPending = false;
    bool returnToHand = false;
    bool skillsLocked = false;
    bool inMonsterTurn = false;
    int turn1Energy = 0;
    int gold = 0;
    Card lastPlayedCard{};
    bool hasLastPlayed = false;

    // potions carried into this combat (PotionId values)
    int potions[MAX_POTIONS]{};
    int potionCount = 0;
    int potionSlots = BASE_POTION_SLOTS;

    int relics[MAX_RELICS]{};
    int relicCount = 0;
    int relicAux[MAX_RELICS]{};

    void init(Encounter enc, std::uint32_t seed, const Card *deck, int deckCount,
              int ascensionLevel, int playerHp = -1, int playerMaxHp = -1,
              const int *relicIds = nullptr, int relicN = 0,
              const int *potionIds = nullptr, int potionN = 0,
              int slotCount = BASE_POTION_SLOTS, int turn1Energy = 0,
              int energyPerTurn = 3, int runGold = 0,
              std::uint32_t potionSeed = 0);

    [[nodiscard]] std::vector<Action> legal_actions() const;
    bool step(const Action &action);

    void start_player_turn();
    void end_player_turn();
    void monster_turn();
    void end_turn_triggers();

    void draw_cards(int count);
    void shuffle_discard_into_draw();
    void move_to_discard(const Card &c);
    void move_to_exhaust(const Card &c);
    void add_card_to_hand(const Card &c);
    void add_card_to_discard(const Card &c);
    void add_card_to_draw_top(const Card &c);
    void discard_hand();

    void play_card(int handIdx, int target);
    void play_card_effect(Card &card, int target);
    void finish_played_card(const Card &card);
    void after_card_played(const Card &card);
    [[nodiscard]] bool card_will_exhaust(const Card &c) const;

    int calc_player_damage(int base, int monsterIdx) const;
    int calc_monster_damage(const Monster &m, int base) const;
    void attack_monster(int target, int base, int hits = 1);
    void attack_random_monster(int base, int hits = 1);
    void attack_all(int base, int hits = 1);
    void attack_from_card(Card &card, int target, int base, int hits = 1, bool all = false);
    void monster_attack_player(int monsterIdx, int base);
    void damage_player(int amount, bool unblockable = false);
    void damage_monster(int idx, int amount, bool fromPlayer = true);
    void gain_block(int amount, bool fromCard = false);
    int gain_block_raw(int amount);
    void apply_vulnerable(int idx, int amount);
    void apply_weak(int idx, int amount);
    void lose_hp(int amount, bool fromCard = false);

    int player_power(PowerId id) const;
    int monster_power(int idx, PowerId id) const;
    void add_player_power(PowerId id, int amount);
    void add_monster_power(int idx, PowerId id, int amount);
    void trigger_exhaust_hooks(const Card &card);
    void trigger_block_hooks(int amount);

    int alive_monster_count() const;
    int first_alive_monster() const;
    int random_alive_monster();
    Card *find_in_hand(std::uint16_t uid);
    Card *find_in_discard(std::uint16_t uid);
    Card *find_in_draw(std::uint16_t uid);

    Card random_card_of_type(CardType type, bool include_colorless = true);
    Card random_colorless_card();
    Card random_attack();
    Card random_skill();
    Card random_power();
    void add_random_card_to_hand(CardType type, bool free = false, bool colorless = false,
                                 bool upgraded = false);
    void upgrade_card(Card &c);
    void transform_card(Card &c);
    void play_top_card(bool exhaustIt);
    void auto_play_random(const Card &c, bool exhaustIt);

    void start_choice(ChoiceOp op, ChoicePile pile, int count, bool optional,
                      const Card &source, bool sourceExhaust, int payload = 0,
                      int candidateLimit = MAX_HAND);
    // Choose one card from the draw pile to add to hand, filtered by type/rarity
    // (pass -1 for "any").
    void start_draw_choice(const Card &source, bool sourceExhaust, int type, int rarity,
                           int candidateLimit = -1);
    void start_offer(ChoiceOp op, const Card *cards, int count, const Card &source,
                     bool sourceExhaust, bool free);
    void resolve_choice(std::uint16_t uid);
    void auto_resolve_pending();
    void finish_pending();
    void maybe_finish_pending();

    void check_outcome();
    void finish_pending_source();

    bool can_use_potion(int idx) const;
    void use_potion(int idx, int target);
    void apply_potion(PotionId id, int target);
    void add_potion(PotionId id);
    PotionId gain_random_combat_potion();
    bool try_fairy_revive();
};

int &power_ref(Player &p, PowerId id);
int &power_ref(Monster &m, PowerId id);

}  // namespace sts2
