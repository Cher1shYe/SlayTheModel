using System.Text.Json;
using CombatSolver.Api;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Powers;
using MegaCrit.Sts2.Core.Models.Relics;

public static partial class NativeVerification
{
    public static async Task CrossRootAsync(NativeSession session, string outputPath,
        CancellationToken cancellation)
    {
        outputPath = Path.GetFullPath(outputPath);
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
        if (File.Exists(outputPath))
            throw new IOException($"Cross-root diagnostic already exists: {outputPath}");
        object crossRoot = await CheckCrossRootRewardAsync(session, cancellation);
        using var stream = new FileStream(outputPath, FileMode.CreateNew, FileAccess.Write);
        JsonSerializer.Serialize(stream, new
        {
            format = "azcombat.cross-root-reward-regression.v1",
            regressionOnly = true,
            status = "passed",
            crossRoot,
        }, new JsonSerializerOptions { WriteIndented = true });
        Godot.GD.Print($"SLAY_WORKER_CROSS_ROOT_REWARD_MATCH output={outputPath}");
    }

    public static async Task HeadbuttAsync(NativeSession session, string outputPath, CancellationToken cancellation)
    {
        outputPath = Path.GetFullPath(outputPath);
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
        if (File.Exists(outputPath)) throw new IOException($"Headbutt diagnostic already exists: {outputPath}");

        object lethal = await CheckHeadbuttCaseAsync(session, targetHp: 10,
            startingHp: 57, burningBlood: true, cancellation);
        object capped = await CheckHeadbuttCaseAsync(session, targetHp: 10,
            startingHp: 78, burningBlood: true, cancellation);
        object noHeal = await CheckHeadbuttCaseAsync(session, targetHp: 10,
            startingHp: 57, burningBlood: false, cancellation);
        object nonlethal = await CheckHeadbuttCaseAsync(session, targetHp: 40,
            startingHp: 57, burningBlood: false, cancellation);
        object death = await CheckDeathRewardAsync(session, cancellation);
        object crossRoot = await CheckCrossRootRewardAsync(session, cancellation);
        object arithmetic = CheckTrajectoryRewardArithmetic();
        using var stream = new FileStream(outputPath, FileMode.CreateNew, FileAccess.Write);
        JsonSerializer.Serialize(stream, new
        {
            format = "azcombat.headbutt-boundary-regression.v1",
            regressionOnly = true,
            lethal,
            capped,
            noHeal,
            nonlethal,
            death,
            crossRoot,
            arithmetic,
        }, new JsonSerializerOptions { WriteIndented = true });
        Godot.GD.Print($"SLAY_WORKER_HEADBUTT_BOUNDARY_MATCH output={outputPath}");
    }

    private static async Task<object> CheckHeadbuttCaseAsync(
        NativeSession session, int targetHp, int startingHp,
        bool burningBlood, CancellationToken cancellation)
    {
        bool lethal = targetHp == 10;
        session.Checkpoint = null;
        session.Seed = $"AZ-HEADBUTT-{targetHp}-{startingHp}-{burningBlood}-REWARD";
        session.EncounterId = "LIVING_FOG_NORMAL";
        session.ChoiceFixture = true;
        session.ChoiceFixtureCards =
            ["HEADBUTT", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH", "DEFEND_IRONCLAD"];
        session.ChoiceFixtureUpgradedCards.Clear();
        await session.ResetAsync(session.Seed, cancellation);
        var player = session.CombatStateForSimulation.Players.Single();
        if (burningBlood)
        {
            if (!player.Relics.OfType<BurningBlood>().Any())
                await RelicCmd.Obtain(ModelDb.Relic<BurningBlood>().ToMutable(), player);
        }
        else
        {
            foreach (var relic in player.Relics.Where(relic => relic is BurningBlood or BlackBlood or MeatOnTheBone).ToArray())
                await RelicCmd.Remove(relic);
            if (player.Relics.Any(relic => relic is BurningBlood or BlackBlood or MeatOnTheBone))
                throw new InvalidDataException("No-heal reward fixture retained a healing relic.");
        }
        await session.SetInitialHpFixtureAsync(startingHp, cancellation);

        await session.StepAsync(session.ActionForCard("STRIKE_IRONCLAD"), cancellation);
        await session.StepAsync(session.ActionForCard("DEFEND_IRONCLAD"), cancellation);
        Creature enemy = session.CombatStateForSimulation.Enemies.Single();
        await CreatureCmd.SetCurrentHp(enemy, targetHp);
        await PowerCmd.Apply<StrengthPower>(new BlockingPlayerChoiceContext(), enemy, 20, enemy, null);
        await PowerCmd.Apply<VulnerablePower>(new BlockingPlayerChoiceContext(), enemy, 2, enemy, null);
        if (enemy.CurrentHp != targetHp || enemy.GetPower<StrengthPower>()?.Amount != 20
            || enemy.GetPower<VulnerablePower>()?.Amount != 2)
            throw new InvalidDataException("Headbutt strength/vulnerability/HP fixture did not settle.");
        session.BeginTrajectoryAtCurrentState();

        using var environment = new CombatSolverReplayEnvironment();
        environment.Capture(session.CombatStateForSimulation, session.CaptureRewardSeed());
        session.BindTrajectoryRewardContext(environment.RewardContext);
        string rootKey = environment.RootKey;
        string predictedBefore = environment.CurrentContinuationStateText;
        string liveBefore = NativeMctsSimulationApi.CaptureLiveContinuationStateText(
            session.CombatStateForSimulation);
        if (predictedBefore != liveBefore)
            throw new InvalidDataException("Headbutt pre-action piles/RNG/continuation differ.");
        var headbutt = environment.RootActions.Single(action => action.Native.CardId == "HEADBUTT");
        if (headbutt.Native.TargetHp != targetHp)
            throw new InvalidDataException("Headbutt did not target the configured enemy HP.");
        await environment.ApplyAsync(headbutt, cancellation);
        NativeMctsState predictedAfter = environment.State;
        NativeMctsProbeBoundaryDiagnostic probeBoundary = environment.LastProbeBoundary
            ?? throw new InvalidDataException("Headbutt action has no predicted probe boundary.");
        await session.StepAsync(session.ToLiveSearchAction(headbutt), cancellation);
        NativeSession.EnemyHpTransition transition = session.EnemyHpTransitions.Single();
        if (transition.Before != targetHp || transition.Damage <= 0
            || transition.After != Math.Max(0, targetHp - transition.Damage)
            || lethal && predictedAfter.EnemyHpLost != transition.Damage)
            throw new InvalidDataException("Headbutt live/predicted enemy HP damage differs.");

        if (lethal)
        {
            if (!session.Terminal || !session.Won || !predictedAfter.Terminal
                || !predictedAfter.Won || !predictedAfter.Resolved || predictedAfter.PendingChoice
                || probeBoundary.PlayerDead || !probeBoundary.AllEnemiesDead
                || probeBoundary.TerminalStamp is null || probeBoundary.SimulatorIsInProgress
                || probeBoundary.SimulatorHasPendingChoice || probeBoundary.CombatHasPendingChoice
                || transition.After != 0 || predictedAfter.LegalActions.Count != 0)
                throw new InvalidDataException("Lethal Headbutt kept a choice or failed to settle victory.");
            string predictedAfterText = environment.CurrentContinuationStateText;
            string liveAfterText = NativeMctsSimulationApi.CaptureLiveContinuationStateText(
                session.CombatStateForSimulation);
            bool rngMatches = ContinuationField(predictedAfterText, "R")
                == ContinuationField(liveAfterText, "R");
            if (!rngMatches) throw new InvalidDataException("Lethal Headbutt advanced the wrong RNG stream.");
            double actualReward = session.EvaluateTerminal();
            NativeMctsTerminalRewardInputs rewardInputs = environment.TerminalRewardInputs();
            double expectedReward = 0.5 + Math.Atan((session.Hp - session.EntryHp) / 20d) / Math.PI;
            if (Math.Abs(actualReward - expectedReward) > 1e-9)
                throw new InvalidDataException("Native terminal reward differs from the fixed reward contract.");
            if (Math.Abs(rewardInputs.Reward - actualReward) > 1e-9
                || rewardInputs.EntryHp != session.EntryHp
                || rewardInputs.CombatFinalHp != predictedAfter.PlayerHp
                || rewardInputs.SettledFinalHp != session.Hp
                || rewardInputs.AppliedPostCombatHeal != session.Hp - predictedAfter.PlayerHp)
                throw new InvalidDataException(
                    $"Predicted terminal reward differs from native settled label: "
                    + $"predicted={rewardInputs.Reward:R} native={actualReward:R} "
                    + $"entryHp={session.EntryHp} predictedCombatHp={predictedAfter.PlayerHp} "
                    + $"nativeSettledHp={session.Hp}.");
            return new
            {
                regressionOnly = true, targetHp, startingHp, burningBlood,
                rootKey, actionId = headbutt.Key,
                strength = 20, vulnerable = 2, predictedBefore, liveBefore,
                probeBoundary, predictedAfter, liveTerminal = session.Terminal, liveWon = session.Won,
                livePlayerHp = session.Hp, transition, rngMatches,
                predictedAfterText, liveAfterText, actualReward, rewardInputs,
            };
        }

        if (session.Terminal || !session.HasPendingChoice || predictedAfter.Terminal
            || !predictedAfter.PendingChoice || predictedAfter.LegalActions.Count < 1
            || probeBoundary.PlayerDead || probeBoundary.AllEnemiesDead
            || probeBoundary.TerminalStamp is not null || !probeBoundary.SimulatorIsInProgress
            || !probeBoundary.SimulatorHasPendingChoice || !probeBoundary.CombatHasPendingChoice)
            throw new InvalidDataException("Nonlethal Headbutt did not expose a real selection layer.");
        int originalEntryHp = environment.CapturedEntryHp;
        environment.Promote(headbutt);
        int promotedEntryHp = environment.CapturedEntryHp;
        if (promotedEntryHp != originalEntryHp || promotedEntryHp != session.EntryHp)
            throw new InvalidDataException("Promoted choice root changed the combat entry HP baseline.");
        if (!environment.MatchesLiveRoot(session.CombatStateForSimulation, true, session.ChoiceSignature))
            throw new InvalidDataException("Nonlethal Headbutt choice root differs from live.");
        NativeMctsChoiceFrame frame = environment.CurrentChoiceFrame;
        session.ValidateChoiceFrame(frame);
        var selected = environment.RootActions.First();
        environment.Promote(selected);
        await environment.RestoreAsync([], cancellation);
        int restoredEntryHp = environment.CapturedEntryHp;
        if (restoredEntryHp != originalEntryHp || restoredEntryHp != session.EntryHp)
            throw new InvalidDataException("Restored choice root changed the combat entry HP baseline.");
        await session.StepAsync(session.ToLiveSearchAction(selected), cancellation);
        string predictedContinuation = environment.CurrentContinuationStateText;
        string liveContinuation = NativeMctsSimulationApi.CaptureLiveContinuationStateText(
            session.CombatStateForSimulation);
        if (session.Terminal || session.HasPendingChoice || environment.State.PendingChoice
            || environment.State.EnemyHpLost != transition.Damage
            || predictedContinuation != liveContinuation)
            throw new InvalidDataException("Nonlethal Headbutt selection continuation differs from live.");
        double nativeUnresolved = session.EvaluateUnresolved();
        double predictedUnresolved = environment.EvaluateUnresolved();
        double expectedUnresolved = -0.5 + 0.25 * Math.Clamp(
            transition.Damage / (double)Math.Max(targetHp, 1), 0, 1);
        if (Math.Abs(nativeUnresolved - predictedUnresolved) > 1e-9
            || Math.Abs(nativeUnresolved - expectedUnresolved) > 1e-9)
            throw new InvalidDataException("Unresolved reward differs from native label.");
        using var laterRoot = new CombatSolverReplayEnvironment();
        laterRoot.Capture(session.CombatStateForSimulation, session.CaptureRewardSeed());
        session.BindTrajectoryRewardContext(laterRoot.RewardContext);
        if (laterRoot.CapturedEntryHp != originalEntryHp)
            throw new InvalidDataException("A later decision root changed the combat entry HP baseline.");
        return new
        {
            regressionOnly = true, targetHp, startingHp, burningBlood,
            rootKey, actionId = headbutt.Key,
            strength = 20, vulnerable = 2, predictedBefore, liveBefore,
            probeBoundary, predictedAfter, liveTerminal = session.Terminal, liveWon = session.Won,
            livePlayerHp = session.Hp, transition,
            choice = new { frame.Effect, frame.SourcePile, frame.MinCount, frame.MaxCount,
                frame.Ordered, candidates = frame.Candidates.Select(candidate => new {
                    candidate.CombatCardIndex, candidate.ModelId, candidate.UpgradeLevel }).ToArray(),
                selectedActionId = selected.Key },
            predictedContinuation, liveContinuation,
            originalEntryHp, promotedEntryHp, restoredEntryHp,
            recapturedLaterEntryHp = laterRoot.CapturedEntryHp,
            unresolved = new { session.EntryHp, combatHp = environment.State.PlayerHp,
                liveHp = session.Hp, environment.State.EnemyHpLost,
                environment.State.EnemyHpTotal, predictedUnresolved, nativeUnresolved },
        };
    }

    private static async Task<object> CheckDeathRewardAsync(
        NativeSession session, CancellationToken cancellation)
    {
        session.Checkpoint = null;
        session.Seed = "AZ-TERMINAL-DEATH-REWARD-REGRESSION";
        session.EncounterId = "LIVING_FOG_NORMAL";
        session.ChoiceFixture = false;
        await session.ResetAsync(session.Seed, cancellation);
        await session.SetInitialHpFixtureAsync(1, cancellation);
        using var environment = new CombatSolverReplayEnvironment();
        environment.Capture(session.CombatStateForSimulation, session.CaptureRewardSeed());
        session.BindTrajectoryRewardContext(environment.RewardContext);
        var endTurn = environment.RootActions.Single(action => action.Native.Kind == "EndTurn");
        await environment.ApplyAsync(endTurn, cancellation);
        await session.StepAsync(session.ToLiveSearchAction(endTurn), cancellation);
        if (!session.Terminal || session.Won || !environment.State.Terminal
            || !environment.State.Defeated || environment.State.Won)
            throw new InvalidDataException("Death reward fixture did not reach matching loss states.");
        NativeMctsTerminalRewardInputs rewardInputs = environment.TerminalRewardInputs();
        double actualReward = session.EvaluateTerminal();
        double expectedReward = -1.0 + 0.25 * Math.Clamp(
            rewardInputs.EnemyHpLost / (double)Math.Max(rewardInputs.EnemyHpTotal, 1), 0, 1);
        if (rewardInputs.Outcome != "loss" || rewardInputs.AppliedPostCombatHeal != 0
            || rewardInputs.SettledFinalHp != rewardInputs.CombatFinalHp
            || Math.Abs(rewardInputs.Reward - actualReward) > 1e-9
            || Math.Abs(actualReward - expectedReward) > 1e-9)
            throw new InvalidDataException("Predicted death reward differs from native settled label.");
        return new { regressionOnly = true, entryHp = session.EntryHp,
            liveSettledHp = session.Hp, rewardInputs, actualReward };
    }

    private static object CheckTrajectoryRewardArithmetic()
    {
        var context = new NativeMctsTrajectoryRewardContext(
            "ARITHMETIC-CONTROL", 1, "ARITHMETIC-BOUNDARY",
            EntryHp: 80, InitialEnemyEffectiveHp: 100,
            CapturedEnemyDamagePrefix: 60);
        int total = context.TotalEnemyHpLost(branchEnemyHpLost: 10);
        double loss = NativeMctsReward.Score(false, true, context.EntryHp, 0,
            total, context.InitialEnemyEffectiveHp);
        double unresolved = NativeMctsReward.Score(false, false, context.EntryHp, 80,
            total, context.InitialEnemyEffectiveHp);
        if (total != 70 || Math.Abs(loss - -0.825) > 1e-12
            || Math.Abs(unresolved - -0.325) > 1e-12)
            throw new InvalidDataException(
                $"Trajectory reward arithmetic control failed: total={total} loss={loss:R} unresolved={unresolved:R}");
        return new
        {
            regressionOnly = true, initialEnemyHp = context.InitialEnemyEffectiveHp,
            capturedPrefixDamage = context.CapturedEnemyDamagePrefix,
            branchDamage = 10, totalEnemyHpLost = total, loss, unresolved,
        };
    }

    private static async Task<object> CheckCrossRootRewardAsync(
        NativeSession session, CancellationToken cancellation)
    {
        session.Checkpoint = null;
        session.Seed = "AZ-CROSS-ROOT-REWARD-REGRESSION";
        session.EncounterId = "LIVING_FOG_NORMAL";
        session.ChoiceFixture = true;
        session.ChoiceFixtureCards =
            ["STRIKE_IRONCLAD", "BASH", "DEFEND_IRONCLAD", "DEFEND_IRONCLAD", "DEFEND_IRONCLAD"];
        session.ChoiceFixtureUpgradedCards.Clear();
        await session.ResetAsync(session.Seed, cancellation);
        session.BeginTrajectoryAtCurrentState();
        const int decisionCap = 2;
        long decisionsBefore = session.Transitions;
        int initialEnemyHpFromLive = session.CombatStateForSimulation.Enemies
            .Sum(enemy => Math.Max(enemy.CurrentHp, 0));
        if (initialEnemyHpFromLive < 1 || session.InitialEnemyRawHp != initialEnemyHpFromLive)
            throw new InvalidDataException("Cross-root fixture has no independent live initial enemy HP.");

        using var firstRoot = new CombatSolverReplayEnvironment();
        firstRoot.Capture(session.CombatStateForSimulation, session.CaptureRewardSeed());
        session.BindTrajectoryRewardContext(firstRoot.RewardContext);
        NativeMctsTrajectoryRewardContext firstContext = firstRoot.RewardContext;
        if (firstContext.CaptureId != 1 || firstContext.CapturedEnemyDamagePrefix != 0
            || firstContext.InitialEnemyEffectiveHp != initialEnemyHpFromLive
            || firstContext.EntryHp != session.EntryHp
            || firstContext.CaptureBoundaryKey != NativeMctsSimulationApi.CaptureLiveContinuationKey(
                session.CombatStateForSimulation))
            throw new InvalidDataException("Initial cross-root Capture context differs from the live trajectory.");
        var strike = firstRoot.RootActions.Single(action => action.Native.CardId == "STRIKE_IRONCLAD");
        firstRoot.Promote(strike);
        await session.StepAsync(session.ToLiveSearchAction(strike), cancellation);
        NativeSession.EnemyHpTransition prefixTransition = session.EnemyHpTransitions.Single();
        int prefixDamage = prefixTransition.Before - prefixTransition.After;
        if (prefixDamage <= 0 || prefixDamage != prefixTransition.Damage
            || prefixDamage != session.EnemyDamageLost
            || prefixTransition.Before != initialEnemyHpFromLive
            || firstRoot.State.EnemyHpLost != prefixDamage
            || session.Terminal || session.HasPendingChoice)
            throw new InvalidDataException("Cross-root fixture did not create a nonzero stable damage prefix.");

        await session.SetCurrentHpForRegressionAsync(1, cancellation);
        using var secondRoot = new CombatSolverReplayEnvironment();
        secondRoot.Capture(session.CombatStateForSimulation, session.CaptureRewardSeed());
        session.BindTrajectoryRewardContext(secondRoot.RewardContext);
        NativeMctsTrajectoryRewardContext secondContext = secondRoot.RewardContext;
        if (secondContext.TrajectoryId != firstContext.TrajectoryId
            || secondContext.CaptureId != firstContext.CaptureId + 1
            || secondContext.CaptureBoundaryKey != NativeMctsSimulationApi.CaptureLiveContinuationKey(
                session.CombatStateForSimulation)
            || secondContext.CapturedEnemyDamagePrefix != prefixDamage
            || secondContext.InitialEnemyEffectiveHp != initialEnemyHpFromLive
            || secondContext.EntryHp != firstContext.EntryHp
            || secondRoot.State.EnemyHpLost != 0
            || secondRoot.State.EnemyHpTotal != prefixTransition.After)
            throw new InvalidDataException("Cross-root trajectory reward context was reset or changed.");

        var sibling = secondRoot.RootActions.FirstOrDefault(action =>
            action.Native.Kind == "PlayCard" && action.Native.CardId == "DEFEND_IRONCLAD")
            ?? throw new InvalidDataException("Cross-root sibling Restore fixture has no Defend action.");
        _ = secondRoot.PredictSuccessor(sibling);
        await secondRoot.RestoreAsync([], cancellation);
        if (secondRoot.State.EnemyHpLost != 0
            || secondRoot.RewardContext.CapturedEnemyDamagePrefix != prefixDamage)
            throw new InvalidDataException("Sibling restore duplicated or leaked cross-root damage.");

        var bash = secondRoot.RootActions.Single(action => action.Native.CardId == "BASH");
        await secondRoot.ApplyAsync(bash, cancellation);
        NativeMctsState afterBranch = secondRoot.State;
        await session.StepAsync(session.ToLiveSearchAction(bash), cancellation);
        NativeSession.EnemyHpTransition branchTransition = session.EnemyHpTransitions.Last();
        int branchDamage = branchTransition.Before - branchTransition.After;
        int totalDamageFromLive = checked(prefixDamage + branchDamage);
        if (branchDamage <= 0 || branchDamage != branchTransition.Damage
            || branchTransition.Before != prefixTransition.After
            || totalDamageFromLive != session.EnemyDamageLost
            || afterBranch.Terminal || afterBranch.PendingChoice
            || session.Terminal || session.HasPendingChoice
            || afterBranch.EnemyHpLost != branchDamage
            || afterBranch.EnemyHpTotal != prefixTransition.After)
            throw new InvalidDataException(
                $"Cross-root branch damage differs: livePrefix={prefixDamage} "
                + $"liveBranch={branchDamage} predictedBranch={afterBranch.EnemyHpLost}.");
        long executedAtCap = session.Transitions - decisionsBefore;
        if (executedAtCap != decisionCap)
            throw new InvalidDataException("Cross-root unresolved boundary is not the registered decision cap.");

        NativeMctsTerminalRewardInputs unresolvedInputs = secondRoot.UnresolvedRewardInputs();
        double expectedUnresolved = -0.5 + 0.25 * Math.Clamp(
            totalDamageFromLive / (double)initialEnemyHpFromLive, 0, 1);
        double nativeUnresolved = session.EvaluateUnresolved();
        if (unresolvedInputs.Outcome != "unresolved"
            || unresolvedInputs.TrajectoryId != firstContext.TrajectoryId
            || unresolvedInputs.CaptureId != secondContext.CaptureId
            || unresolvedInputs.CaptureBoundaryKey != secondContext.CaptureBoundaryKey
            || unresolvedInputs.TrajectoryInitialEnemyHp != initialEnemyHpFromLive
            || unresolvedInputs.CapturedEnemyDamagePrefix != prefixDamage
            || unresolvedInputs.EnemyHpLost != branchDamage
            || unresolvedInputs.TotalEnemyHpLost != totalDamageFromLive
            || Math.Abs(unresolvedInputs.Reward - nativeUnresolved) > 1e-9
            || Math.Abs(nativeUnresolved - expectedUnresolved) > 1e-9)
            throw new InvalidDataException("Decision-cap unresolved reward differs from independent live damage.");

        secondRoot.Promote(bash);
        await secondRoot.RestoreAsync([], cancellation);
        if (secondRoot.State.EnemyHpLost != branchDamage
            || secondRoot.RewardContext.CapturedEnemyDamagePrefix != prefixDamage
            || Math.Abs(secondRoot.EvaluateUnresolved() - expectedUnresolved) > 1e-9)
            throw new InvalidDataException("Promote/Restore lost or duplicated root-local branch damage.");

        using var thirdRoot = new CombatSolverReplayEnvironment();
        thirdRoot.Capture(session.CombatStateForSimulation, session.CaptureRewardSeed());
        session.BindTrajectoryRewardContext(thirdRoot.RewardContext);
        NativeMctsTrajectoryRewardContext thirdContext = thirdRoot.RewardContext;
        if (thirdContext.TrajectoryId != firstContext.TrajectoryId
            || thirdContext.CaptureId != secondContext.CaptureId + 1
            || thirdContext.CaptureBoundaryKey != NativeMctsSimulationApi.CaptureLiveContinuationKey(
                session.CombatStateForSimulation)
            || thirdContext.EntryHp != firstContext.EntryHp
            || thirdContext.InitialEnemyEffectiveHp != initialEnemyHpFromLive
            || thirdContext.CapturedEnemyDamagePrefix != totalDamageFromLive
            || thirdRoot.State.EnemyHpLost != 0
            || thirdRoot.State.EnemyHpTotal != branchTransition.After
            || Math.Abs(thirdRoot.EvaluateUnresolved() - expectedUnresolved) > 1e-9)
            throw new InvalidDataException("Third Capture did not transfer branch damage into the prefix once.");

        var endTurn = secondRoot.RootActions.Single(action => action.Native.Kind == "EndTurn");
        var thirdRootEndTurn = thirdRoot.RootActions.Single(action => action.Native.Kind == "EndTurn");
        secondRoot.Promote(endTurn);
        await thirdRoot.ApplyAsync(thirdRootEndTurn, cancellation);
        await secondRoot.RestoreAsync([], cancellation);
        if (secondRoot.RewardContext.CapturedEnemyDamagePrefix != prefixDamage
            || secondRoot.State.EnemyHpLost != branchDamage)
            throw new InvalidDataException("Terminal Promote/Restore changed the branch damage ledger.");
        await session.StepAsync(session.ToLiveSearchAction(endTurn), cancellation);
        if (!session.Terminal || session.Won || !secondRoot.State.Defeated
            || !thirdRoot.State.Defeated || session.Hp != 0
            || secondRoot.State.PlayerHp != 0 || thirdRoot.State.PlayerHp != 0
            || session.EnemyDamageLost != totalDamageFromLive)
            throw new InvalidDataException("Cross-root fixture did not reach a real death.");

        NativeMctsTerminalRewardInputs rewardInputs = secondRoot.TerminalRewardInputs();
        NativeMctsTerminalRewardInputs recapturedRewardInputs = thirdRoot.TerminalRewardInputs();
        double actualReward = session.EvaluateTerminal();
        double expectedLoss = -1.0 + 0.25 * Math.Clamp(
            totalDamageFromLive / (double)initialEnemyHpFromLive, 0, 1);
        if (rewardInputs.Outcome != "loss" || recapturedRewardInputs.Outcome != "loss"
            || rewardInputs.EntryHp != firstContext.EntryHp
            || recapturedRewardInputs.EntryHp != firstContext.EntryHp
            || rewardInputs.CombatFinalHp != 0 || recapturedRewardInputs.CombatFinalHp != 0
            || rewardInputs.SettledFinalHp != session.Hp
            || recapturedRewardInputs.SettledFinalHp != session.Hp
            || rewardInputs.AppliedPostCombatHeal != 0
            || recapturedRewardInputs.AppliedPostCombatHeal != 0
            || rewardInputs.CapturedEnemyDamagePrefix != prefixDamage
            || rewardInputs.EnemyHpLost != branchDamage
            || rewardInputs.EnemyHpTotal != prefixTransition.After
            || rewardInputs.TotalEnemyHpLost != totalDamageFromLive
            || rewardInputs.TrajectoryInitialEnemyHp != initialEnemyHpFromLive
            || rewardInputs.TrajectoryId != firstContext.TrajectoryId
            || rewardInputs.CaptureId != secondContext.CaptureId
            || rewardInputs.CaptureBoundaryKey != secondContext.CaptureBoundaryKey
            || recapturedRewardInputs.TrajectoryId != firstContext.TrajectoryId
            || recapturedRewardInputs.CaptureId != thirdContext.CaptureId
            || recapturedRewardInputs.CaptureBoundaryKey != thirdContext.CaptureBoundaryKey
            || recapturedRewardInputs.CapturedEnemyDamagePrefix != totalDamageFromLive
            || recapturedRewardInputs.EnemyHpLost != 0
            || recapturedRewardInputs.TotalEnemyHpLost != totalDamageFromLive
            || recapturedRewardInputs.TrajectoryInitialEnemyHp != initialEnemyHpFromLive
            || Math.Abs(rewardInputs.Reward - actualReward) > 1e-9
            || Math.Abs(recapturedRewardInputs.Reward - actualReward) > 1e-9
            || Math.Abs(actualReward - expectedLoss) > 1e-9)
            throw new InvalidDataException("Cross-root terminal reward did not use prefix plus root-local damage once.");
        return new
        {
            regressionOnly = true,
            trajectoryId = firstContext.TrajectoryId,
            initialEnemyHp = initialEnemyHpFromLive,
            entryHp = firstContext.EntryHp,
            firstCapture = firstContext,
            secondCapture = secondContext,
            thirdCapture = thirdContext,
            prefixTransition,
            branchTransition,
            liveEnemyHpTransitions = session.EnemyHpTransitions.ToArray(),
            capturedPrefixDamage = prefixDamage,
            branchDamage,
            totalEnemyHpLost = totalDamageFromLive,
            unresolvedAtDecisionCap = new
            {
                regressionOnly = true,
                decisionCap,
                executedDecisions = executedAtCap,
                terminationReason = "decision_cap",
                expectedUnresolved,
                nativeUnresolved,
                rewardInputs = unresolvedInputs,
            },
            liveSettledHp = session.Hp,
            actualReward, expectedLoss, recapturedRewardInputs,
            rewardInputs,
        };
    }

    private static string ContinuationField(string text, string name)
        => text.Split(';').Single(field => field.StartsWith(name + "=", StringComparison.Ordinal));
}
