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
    TURN_FLOW_SIDE_START = 6,     // Hook.AfterSideTurnStart(Player)
};
struct TurnFlowState {
    int stage=0;
    // PowerModel.AmountOnTurnStart for DrawCardsNextTurnPower.
    int drawCardsNextTurnAtStart=0;
};
}
