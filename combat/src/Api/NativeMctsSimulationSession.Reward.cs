using CombatSolver.Engine.InCombat.Simulation;

namespace CombatSolver.Api;

/// <summary>
/// Immutable live-to-simulation hand-off for one stable trajectory boundary.
/// The effective enemy denominator is filled from the captured CombatRootSnapshot;
/// callers must not reconstruct it from live HP.
/// </summary>
public sealed record NativeMctsTrajectoryRewardSeed(
    string TrajectoryId,
    long CaptureId,
    string CaptureBoundaryKey,
    int EntryHp,
    int CapturedEnemyDamagePrefix,
    int? TrajectoryInitialEnemyEffectiveHp);

public sealed record NativeMctsTrajectoryRewardContext(
    string TrajectoryId,
    long CaptureId,
    string CaptureBoundaryKey,
    int EntryHp,
    int InitialEnemyEffectiveHp,
    int CapturedEnemyDamagePrefix)
{
    public int TotalEnemyHpLost(int branchEnemyHpLost)
    {
        if (branchEnemyHpLost < 0)
            throw new InvalidDataException("Branch enemy damage must be non-negative.");
        return checked(CapturedEnemyDamagePrefix + branchEnemyHpLost);
    }
}

/// <summary>
/// The single utility contract shared by the native label and the predicted
/// terminal projection. Values are from the player's perspective and are not
/// converted into win probabilities.
/// </summary>
public static class NativeMctsReward
{
    public static double Score(bool won, bool resolved, int entryHp, int finalHp,
        int enemyHpLost, int enemyHpTotal)
    {
        if (entryHp < 0 || finalHp < 0 || enemyHpLost < 0 || enemyHpTotal < 0)
            throw new InvalidDataException("Native MCTS reward inputs must be non-negative.");
        double progress = Math.Clamp(enemyHpLost / (double)Math.Max(enemyHpTotal, 1), 0.0, 1.0);
        if (won)
            return 0.5 + Math.Atan((finalHp - entryHp) / 20.0) / Math.PI;
        return resolved ? -1.0 + 0.25 * progress : -0.5 + 0.25 * progress;
    }
}

/// <summary>
/// A search terminal is a combat boundary. Native value labels are written after
/// victory hooks and combat teardown, so keep both HP timepoints in the audit.
/// </summary>
public sealed record NativeMctsTerminalRewardInputs(
    string TrajectoryId,
    long CaptureId,
    string CaptureBoundaryKey,
    string Outcome,
    int EntryHp,
    int CombatFinalHp,
    int CombatFinalMaxHp,
    int UnconditionalRelicHeal,
    int WoundedRelicHeal,
    int WoundedHpPercent,
    int AppliedPostCombatHeal,
    int SettledFinalHp,
    int EnemyHpLost,
    int EnemyHpTotal,
    int TrajectoryInitialEnemyHp,
    int CapturedEnemyDamagePrefix,
    int TotalEnemyHpLost,
    double EnemyDamageProgress,
    double Reward);

public sealed partial class NativeMctsSimulationSession
{
    /// <summary>
    /// Project only known native victory healing from the current fork. This
    /// reads no mutable live player, relic, HP or RNG state after root capture.
    /// </summary>
    public NativeMctsTerminalRewardInputs TerminalRewardInputs()
    {
        ThrowIfDisposed();
        NativeMctsState terminal = currentDescription;
        if (!terminal.Terminal)
            throw new InvalidOperationException("Terminal reward requires a terminal combat state.");
        var simulator = (CombatPredictionSimulator)current.Simulator;
        var predicted = simulator.State.GetCreature(capturedRoot.PlayerIdentity.Creature);
        int combatHp = terminal.PlayerHp;
        int maxHp = predicted.MaxHp;
        if (combatHp != predicted.CurrentHp || maxHp < 1)
            throw new InvalidDataException("Terminal player HP differs from the current simulation fork.");
        int totalEnemyHpLost = RewardContext.TotalEnemyHpLost(terminal.EnemyHpLost);
        double progress = Math.Clamp(totalEnemyHpLost
            / (double)Math.Max(RewardContext.InitialEnemyEffectiveHp, 1), 0.0, 1.0);

        int settledHp = combatHp;
        PostCombatRelicHealProfile heal = default;
        int appliedHeal = 0;
        if (terminal.Won)
        {
            var combat = (SimulatedCombatState)simulator.State.CombatState;
            combat.EnsureSupportedPostCombatRewardEffects();
            heal = CombatRootSnapshot.CapturePostCombatRelicHeal(
                combat.RelicsOf(capturedRoot.PlayerIdentity));
            appliedHeal = heal.HealFor(combatHp, maxHp);
            settledHp = checked(combatHp + appliedHeal);
        }
        double reward = NativeMctsReward.Score(terminal.Won, terminal.Resolved,
            RewardContext.EntryHp, settledHp, totalEnemyHpLost,
            RewardContext.InitialEnemyEffectiveHp);
        return new NativeMctsTerminalRewardInputs(
            RewardContext.TrajectoryId, RewardContext.CaptureId,
            RewardContext.CaptureBoundaryKey,
            terminal.Won ? "win" : terminal.Resolved ? "loss" : "unresolved",
            RewardContext.EntryHp, combatHp, maxHp, heal.UnconditionalHeal,
            heal.WoundedHeal, heal.WoundedHpPercent, appliedHeal, settledHp,
            terminal.EnemyHpLost, terminal.EnemyHpTotal,
            RewardContext.InitialEnemyEffectiveHp,
            RewardContext.CapturedEnemyDamagePrefix, totalEnemyHpLost,
            progress, reward);
    }
}
