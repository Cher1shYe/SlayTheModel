using System.Text.Json;
using CombatSolver.Api;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models.Powers;

public static partial class NativeVerification
{
    public static async Task HeadbuttAsync(NativeSession session, string outputPath, CancellationToken cancellation)
    {
        outputPath = Path.GetFullPath(outputPath);
        Directory.CreateDirectory(Path.GetDirectoryName(outputPath)!);
        if (File.Exists(outputPath)) throw new IOException($"Headbutt diagnostic already exists: {outputPath}");

        object lethal = await CheckHeadbuttCaseAsync(session, targetHp: 10, cancellation);
        object nonlethal = await CheckHeadbuttCaseAsync(session, targetHp: 40, cancellation);
        using var stream = new FileStream(outputPath, FileMode.CreateNew, FileAccess.Write);
        JsonSerializer.Serialize(stream, new
        {
            format = "azcombat.headbutt-boundary-regression.v1",
            regressionOnly = true,
            lethal,
            nonlethal,
        }, new JsonSerializerOptions { WriteIndented = true });
        Godot.GD.Print($"SLAY_WORKER_HEADBUTT_BOUNDARY_MATCH output={outputPath}");
    }

    private static async Task<object> CheckHeadbuttCaseAsync(
        NativeSession session, int targetHp, CancellationToken cancellation)
    {
        bool lethal = targetHp == 10;
        session.Checkpoint = null;
        session.Seed = lethal ? "AZ-HEADBUTT-LETHAL-REGRESSION" : "AZ-HEADBUTT-NONLETHAL-REGRESSION";
        session.EncounterId = "LIVING_FOG_NORMAL";
        session.ChoiceFixture = true;
        session.ChoiceFixtureCards =
            ["HEADBUTT", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH", "DEFEND_IRONCLAD"];
        session.ChoiceFixtureUpgradedCards.Clear();
        await session.ResetAsync(session.Seed, cancellation);

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
        environment.Capture(session.CombatStateForSimulation, session.EntryHp);
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
            double expectedReward = 0.5 + Math.Atan((session.Hp - session.EntryHp) / 20d) / Math.PI;
            if (Math.Abs(actualReward - expectedReward) > 1e-9)
                throw new InvalidDataException("Native terminal reward differs from the fixed reward contract.");
            return new
            {
                regressionOnly = true, targetHp, rootKey, actionId = headbutt.Key,
                strength = 20, vulnerable = 2, predictedBefore, liveBefore,
                probeBoundary, predictedAfter, liveTerminal = session.Terminal, liveWon = session.Won,
                livePlayerHp = session.Hp, transition, rngMatches,
                predictedAfterText, liveAfterText, actualReward,
                predictedPreTeardownReward = environment.EvaluateTerminal(),
            };
        }

        if (session.Terminal || !session.HasPendingChoice || predictedAfter.Terminal
            || !predictedAfter.PendingChoice || predictedAfter.LegalActions.Count < 1
            || probeBoundary.PlayerDead || probeBoundary.AllEnemiesDead
            || probeBoundary.TerminalStamp is not null || !probeBoundary.SimulatorIsInProgress
            || !probeBoundary.SimulatorHasPendingChoice || !probeBoundary.CombatHasPendingChoice)
            throw new InvalidDataException("Nonlethal Headbutt did not expose a real selection layer.");
        environment.Promote(headbutt);
        if (!environment.MatchesLiveRoot(session.CombatStateForSimulation, true, session.ChoiceSignature))
            throw new InvalidDataException("Nonlethal Headbutt choice root differs from live.");
        NativeMctsChoiceFrame frame = environment.CurrentChoiceFrame;
        session.ValidateChoiceFrame(frame);
        var selected = environment.RootActions.First();
        environment.Promote(selected);
        await session.StepAsync(session.ToLiveSearchAction(selected), cancellation);
        string predictedContinuation = environment.CurrentContinuationStateText;
        string liveContinuation = NativeMctsSimulationApi.CaptureLiveContinuationStateText(
            session.CombatStateForSimulation);
        if (session.Terminal || session.HasPendingChoice || environment.State.PendingChoice
            || environment.State.EnemyHpLost != transition.Damage
            || predictedContinuation != liveContinuation)
            throw new InvalidDataException("Nonlethal Headbutt selection continuation differs from live.");
        return new
        {
            regressionOnly = true, targetHp, rootKey, actionId = headbutt.Key,
            strength = 20, vulnerable = 2, predictedBefore, liveBefore,
            probeBoundary, predictedAfter, liveTerminal = session.Terminal, liveWon = session.Won,
            livePlayerHp = session.Hp, transition,
            choice = new { frame.Effect, frame.SourcePile, frame.MinCount, frame.MaxCount,
                frame.Ordered, candidates = frame.Candidates.Select(candidate => new {
                    candidate.CombatCardIndex, candidate.ModelId, candidate.UpgradeLevel }).ToArray(),
                selectedActionId = selected.Key },
            predictedContinuation, liveContinuation,
        };
    }

    private static string ContinuationField(string text, string name)
        => text.Split(';').Single(field => field.StartsWith(name + "=", StringComparison.Ordinal));
}
