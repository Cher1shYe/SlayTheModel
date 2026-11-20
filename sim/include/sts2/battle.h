#pragma once

#include "sts2/common.h"
#include "sts2/silent_state.h"
#include "sts2/defect_state.h"
#include "sts2/necrobinder_state.h"
#include "sts2/regent_state.h"
#include "sts2/turn_flow_state.h"

namespace sts2 {

constexpr int MAX_HAND = 10;
constexpr int MAX_PILE = 160;
constexpr int MAX_MONSTERS = 6;  // native encounters have up to 6 enemy slots (Ovicopter, Living Fog)
constexpr int MAX_POTIONS = 12;
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
    DUPLICATE,          // clone a selected hand card
    DISCARD_ANY,        // discard any number of hand cards (then draw as many)
    SILENT_DISCARD, SILENT_SLY, SILENT_NIGHTMARE,
    NECRO_SCULPT_ETHEREAL, NECRO_SNAP_RETAIN, NECRO_SEANCE, NECRO_TRANSFIGURE,
    REGENT_TRANSFORM, REGENT_CLONE, REGENT_AUTO_SKILL,
    // KnowledgeDemon.ChooseCurse during the enemy turn: pick one of two curse cards
    // (CardSelectCmd.FromChooseACardScreen); the enemy turn resumes afterwards.
    KNOWLEDGE_CURSE,
    GAMBLING_CHIP,
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
    int toricToughnessBlock = 0;
    // Native power DynamicVars["SelfDamage"], incremented by each card play
    // independently of the power's block/damage Amount.
    int crimsonMantleSelfDamage = 0;
    int infernoSelfDamage = 0;
    bool infernoBeforeCrimsonMantle = false;
    bool surroundedFacingRight = true;
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
    // Native MonsterMoveStateMachine.StateLog keeps the whole history; UseOnlyOnce
    // checks StateLog.Contains. One bit per local state ever logged (states < 32).
    std::uint32_t everLogged = 0;
    // Native rolls every enemy's next move at the start of the player's turn, in
    // enemy order (CombatManager: PrepareForNextTurn after BeforeSideTurnStart).
    // After acting, `move` keeps the performed move (native NextMove) and the
    // follow-up state waits here until roll_pending_moves.
    bool pendingRoll = false;
    std::uint8_t pendingState = 0;
    // CombatManager iterates Enemies.ToList() taken when the enemy turn starts: a
    // creature added during the enemy turn does not act until the next one.
    bool spawnedThisEnemyTurn = false;
    // Position in the native enemy list (CombatState.SortEnemiesBySlotName): the index
    // of the slot name in Encounter.Slots, or 64 + creation order when the encounter
    // has no Slots. Turn order, move rolls and random targets follow it.
    std::int16_t orderKey = 0;
    bool offBalance = false;
    bool combatEndBlocker = false;

    int power[static_cast<int>(PowerId::COUNT)]{};
    int tempStrengthLoss = 0;
    int stolenGold = 0;  // Thievery/Heist amount carried by this monster
    int steamEruptionDamage = 0;  // Waterfall Giant's stored explosion damage
    // Per-monster AI counters referenced by conditional branches (respawn count,
    // extra multi-claw hits, charged flags, curse counters).
    std::int16_t aux[4]{};
    bool reviving = false;  // Test Subject: between death and RESPAWN_MOVE
    bool stunned = false;   // skips its next action (e.g. waking up)

    // intent for the coming monster turn
    std::uint8_t intentType = 0;  // 0 attack, 1 block, 2 buff, 3 debuff, 4 status
    int intentDamage = 0;
    int intentHits = 1;

    // Power rule state (SlowPower.SlowAmount, HardenedShellPower damage cap,
    // NemesisPower's alternating Intangible flag).
    int slowCardsThisTurn = 0;
    int shellHpLostThisTurn = 0;
    bool nemesisIntangible = false;
    bool skittishTriggeredThisTurn = false;
    // RitualPower.WasJustAppliedByEnemy: a newly created Ritual instance on an
    // enemy skips its first AfterSideTurnEnd.
    bool ritualJustApplied = false;
    int grappleCount = 0;
    int grappleAmounts[MAX_PILE]{};
};

// Result of one damage application (DamageResult in the reference engine).
struct DamageDealt {
    int total = 0;      // blocked + unblocked damage
    int unblocked = 0;  // HP actually lost (capped at remaining HP)
    int overkill = 0;   // damage beyond the target's remaining HP
    bool blockBroken = false;
    bool fullyBlocked = false;
    bool wasKilled = false;
};

// One card play in progress, mirroring CardModel.OnPlayWrapper: the source card
// entity is placed in the result pile exactly once, after every play iteration
// (replay / Duplication / One-Two Punch / Throwing Axe) has finished.  A
// selector inside OnPlay suspends the frame; resolving it resumes the play.
struct ActivePlay {
    SilentPlayState silent;
    DefectPlayState defect;
    NecrobinderPlayState necro;
    RegentPlayState regent;
    bool active = false;
    Card card{};          // the one source entity, reused by every iteration
    int target = 0;
    int playCount = 1;
    int nextPlay = 0;     // play iterations started so far
    bool autoPlay = false;
    bool forceExhaust = false;  // CardPileCmd.AutoPlayFromDrawPile(forceExhaust)
    bool dupe = false;          // HistoryCourse CreateDupe: excluded from history
    // NostalgiaPower decided the result pile at play start (CardModel computes
    // it once, before any replay iteration): this source card returns to the
    // top of the draw pile instead of the discard pile.
    bool resultsToDraw = false;
    // OnPlay paused inside a selector: AfterCardPlayed must run when it closes.
    bool awaitingAfter = false;
    bool swiftAwaitingDraw = false;  // Swift OnPlay suspended in a draw choice
    // Energy actually paid for this card (0 for auto-plays); Intimidating
    // Helmet checks CardPlay.Resources.EnergyValue.
    int energySpent = 0;
    int starsSpent = 0;
    int starX = 0;
};

struct PendingChoice {
    ChoiceOp op = ChoiceOp::NONE;
    ChoicePile pile = ChoicePile::NONE;
    // A choice may enumerate an entire draw/discard pile (up to MAX_PILE
    // cards); MAX_HAND is only the size of the hand itself.
    Card cards[MAX_PILE]{};
    int count = 0;
    int remaining = 1;     // how many more cards may be chosen (multi-select)
    bool optional = false;
    Card sourceCard{};
    bool hasSource = false;
    bool sourceExhaust = false;
    int payload = 0;
    // Native hand selectors retain their cards until the player confirms.
    int selectedUids[MAX_HAND]{};
    int selectedCount = 0;
};

// A confirmed hand exhaust waits for draw-triggered choices and child plays.
// Store only selected identities and source metadata, not a MAX_PILE candidate copy.
struct ConfirmedExhaustChoice {
    Card sourceCard{};
    int uids[MAX_HAND]{};
    int count=0, index=0, payload=0, ownerDepth=-1;
    bool hasSource=false, sourceExhaust=false;
};

struct AutoPlayRequest {
    Card card;
    int ownerDepth = -1;
    int target = -1;
    bool forceExhaust = false;
    bool dupe = false;
    bool visible = false;
    int xOverride = -1;  // X already captured by CardModel.SpendResources (skipXCapture)
};
struct SuspendedPlay {
    ActivePlay play;
    int xCost = 0;
    int pendingDrawRemainder = 0;
    bool returnToHand = false;
    bool pendingDrawFromHand = false;
};
constexpr int MAX_PLAY_DEPTH = 16;

struct BattleContext {
    // Kept as a compatibility seed stream for direct callers.  Combat effects
    // use the named streams below, matching RunRngSet.
    Rng rng;
    Rng shuffleRng;
    Rng cardGenerationRng;
    Rng potionRng;
    Rng cardSelectionRng;
    Rng energyCostRng;
    Rng targetRng;
    Rng monsterAiRng;
    Rng nicheRng;
    Rng orbRng;
    CardPool characterPool = CardPool::IRONCLAD;
    std::uint8_t unlockedCharacterMask = 31;
    std::uint64_t revealedEpochs = ~std::uint64_t{0};  // copied from the run's progress
    SilentState silent;
    DefectState defect;
    NecrobinderState necro;
    RegentState regent;
    TurnFlowState turnFlow;
    Player player;
    Monster monsters[MAX_MONSTERS]{};
    int monsterCount = 0;
    // Native Creature.SetUniqueMonsterHpValue looks at every creature still in the
    // enemy list; a creature whose AfterDeath hooks are running (Surprise spawning
    // the gremlins, Stock respawning an Axebot) has not been removed yet. Its MaxHp
    // (0 = none) also counts as taken, even if its slot is being reused.
    int hpDyingMaxHp = 0;
    // Native Encounter.Slots count for this fight (0 = the encounter has no Slots) and
    // the creation counter used for orderKey when it has none.
    int encounterSlots = 0;
    int spawnSeq = 0;
    // Enemy indices in native list order (orderKey, then index); returns the count.
    int enemy_order(int out[MAX_MONSTERS]) const;

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

    // DeckVersion identities and Swipe events: the run layer owns the
    // original cards and synchronizes theft/removal and special rewards.
    std::uint16_t originalDeckUids[MAX_PILE]{};
    int originalDeckCount = 0;
    std::uint16_t theftUids[MAX_PILE]{};
    Card theftCards[MAX_PILE]{};  // publicly visible combat versions
    std::int8_t theftOwners[MAX_PILE]{};
    bool theftReturned[MAX_PILE]{};
    int theftCount = 0;

    int turn = 0;         // PlayerCombatState.TurnNumber, including extra turns
    int combatRound = 0;  // CombatState.RoundNumber; extra turns stay in the same round
    int ascension = 0;
    int xCost = 0;
    Encounter encounter = Encounter::INVALID;
    Outcome outcome = Outcome::UNDECIDED;
    PendingChoice pending;
    // Native UsePotionAction / DiscardPotionGameAction wait behind an open
    // player choice. Keep their FIFO order and lock each queued belt slot.
    Action queuedPotionActions[MAX_POTIONS]{};
    int queuedPotionActionCount = 0;
    ActivePlay activePlay;
    SuspendedPlay suspendedPlays[MAX_PLAY_DEPTH]{};
    int suspendedPlayCount = 0;
    ConfirmedExhaustChoice confirmedExhaustChoices[MAX_PLAY_DEPTH]{};
    int confirmedExhaustCount = 0;
    bool runningConfirmedExhaust = false;
    AutoPlayRequest autoPlayQueue[MAX_PILE]{};
    int autoPlayQueueCount = 0;
    bool runningPlayLoop = false;
    bool turnFlowRunning = false;  // re-entrancy guard for resume_turn_flow
    bool nextPlayIsDupe = false;  // HistoryCourse: the copy is not history
    std::uint16_t nextUid = 1;
    // Reservations protect locally constructed offers until the next action
    // completes. Direct C++ callers must clear after committing their local
    // candidates to a pile or choice; doing so earlier permits UID reuse.
    std::uint64_t uidReservations[1024]{};

    // Returns 0 only if every non-sentinel UID is occupied or reserved.
    std::uint16_t allocate_card_uid();
    // Throws std::overflow_error on exhaustion rather than creating UID 0.
    std::uint16_t require_card_uid();
    void clear_card_uid_reservations();

    // per-turn / per-combat counters used by card triggers
    int cardsPlayedThisTurn = 0;
    int tenderCardsPlayedThisTurn = 0;
    int slothCardsPlayedThisTurn = 0;
    int manualCardsPlayedThisTurn = 0; // finished non-autoplay CardPlay instances
    int attacksPlayedThisTurn = 0;
    int cardsPlayedThisCombat = 0;
    int cardsFinishedThisCombat = 0;
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
    bool byrdpipPresent = false;
    bool boneTeaPending = false;
    int recoveredStolenGold = 0;
    bool vitalSparkTriggeredThisEnemyTurn = false;
    bool lavaLampTookQualifyingDamage = false;
    // BattlewornDummyEventEncounter.RanOutOfTime (the dummy escaped).
    bool battlewornRanOutOfTime = false;
    // CombatState.EscapedCreatures for EncounterModel.CalculateGoldProportion:
    // creatures removed by CreatureCmd.Escape (Thieving Hopper, Fat Gremlin).
    std::uint8_t escapedMonsterCount = 0;
    bool fatGremlinEscaped = false;
    // GremlinMercNormal.GoldWasStolen (SurprisePower.AfterDeath with stolen gold).
    bool mercGoldStolen = false;
    // Goopy DeckVersion growth (Amount++ per play), applied to the run deck by
    // uid when the combat ends. Only original deck cards have a DeckVersion.
    std::uint16_t goopyUids[MAX_PILE]{};
    std::int16_t goopyGrowth[MAX_PILE]{};
    int goopyCount = 0;
    void record_goopy_growth(std::uint16_t uid);
    Card returnNextTurn[MAX_HAND]{};
    int returnNextTurnCount = 0;
    bool gainedBlockFromCardThisTurn = false;
    // UnmovablePower counts block-gaining CardPlays this turn: the index of the
    // current play is fixed on its first block gain and compared to Amount.
    // UnmovablePower: native BlockGainedEntry rows (block > 0 gained from a card play)
    // this turn, and how many of them belong to the card play in progress.
    int blockGainEntriesThisTurn = 0;
    int blockGainEntriesThisPlay = 0;
    bool playedAttackOrSkillThisTurn = false;
    bool jugglingTriggeredThisTurn = false;
    // Attack/skill plays started this turn (NostalgiaPower compares this count
    // against its amount; plays are recorded when they start, like
    // CombatHistory.CardPlaysStarted).
    int attackSkillPlaysThisTurn = 0;
    // Card uids played this turn / during the previous round (ThrummingHatchet
    // recalls the instance it was played from).
    std::uint16_t playedThisTurn[MAX_PILE]{};
    int playedThisTurnCount = 0;
    std::uint16_t playedLastTurn[MAX_PILE]{};
    int playedLastTurnCount = 0;
    bool returnToHand = false;
    bool reboundPending = false;
    bool skillsLocked = false;
    bool inMonsterTurn = false;
    // FurCoat.AfterCreatureAddedToCombat: enemies added during a marked combat start at 1 HP.
    bool furCoatActive = false;
    // ToastyMittens: Strength follows the turn-start hand exhaust choice.
    bool toastyMittensPending = false;
    // CardSelectCmd.PushSelector(VakuuCardSelector): selections take the first maxSelect options.
    bool vakuuSelecting = false;
    int turn1Energy = 0;
    int gold = 0;
    int nextTurnEnergy = 0;
    int nextTurnDraw = 0;
    // Top-of-draw cards whose identity/order the player already knows
    // (Headbutt, Nostalgia, known status placements, ...).  Determinization
    // must preserve them exactly.
    int knownTopCount = 0;
    // The Bomb is instanced: each copy has its own countdown and damage.  There
    // is no rule limit on instances (TheBombPower.IsInstanced); the array is a
    // storage bound only, sized past any pile that can feed auto-play.
    static constexpr int MAX_BOMBS = MAX_PILE;
    int bombTurns[MAX_BOMBS]{};
    int bombDamage[MAX_BOMBS]{};
    int bombCount = 0;
    bool resolvingCard = false;
    int pendingRupture = 0;
    // AutomationPower is instanced: every application keeps its own countdown
    // of drawn cards ("cardsLeft"), independent of turn boundaries.
    static constexpr int MAX_AUTOMATION = MAX_PILE;
    int automationLeft[MAX_AUTOMATION]{};
    int automationAmount[MAX_AUTOMATION]{};
    int automationCount = 0;
    // Toric Toughness keeps the block and remaining triggers per application.
    int toricCount = 0;
    int toricBlock[MAX_PILE]{};
    int toricTurns[MAX_PILE]{};
    int rollingCount = 0;
    int rollingDamage[MAX_PILE]{};
    int panacheCount = 0;
    int panacheDamage[MAX_PILE]{};
    int panacheLeft[MAX_PILE]{};
    bool panachePrimed[MAX_PILE]{};
    // Draws remaining after a choice interrupted CardPileCmd.Draw (Stratagem).
    int pendingDrawRemainder = 0;
    bool pendingDrawFromHand = false;
    bool weakSkipTick = false;   // Doubt/Shame: skip the tick at this turn's end
    bool frailSkipTick = false;
    bool vulnerableSkipTick = false;
    Card lastPlayedCard{};
    bool hasLastPlayed = false;
    int lastPlayedTurn = -1;     // turn of the last real (non-dupe) play

    // potions carried into this combat (PotionId values)
    int potions[MAX_POTIONS]{};
    int potionCount = 0;
    int potionSlots = BASE_POTION_SLOTS;

    int relics[MAX_RELICS]{};
    int relicCount = 0;
    int relicAux[MAX_RELICS]{};
    bool relicWax[MAX_RELICS]{};
    bool relicMelted[MAX_RELICS]{};
    // Per-turn scratch counter (Joss Paper's non-saved EtherealCount).
    int relicAux2[MAX_RELICS]{};
    // Ethereal exhausts are counted now and drawn at end of turn
    // (DarkEmbracePower.AfterTurnEnd).
    int darkEmbraceEthereal = 0;

    void init(Encounter enc, std::uint64_t seed, const Card *deck, int deckCount,
              int ascensionLevel, int playerHp = -1, int playerMaxHp = -1,
              const int *relicIds = nullptr, int relicN = 0,
              const int *potionIds = nullptr, int potionN = 0,
              int slotCount = BASE_POTION_SLOTS, int turn1Energy = 0,
              int energyPerTurn = 3, int runGold = 0,
              std::uint64_t potionSeed = 0, const int *relicAuxIn = nullptr,
              const Rng *runRngs = nullptr, const bool *relicWaxIn = nullptr,
              const bool *relicMeltedIn = nullptr, std::uint64_t encounterSeed = 0);

    [[nodiscard]] std::vector<Action> legal_actions() const;
    bool step(const Action &action);
    bool step_action(const Action &action);
    void settle_forced_choices();

    // Determinization for player-usable search: shuffle zones whose order the
    // player cannot see (draw/discard) and replace the hidden future-RNG stream.
    void resample_hidden(std::uint32_t seed);

    void start_player_turn(bool extraTurn = false);
    void end_player_turn();
    void resume_turn_flow();
    void continue_pre_draw();
    void after_hand_drawn();
    // Returns false when the enemy turn is suspended for a player choice made during it
    // (Knowledge Demon); resolve_choice resumes it.
    bool monster_turn();
    bool monster_turn_continue();      // the act loop from suspendedTurnK, then the turn end
    void after_monster_turn();         // end-of-enemy-turn ticks, then start_player_turn
    int suspendedTurnK = -1;
    // ChainsOfBindingPower: Bound afflictions made this player turn, and whether a
    // Bound card was played (only one may be played per turn).
    int boundAfflictedThisTurn = 0;
    bool boundCardPlayed = false;
    // Hook.ShouldPlay listeners that block a card (Sloth, Chains of Binding).
    bool hook_blocks_play(const Card &c) const;
    // v17: Ringing / Entangled / Smog afflictions (one affliction per card; only a
    // card with no other affliction receives them). 0 none, 1 Ringing, 2 Entangled, 3 Smog.
    int turn_affliction(const Card &c) const;
    // AfterCardEnteredCombat afflictions: GalvanicPower (Power cards -> Galvanized) and
    // VitalSparkPower (Skills without an affliction -> Tainted).
    void afflict_entering_card(Card &c) const;
    void update_hex_afflictions(bool apply);
    void update_tainted_afflictions(int amount);
    // DampenPower.AfterApplied / AfterRemoved: downgrade every upgraded combat card, and
    // upgrade the same cards again when the power is removed.
    void dampen_apply();
    void dampen_remove();
    int suspendedOrder[MAX_MONSTERS]{};
    int suspendedOrderN = 0;
    void end_turn_triggers();

    void draw_cards(int count, bool fromHandDraw = false);
    void shuffle_discard_into_draw(bool force = false);
    void move_to_discard(const Card &c);
    void move_to_exhaust(const Card &c, bool causedByEthereal = false);
    void add_card_to_hand(const Card &c);
    void add_card_to_discard(const Card &c);
    void add_card_to_draw_top(const Card &c);
    void add_card_to_draw_random(const Card &c);
    // Removing a specific draw-pile index must keep knownTopCount consistent:
    // known cards are exactly the top knownTopCount entries (draw[drawCount-1]
    // is the top), so removing one of them shrinks the known prefix.
    void remove_draw_at(int idx);
    // Pops the top card; callers must check drawCount first.
    Card take_draw_top();
    // Removes one existing entity (by UID) from whichever pile holds it, so a
    // snapshotted card is played as the same physical card, never a duplicate.
    bool detach_card(std::uint16_t uid);
    // Queue an entity to return to hand next turn, once per UID (a replay must
    // not enqueue the same card twice).
    void queue_return_next_turn(const Card &c);
    void discard_hand();
    // Explicit discard batches run discard hooks, then draw, then Sly plays.
    void discard_cards(const Card *cards, int count, int drawAfter = 0);
    void auto_play_cards(const Card *cards, int count, int fixedTarget = -1,
                         bool forceExhaust = false);
    void kill_monster(int index);
    void resolve_monster_death(int index);
    void kill_player();
    // byPlayer: the generation's creator is the player (CardPileCmd creator).
    void notify_card_generated(const Card &card, bool byPlayer = true);
    bool start_queued_auto_play();
    void restore_suspended_play();

    bool play_card(int handIdx, int target);
    void play_card_effect(Card &card, int target);
    void after_card_played(const Card &card);
    [[nodiscard]] bool card_will_exhaust(const Card &c) const;

    // Hook.ModifyDamage's first step for a card source: the card's enchantment
    // EnchantDamageAdditive then EnchantDamageMultiplicative on the card's own
    // base, before Vigor/Strength (Vigorous, Sharp, Corrupted).
    double enchant_card_damage(const Card &card, double base) const;
    int calc_player_damage(double base, int monsterIdx, bool powered = true,
                           const Card *card = nullptr) const;
    // Native Thrash evaluates the selected card before exhausting it, with no
    // target and no AttackCommand. This value is intentionally not rounded.
    double thrash_damage_growth(const Card &selected) const;
    int calc_monster_damage(const Monster &m, int base) const;
    void face_surrounded_target(int target);
    void gain_gold(int amount);
    void trigger_skittish(int target, bool unblocked);
    void attack_monster(int target, int base, int hits = 1, bool powered = true);
    void attack_random_monster(int base, int hits = 1, bool powered = true);
    void attack_all(int base, int hits = 1, bool powered = true);
    bool attack_from_card(Card &card, int target, double base, int hits = 1, bool all = false);
    bool can_trigger_fatal(int target) const;
    void attack_all_from_card(Card &card, double base, int hits = 1);
    void attack_random_from_card(Card &card, double base, int hits = 1);
    void monster_attack_player(int monsterIdx, int base);
    void lose_max_hp(int amount, bool fromCard);
    void heal_hp(int amount);
    int generate_play_count(const Card &card);
    // Returns the amount of HP actually lost.  poweredAttack marks damage from
    // an AttackCommand (TheGambitPower checks Props.IsPoweredAttack()).
    int damage_player(int amount, bool unblockable = false, bool poweredAttack = false,
                      bool deferCardRupture = true);
    // poweredAttack gates monster Thorns (ValueProp.IsPoweredAttack).
    DamageDealt damage_monster(int idx, int amount, bool fromPlayer = true,
                               bool poweredAttack = false, bool unblockable = false);
    void gain_block(int amount, bool fromCard = false, bool powered = true);
    int gain_block_raw(int amount, bool powered = true);
    void apply_vulnerable(int idx, int amount, bool fromCard = true);
    void apply_weak(int idx, int amount, bool fromCard = true);
    void apply_strength_loss(int idx, int amount, bool fromCard = true);
    void add_temp_strength(int amount);
    void add_temp_dexterity(int amount);
    void lose_hp(int amount, bool fromCard = false);

    int player_power(PowerId id) const;
    int monster_power(int idx, PowerId id) const;
    void add_player_power(PowerId id, int amount, bool fromCard = false);
    void add_monster_power(int idx, PowerId id, int amount, bool fromCard = false);
    void trigger_exhaust_hooks(const Card &card, bool causedByEthereal);
    // Hook.AfterTurnEnd effects that only see ethereal exhausts after the hand
    // flush (Dark Embrace, Joss Paper).
    void flush_ethereal_exhaust_hooks();
    void trigger_block_hooks(int amount);

    int alive_monster_count() const;
    int first_alive_monster() const;
    int random_alive_monster();
    Card *find_in_hand(std::uint16_t uid);
    Card *find_in_discard(std::uint16_t uid);
    Card *find_in_draw(std::uint16_t uid);

    Card random_card_of_type(CardType type, bool include_colorless = true);
    Card random_colorless_card();
    Card random_character_card_excluding(const CardId *excluded, int excludedCount);
    Card random_colorless_card_excluding(const CardId *excluded, int excludedCount);
    Card random_attack();
    Card random_skill();
    Card random_power();
    void add_random_card_to_hand(CardType type, bool free = false, bool colorless = false,
                                 bool upgraded = false);
    void upgrade_card(Card &c);
    void transform_card(Card &c);
    void play_top_card(bool exhaustIt);
    void auto_play_random(const Card &c, bool exhaustIt);
    void auto_play_dupe(const Card &c);
    // ThrummingHatchet.BeforeHandDraw: recall the exact instance that was
    // played during the previous round from whichever pile holds it.
    void recall_played_last_turn(CardId id);
    // CardPileCmd.AutoPlayFromDrawPile: shuffle-if-necessary before every take,
    // collect all cards first, then run them through AutoPlay in order.
    void auto_play_from_draw(int count, bool forceExhaust);

    // Unified play lifecycle (CardModel.OnPlayWrapper).
    void begin_play(const Card &card, int target, bool autoPlay, bool forceExhaust,
                    int energySpent = 0, int starsSpent = 0);
    void run_active_play();
    void finish_active_play();

    void start_choice(ChoiceOp op, ChoicePile pile, int count, bool optional,
                      const Card &source, bool sourceExhaust, int payload = 0,
                      int candidateLimit = MAX_PILE);
    // Choose one card from the draw pile to add to hand, filtered by type/rarity
    // (pass -1 for "any").
    void start_draw_choice(const Card &source, bool sourceExhaust, int type, int rarity,
                           int candidateLimit = -1);
    void start_offer(ChoiceOp op, const Card *cards, int count, const Card &source,
                     bool sourceExhaust, bool free);
    void resolve_choice(std::uint16_t uid);
    void confirm_exhaust_choice(const int *uids, int count);
    void resume_confirmed_exhaust_choices();
    void auto_resolve_pending();
    void finish_pending();
    void maybe_finish_pending();

    void check_outcome();
    void clear_player_powers_after_death();
    int energy_cost_in_combat(const Card &card) const;
    // CardModel.CanPlay for a hand card (any valid target): the legal-play filter.
    bool hand_card_playable_now(int handIdx) const;
    // WhisperingEarring.AfterAutoPrePlayPhaseEnteredLate (turn 1).
    void whispering_earring_auto_play();

    bool can_use_potion(int idx) const;
    bool potion_action_queued(int idx) const;
    void drain_potion_actions();
    void use_potion(int idx, int target);
    void apply_potion(PotionId id, int target);
    void add_potion(PotionId id);
    PotionId gain_random_combat_potion();
    bool try_fairy_revive();
};

int &power_ref(Player &p, PowerId id);
int &power_ref(Monster &m, PowerId id);

}  // namespace sts2
