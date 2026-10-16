using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Multiplayer.Game;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;

namespace SlayTheModel.Sts2.DataCollector;

internal static partial class CollectorRuntime
{
    private sealed record ActRewardCombatCapture(
        CombatState State,
        CombatRoom Room,
        IRunState Run,
        Player Player,
        Guid CombatId,
        int Act,
        bool IsBoss);

    // Retain completed states until the run is detached so repeated native
    // notifications cannot produce a second start or end for the same fight.
    private static readonly Dictionary<CombatState, ActRewardCombatCapture>
        ActRewardCombats = new(ReferenceEqualityComparer.Instance);
    private static ActRewardCombatCapture? _activeActRewardCombat;

    /// <summary>
    /// Called by the prefix of Hook.BeforeCombatStart, before start-of-combat
    /// relic effects and the first turn. CombatBegan is already too late for
    /// this HP anchor. Only public scalar evidence is written, not run state.
    /// </summary>
    internal static void CaptureActRewardCombatStart(
        IRunState run,
        ICombatState? combatState)
    {
        if (_episodes?.HasActiveEpisode != true)
        {
            return;
        }

        try
        {
            if (combatState is not CombatState state
                || !ReferenceEquals(state.RunState, run))
            {
                ActRewardBoundaryUnavailable("combat_start", "native_combat_state_unavailable");
                return;
            }

            if (ActRewardCombats.ContainsKey(state))
            {
                return;
            }

            if (RunManager.Instance.NetService.Type != NetGameType.Singleplayer
                || run.Players.Count != 1 || state.Players.Count != 1
                || !ReferenceEquals(run.Players[0], state.Players[0])
                || run.Acts.Count != 3 || run.CurrentActIndex is < 0 or > 2)
            {
                ActRewardBoundaryUnavailable("combat_start", "requires_single_player_three_act_run");
                return;
            }

            if (run.CurrentRoom is not CombatRoom room
                || !ReferenceEquals(room.CombatState, state))
            {
                ActRewardBoundaryUnavailable("combat_start", "native_combat_room_unavailable");
                return;
            }

            if (_activeActRewardCombat is not null)
            {
                ActRewardBoundaryUnavailable("combat_start", "previous_combat_end_missing");
            }

            var capture = new ActRewardCombatCapture(
                state, room, run, run.Players[0], Guid.NewGuid(),
                run.CurrentActIndex + 1, room.RoomType == RoomType.Boss);
            ActRewardCombats.Add(state, capture);
            _activeActRewardCombat = capture;
            RecordActRewardBoundary(capture, "combat_start", won: null, actCompleted: false);
        }
        catch (Exception exception)
        {
            ActRewardBoundaryUnavailable("combat_start", "capture_failed", exception);
        }
    }

    private static Guid? ActRewardCombatId(CombatState state) =>
        ActRewardCombats.TryGetValue(state, out var capture) ? capture.CombatId : null;

    // Native CombatWon follows await Hook.AfterCombatVictory (including
    // Burning Blood healing), and precedes player reward claims.
    private static void OnActRewardCombatWon(CombatRoom room) =>
        CompleteActRewardCombat(room, won: true);

    private static void CaptureActRewardCombatEnded(CombatRoom room)
    {
        if (_episodes?.HasActiveEpisode != true
            || _activeActRewardCombat is not { } capture
            || !ReferenceEquals(capture.State, room.CombatState))
        {
            return;
        }

        try
        {
            // Victory was recorded by CombatWon. An unpaired end is a loss
            // only when the single native player is dead; do not infer a win
            // from remaining HP if the victory callback was not observed.
            if (capture.Player.Creature.IsDead)
            {
                CompleteActRewardCombat(room, won: false);
            }
            else
            {
                ActRewardBoundaryUnavailable("combat_end", "victory_callback_missing");
            }
        }
        catch (Exception exception)
        {
            ActRewardBoundaryUnavailable("combat_end", "capture_failed", exception);
        }
    }

    private static void CaptureActRewardTerminalBoundary(RunHistory history)
    {
        if (_episodes?.HasActiveEpisode != true
            || _activeActRewardCombat is not { } capture)
        {
            return;
        }

        try
        {
            // SaveRunHistory can precede CombatEnded on the fatal action.
            // Close that real death before episode_finished, never turn an
            // abandonment or a missing victory callback into a combat loss.
            if (!history.Win && !history.WasAbandoned && capture.Player.Creature.IsDead)
            {
                CompleteActRewardCombat(capture.Room, won: false);
            }
            else
            {
                ActRewardBoundaryUnavailable("combat_end", "terminal_combat_outcome_unverified");
            }
        }
        catch (Exception exception)
        {
            ActRewardBoundaryUnavailable("combat_end", "terminal_capture_failed", exception);
        }
    }

    private static void CompleteActRewardCombat(CombatRoom room, bool won)
    {
        if (_episodes?.HasActiveEpisode != true)
        {
            return;
        }

        try
        {
            if (!ActRewardCombats.TryGetValue(room.CombatState, out var capture))
            {
                ActRewardBoundaryUnavailable("combat_end", "combat_start_missing");
                return;
            }

            if (!ReferenceEquals(_activeActRewardCombat, capture))
            {
                return;
            }

            if (won && (capture.Player.Creature.IsDead
                        || capture.Run.CurrentActIndex + 1 != capture.Act
                        || !ReferenceEquals(capture.Run.CurrentRoom, room)))
            {
                ActRewardBoundaryUnavailable("combat_end", "victory_state_mismatch");
                return;
            }

            // This is the native EndCombatInternal final-boss condition. A
            // double-boss act completes only at SecondBossMapPoint, even if
            // the first fight has RoomType.Boss as well.
            var actCompleted = false;
            if (won && capture.IsBoss)
            {
                var finalBoss = capture.Run.Map.SecondBossMapPoint
                                ?? capture.Run.Map.BossMapPoint;
                actCompleted = finalBoss is not null
                               && capture.Run.CurrentMapCoord == finalBoss.coord;
            }
            RecordActRewardBoundary(capture, "combat_end", won, actCompleted);
            _activeActRewardCombat = null;
        }
        catch (Exception exception)
        {
            ActRewardBoundaryUnavailable("combat_end", "capture_failed", exception);
        }
    }

    private static void RecordActRewardBoundary(
        ActRewardCombatCapture capture,
        string phase,
        bool? won,
        bool actCompleted)
    {
        var player = capture.Player;
        RecordDiagnostic("act_reward_boundary", new
        {
            schema_version = 1,
            phase,
            combat_id = capture.CombatId,
            act = capture.Act,
            is_boss = capture.IsBoss,
            hp = player.Creature.CurrentHp,
            max_hp = player.Creature.MaxHp,
            // The persistent Deck excludes temporary combat copies and
            // temporary upgrades. A repeatedly upgraded card still counts
            // as one upgraded card. Relics includes the starting relic.
            upgraded_cards = player.Deck.Cards.Count(card => card.IsUpgraded),
            relics = player.Relics.Count,
            won,
            act_completed = actCompleted,
        });
    }

    private static void ActRewardBoundaryUnavailable(
        string phase,
        string reason,
        Exception? exception = null) =>
        RecordDiagnostic("act_reward_boundary_unavailable", new
        {
            phase,
            reason,
            error_type = exception?.GetType().Name,
        });

    private static void ResetActRewardCapture()
    {
        ActRewardCombats.Clear();
        _activeActRewardCombat = null;
    }
}
