using System.Text.Json;
using CombatSolver.Api;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Creatures;
using SlayTheModel.Sts2.Protocol;

public static partial class NativeVerification
{
    public static async Task EnemyDamageAsync(NativeSession session, string outputPath,
        CancellationToken cancellation)
    {
        outputPath = Path.GetFullPath(outputPath);
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
        if (File.Exists(outputPath))
            throw new IOException($"Enemy-damage diagnostic already exists: {outputPath}");

        object despawnUnresolved = await CheckDespawnUnresolvedAsync(session, cancellation);
        object lethalOverkill = await CheckLethalOverkillAsync(session, cancellation);
        object despawnLoss = await CheckDespawnLossAsync(session, cancellation);
        object terminalCleanup = await CheckTerminalCleanupAsync(session, cancellation);

        using var stream = new FileStream(outputPath, FileMode.CreateNew, FileAccess.Write);
        JsonSerializer.Serialize(stream, new
        {
            format = "azcombat.enemy-damage-ledger-regression.v1",
            regressionOnly = true,
            status = "passed",
            stageProvenancePath = Path.Combine(Path.GetDirectoryName(outputPath)!, "stage_provenance.json"),
            assemblies = CombatSolverMctsBenchmark.AssemblyProvenance(),
            despawnUnresolved,
            lethalOverkill,
            despawnLoss,
            terminalCleanup,
        }, new JsonSerializerOptions { WriteIndented = true, PropertyNamingPolicy = JsonNamingPolicy.CamelCase });
    }

    private static async Task<NativeMctsTrajectoryRewardContext> PrepareBombAsync(
        NativeSession session, string seed, CancellationToken cancellation)
    {
        session.Checkpoint = null;
        session.Seed = seed;
        session.EncounterId = "LIVING_FOG_NORMAL";
        session.ChoiceFixture = true;
        session.ChoiceFixtureCards =
            ["STRIKE_IRONCLAD", "BASH", "DEFEND_IRONCLAD", "DEFEND_IRONCLAD", "DEFEND_IRONCLAD"];
        session.ChoiceFixtureUpgradedCards.Clear();
        await session.ResetAsync(session.Seed, cancellation);
        session.BeginTrajectoryAtCurrentState();
        NativeMctsTrajectoryRewardContext firstContext;
        using (var firstRoot = new CombatSolverReplayEnvironment())
        {
            firstRoot.Capture(session.CombatStateForSimulation, session.CaptureRewardSeed());
            session.BindTrajectoryRewardContext(firstRoot.RewardContext);
            firstContext = firstRoot.RewardContext;
        }
        if (firstContext.CaptureId != 1 || firstContext.InitialEnemyEffectiveHp != 80
            || firstContext.CapturedEnemyDamagePrefix != 0)
            throw new InvalidDataException("Initial Gas Bomb trajectory has the wrong denominator or prefix.");

        for (int turn = 0; turn < 4 && !session.CombatStateForSimulation.Enemies.Any(enemy =>
                 enemy.Monster?.Id.Entry == "GAS_BOMB"); turn++)
        {
            var endTurn = session.Actions().Single(action =>
                action.Combat?.Kind == CombatActionKind.EndTurn);
            await session.StepAsync(endTurn, cancellation);
        }
        var bomb = session.CombatStateForSimulation.Enemies.Single(enemy =>
            enemy.Monster?.Id.Entry == "GAS_BOMB");
        if (bomb.CurrentHp != 7 || session.Terminal || session.HasPendingChoice
            || session.EnemyDamageLost != 0
            || !session.EnemyHpTransitions.Any(transition => transition.After > transition.Before
                && transition.EnemyRosterAfter.Any(enemy => enemy.MonsterId == "MONSTER.GAS_BOMB")))
            throw new InvalidDataException("Gas Bomb fixture did not reach a damage-free 7-HP summoned choice.");
        return firstContext;
    }

    private static async Task<object> CheckDespawnUnresolvedAsync(
        NativeSession session, CancellationToken cancellation)
    {
        NativeMctsTrajectoryRewardContext firstContext = await PrepareBombAsync(
            session, "AZ-GAS-BOMB-DESPAWN-UNRESOLVED", cancellation);
        Creature bomb = session.CombatStateForSimulation.Enemies.Single(enemy =>
            enemy.Monster?.Id.Entry == "GAS_BOMB");
        using var predicted = new CombatSolverReplayEnvironment();
        predicted.Capture(session.CombatStateForSimulation, session.CaptureRewardSeed());
        session.BindTrajectoryRewardContext(predicted.RewardContext);
        NativeMctsTrajectoryRewardContext context = predicted.RewardContext;
        if (context.TrajectoryId != firstContext.TrajectoryId || context.CaptureId != 2
            || context.InitialEnemyEffectiveHp != 80 || context.CapturedEnemyDamagePrefix != 0)
            throw new InvalidDataException("Despawn Capture changed its original damage denominator or prefix.");
        var predictedEndTurn = predicted.RootActions.Single(action => action.Native.Kind == "EndTurn");
        await predicted.ApplyAsync(predictedEndTurn, cancellation);
        int predictedBranchDamage = predicted.State.EnemyHpLost;
        int damageBefore = session.EnemyDamageLost;
        var explode = session.Actions().Single(action =>
            action.Combat?.Kind == CombatActionKind.EndTurn);
        await session.StepAsync(explode, cancellation);
        NativeSession.EnemyHpTransition transition = session.EnemyHpTransitions.Last();
        if (session.CombatStateForSimulation.Enemies.Contains(bomb)
            || transition.Before - transition.After != 7
            || transition.Damage != 0
            || transition.EnemyDamageEvents.Count != 0
            || session.EnemyDamageLost != damageBefore
            || predictedBranchDamage != 0
            || session.Terminal || predicted.State.Terminal)
            throw new InvalidDataException(
                $"Gas Bomb exit must not count as damage: transition={transition}, cumulative={session.EnemyDamageLost}.");
        double nativeUnresolved = session.EvaluateUnresolved();
        double predictedUnresolved = predicted.EvaluateUnresolved();
        NativeMctsTerminalRewardInputs rewardInputs = predicted.UnresolvedRewardInputs();
        if (nativeUnresolved != -0.5 || Math.Abs(predictedUnresolved - nativeUnresolved) > 1e-9
            || rewardInputs.CapturedEnemyDamagePrefix != damageBefore
            || rewardInputs.TotalEnemyHpLost != damageBefore)
            throw new InvalidDataException("Gas Bomb unresolved reward differs across native and prediction.");
        return new
        {
            bombHpBefore = 7, bombPresentAfter = false,
            transition, context, predictedBranchDamage,
            nativeUnresolved, predictedUnresolved, rewardInputs,
        };
    }

    private static async Task<object> CheckLethalOverkillAsync(
        NativeSession session, CancellationToken cancellation)
    {
        NativeMctsTrajectoryRewardContext firstContext = await PrepareBombAsync(
            session, "AZ-GAS-BOMB-LETHAL-OVERKILL", cancellation);
        Creature bomb = session.CombatStateForSimulation.Enemies.Single(enemy =>
            enemy.Monster?.Id.Entry == "GAS_BOMB");
        int targetHpBefore = bomb.CurrentHp;
        using var predicted = new CombatSolverReplayEnvironment();
        predicted.Capture(session.CombatStateForSimulation, session.CaptureRewardSeed());
        session.BindTrajectoryRewardContext(predicted.RewardContext);
        NativeMctsTrajectoryRewardContext context = predicted.RewardContext;
        if (context.TrajectoryId != firstContext.TrajectoryId || context.CaptureId != 2
            || context.InitialEnemyEffectiveHp != 80 || context.CapturedEnemyDamagePrefix != 0)
            throw new InvalidDataException("Overkill Capture changed its original denominator or prefix.");
        var bash = predicted.RootActions.Single(action =>
            action.Native.CardId == "BASH" && action.Native.TargetCombatId == bomb.CombatId);
        await predicted.ApplyAsync(bash, cancellation);
        int predictedBranchDamage = predicted.State.EnemyHpLost;
        await session.StepAsync(session.ToLiveSearchAction(bash), cancellation);
        NativeSession.EnemyHpTransition transition = session.EnemyHpTransitions.Last();
        NativeSession.EnemyDamageEvent damageEvent = transition.EnemyDamageEvents.Single(
            entry => entry.CombatId == bomb.CombatId);
        int unblockedDamage = damageEvent.UnblockedDamage;
        int overkillDamage = damageEvent.OverkillDamage;
        int creditedDamage = damageEvent.CreditedDamage;
        if (session.CombatStateForSimulation.Enemies.Contains(bomb)
            || unblockedDamage <= 0 || overkillDamage <= 0 || creditedDamage <= 0
            || transition.Damage != creditedDamage
            || predictedBranchDamage != creditedDamage || session.EnemyDamageLost != creditedDamage
            || session.Terminal || predicted.State.Terminal)
            throw new InvalidDataException(
                $"Native lethal overkill was not credited as actual enemy HP damage: "
                + $"targetHp={targetHpBefore}, unblocked={unblockedDamage}, overkill={overkillDamage}, "
                + $"credited={creditedDamage}, transition={transition.Damage}, "
                + $"predicted={predictedBranchDamage}, cumulative={session.EnemyDamageLost}, "
                + $"terminal={session.Terminal}, predictedTerminal={predicted.State.Terminal}.");
        double nativeUnresolved = session.EvaluateUnresolved();
        double predictedUnresolved = predicted.EvaluateUnresolved();
        double expectedUnresolved = -0.5 + 0.25 * creditedDamage / 80.0;
        if (Math.Abs(nativeUnresolved - predictedUnresolved) > 1e-9
            || Math.Abs(nativeUnresolved - expectedUnresolved) > 1e-9)
            throw new InvalidDataException("Lethal overkill unresolved reward differs.");
        predicted.Promote(bash);
        await predicted.RestoreAsync([], cancellation);
        if (predicted.State.EnemyHpLost != creditedDamage
            || predicted.RewardContext.CapturedEnemyDamagePrefix != 0)
            throw new InvalidDataException("Overkill Promote/Restore lost root-local actual damage.");
        using var recaptured = new CombatSolverReplayEnvironment();
        recaptured.Capture(session.CombatStateForSimulation, session.CaptureRewardSeed());
        session.BindTrajectoryRewardContext(recaptured.RewardContext);
        if (recaptured.RewardContext.TrajectoryId != firstContext.TrajectoryId
            || recaptured.RewardContext.CaptureId != 3
            || recaptured.RewardContext.CapturedEnemyDamagePrefix != creditedDamage
            || recaptured.RewardContext.InitialEnemyEffectiveHp != 80
            || recaptured.State.EnemyHpLost != 0
            || Math.Abs(recaptured.EvaluateUnresolved() - nativeUnresolved) > 1e-9)
            throw new InvalidDataException("Overkill recapture lost or double-counted its damage prefix.");
        return new
        {
            targetHpBefore, unblockedDamage, overkillDamage, creditedDamage,
            transition, context, predictedBranchDamage, nativeUnresolved, predictedUnresolved,
            recapture = recaptured.RewardContext,
            recapturedBranchDamage = recaptured.State.EnemyHpLost,
        };
    }

    private static async Task<object> CheckTerminalCleanupAsync(
        NativeSession session, CancellationToken cancellation)
    {
        await PrepareBombAsync(session, "AZ-TERMINAL-CLEANUP-RETAINED", cancellation);
        Creature fog = session.CombatStateForSimulation.Enemies.Single(enemy => enemy.Monster?.Id.Entry == "LIVING_FOG");
        Creature bomb = session.CombatStateForSimulation.Enemies.Single(enemy => enemy.Monster?.Id.Entry == "GAS_BOMB");
        await CreatureCmd.SetCurrentHp(fog, 6);
        using var predicted = new CombatSolverReplayEnvironment();
        predicted.Capture(session.CombatStateForSimulation, session.CaptureRewardSeed());
        session.BindTrajectoryRewardContext(predicted.RewardContext);
        var strike = predicted.RootActions.Single(action => action.Native.CardId == "STRIKE_IRONCLAD"
            && action.Native.TargetCombatId == fog.CombatId);
        await predicted.ApplyAsync(strike, cancellation);
        await session.StepAsync(session.ToLiveSearchAction(strike), cancellation);
        var transition = session.EnemyHpTransitions.Last();
        if (!session.Won || !predicted.State.Won || !transition.HistoryReset
            || transition.Before != 13 || transition.After != 0 || transition.Damage != 6
            || predicted.State.EnemyHpLost != 6 || session.EnemyDamageLost != 6
            || transition.EnemyDamageEvents.Sum(e => e.CreditedDamage) != 6
            || transition.EnemyDamageEvents.Any(e => e.CombatId == bomb.CombatId)
            || Math.Abs(session.EvaluateTerminal() - predicted.EvaluateTerminal()) > 1e-9)
            throw new InvalidDataException("Terminal cleanup counted summon disappearance as damage: "
                + JsonSerializer.Serialize(new { transition, session.Won, predicted.State,
                    session.EnemyDamageLost, nativeReward = session.EvaluateTerminal(),
                    predictedReward = predicted.EvaluateTerminal() }));
        return new { expectedActualDamage = 6, excludedCleanupHp = 7, transition,
            predictedDamage = predicted.State.EnemyHpLost, nativeDamage = session.EnemyDamageLost,
            nativeReward = session.EvaluateTerminal(), predictedReward = predicted.EvaluateTerminal() };
    }

    private static async Task<object> CheckDespawnLossAsync(
        NativeSession session, CancellationToken cancellation)
    {
        NativeMctsTrajectoryRewardContext firstContext = await PrepareBombAsync(
            session, "AZ-GAS-BOMB-DESPAWN-LOSS", cancellation);
        Creature bomb = session.CombatStateForSimulation.Enemies.Single(enemy =>
            enemy.Monster?.Id.Entry == "GAS_BOMB");
        await session.SetCurrentHpForRegressionAsync(1, cancellation);
        using var predicted = new CombatSolverReplayEnvironment();
        predicted.Capture(session.CombatStateForSimulation, session.CaptureRewardSeed());
        session.BindTrajectoryRewardContext(predicted.RewardContext);
        NativeMctsTrajectoryRewardContext context = predicted.RewardContext;
        int capturedPrefixDamage = context.CapturedEnemyDamagePrefix;
        if (context.TrajectoryId != firstContext.TrajectoryId || context.CaptureId != 2
            || context.EntryHp != firstContext.EntryHp || context.InitialEnemyEffectiveHp != 80
            || capturedPrefixDamage != 0)
            throw new InvalidDataException("Death Capture changed trajectory damage accounting.");
        var predictedEndTurn = predicted.RootActions.Single(action => action.Native.Kind == "EndTurn");
        await predicted.ApplyAsync(predictedEndTurn, cancellation);
        int predictedBranchDamage = predicted.State.EnemyHpLost;
        await session.StepAsync(session.Actions().Single(action =>
            action.Combat?.Kind == CombatActionKind.EndTurn), cancellation);
        NativeSession.EnemyHpTransition transition = session.EnemyHpTransitions.Last();
        bool liveDeath = session.Terminal && !session.Won && session.Hp == 0;
        int actualTotalDamage = session.EnemyDamageLost;
        if (!liveDeath || !predicted.State.Defeated
            || session.CombatStateForSimulation.Enemies.Contains(bomb)
            || transition.Before - transition.After != 7
            || transition.Damage != 0 || transition.EnemyDamageEvents.Count != 0
            || predictedBranchDamage != 0 || actualTotalDamage != capturedPrefixDamage)
            throw new InvalidDataException("Gas Bomb loss counted disappearance as damage or missed real death.");
        double nativeLoss = session.EvaluateTerminal();
        double predictedLoss = predicted.EvaluateTerminal();
        NativeMctsTerminalRewardInputs rewardInputs = predicted.TerminalRewardInputs();
        if (nativeLoss != -1.0 || Math.Abs(predictedLoss - nativeLoss) > 1e-9
            || rewardInputs.CapturedEnemyDamagePrefix != capturedPrefixDamage
            || rewardInputs.EnemyHpLost != predictedBranchDamage
            || rewardInputs.TotalEnemyHpLost != actualTotalDamage
            || Math.Abs(rewardInputs.Reward - nativeLoss) > 1e-9)
            throw new InvalidDataException("Gas Bomb real loss reward differs across native and prediction.");
        return new
        {
            liveDeath, capturedPrefixDamage, predictedBranchDamage,
            actualTotalDamage, nativeLoss, predictedLoss, context, transition, rewardInputs,
        };
    }
}
