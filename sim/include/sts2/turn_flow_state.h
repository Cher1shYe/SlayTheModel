#pragma once
namespace sts2 {
// Resumable player-turn setup (CombatManager.SetupPlayerTurn and the turn-start
// hooks).  A selection opened by any stage suspends the flow; resolving it
// continues from the recorded stage.
enum TurnFlowStage : int {
    TURN_FLOW_IDLE = 0,
    TURN_FLOW_HAND_DRAW = 1,      // inside CardPileCmd.Draw (Stratagem etc.)
    TURN_FLOW_PRE_DRAW = 2,       // remaining BeforeHandDraw work, then the draw
    TURN_FLOW_SILENT_APTS = 3,    // Hook.AfterPlayerTurnStart, per listener
    TURN_FLOW_NECRO_APTS = 4,
    TURN_FLOW_REGENT_APTS = 5,
    TURN_FLOW_RELIC_PRE_DRAW = 7,
    TURN_FLOW_RELIC_APTS = 8,
    TURN_FLOW_PAELS_EYE_END = 9,
    TURN_FLOW_SIDE_START = 6,     // Hook.AfterSideTurnStart(Player)
    TURN_FLOW_POWER_APTS = 10,    // AfterPlayerTurnStart of the player's powers (they precede relics)
    TURN_FLOW_AUTO_PRE_PLAY = 11, // Hook.AfterAutoPrePlayPhaseEntered (Mayhem, Imbued)
    TURN_FLOW_FINISH_START = 12,  // AfterAutoPrePlayPhaseEnteredLate (Whispering Earring)
};
struct TurnFlowState {
    int stage=0;
    int relicCursor=0;
    int paelsEyeExhaustUids[10]{};
    int paelsEyeExhaustCount=0;
    int paelsEyeExhaustIndex=0;
    bool paelsEyeExtraTurn=false;
    // PowerModel.AmountOnTurnStart for DrawCardsNextTurnPower.
    int drawCardsNextTurnAtStart=0;
    // This setup is an extra turn (Pael's Eye, Ambergris): enemy AfterSideTurnStart powers such as
    // Rampart skip it. Kept here because Rampart now runs after the relics (v29).
    bool extraTurn=false;
};
}
