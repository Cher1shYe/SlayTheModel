using System.Text.Json;
using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;

public static partial class NativeVerification
{
    public static async Task CombatSolverEndTurnAsync(NativeSession session, CancellationToken cancellation)
    {
        session.Checkpoint = null;
        session.ChoiceFixture = false;
        session.EncounterId = "CULTISTS_NORMAL";
        await session.ResetAsync("SOLVER-END-TURN", cancellation);
        using var environment = new CombatSolverReplayEnvironment();
        environment.Capture(session.CombatStateForSimulation, session.CaptureRewardSeed());
        session.BindTrajectoryRewardContext(environment.RewardContext);
        await environment.RestoreAsync([], cancellation);
        var endTurn = environment.LegalActions().Single(action => action.Native.Kind == "EndTurn");
        await environment.ApplyAsync(endTurn, cancellation);
        string predicted = environment.CurrentContinuationKey;
        await session.StepAsync(session.ToLiveSearchAction(endTurn), cancellation);
        string actual = CombatSolver.Api.NativeMctsSimulationApi
            .CaptureLiveContinuationKey(session.CombatStateForSimulation);
        if (predicted != actual)
            throw new InvalidDataException($"Combat Solver EndTurn differs from native execution. predicted={predicted} actual={actual}");
        Godot.GD.Print("SLAY_WORKER_COMBAT_SOLVER_END_TURN_MATCH enemy turn and next player turn matched native");
    }

    public static async Task ChoicesAsync(NativeSession session, CancellationToken cancellation)
    {
        var defend = MegaCrit.Sts2.Core.Models.ModelDb.AllCards.Single(card => card.Id.Entry == "DEFEND_IRONCLAD");
        if (NativeSession.FormatChoiceSignature(0, 2, new[] { defend }) != "0:1:DEFEND_IRONCLAD")
            throw new InvalidDataException("A native 0-2 choice with one option must align as an effective 0-1 choice.");

        session.Checkpoint = null;
        session.ChoiceFixture = true;
        await session.ResetAsync("CHOICE-FIXTURE", cancellation);
        var purity = session.ActionForCard("PURITY");
        await session.StepAsync(purity, cancellation);
        var choiceKey = session.Fingerprint();
        var choices = session.Actions();
        if (choices.Count != 15 || choices.Select(action => action.Key).Distinct().Count() != 15)
            throw new InvalidDataException("Purity should expose all 15 subsets of up to 3 of 4 cards.");
        var exhaust = choices.First(action => action.Selection?.Length == 3);
        await session.StepAsync(exhaust, cancellation);
        var exhaustedKey = session.Fingerprint();
        await session.RestoreAsync("CHOICE-FIXTURE", [purity], cancellation);
        if (session.Fingerprint() != choiceKey) throw new InvalidDataException("Pending choice replay diverged.");
        await session.StepAsync(exhaust, cancellation);
        if (session.Fingerprint() != exhaustedKey) throw new InvalidDataException("Choice effect replay diverged.");
        await session.RestoreAsync("CHOICE-FIXTURE", [purity], cancellation);
        await session.StepAsync(session.Actions().First(action => action.Selection?.Length == 0), cancellation);
        if (session.Fingerprint() == exhaustedKey) throw new InvalidDataException("Different selections collapsed to one state.");
        await session.StepAsync(session.ActionForCard("ARMAMENTS"), cancellation);
        if (!session.Actions().All(action => action.Selection?.Length == 1)) throw new InvalidDataException("Required upgrade choice missing.");
        await session.StepAsync(session.Actions()[0], cancellation);
        session.Seed = "CHOICE-FIXTURE";
        await session.ResetAsync("CHOICE-FIXTURE", cancellation);
        session.ChoiceFixture = false;
        Godot.GD.Print("SLAY_WORKER_CHOICES_MATCH purity=15 branches; alternate branch isolated; armaments resolved");
        await CombatSolverChoicesAsync(session, cancellation);
    }

    private static async Task CombatSolverChoicesAsync(NativeSession session, CancellationToken cancellation)
    {
        session.Checkpoint = null;
        session.ChoiceFixture = true;
        session.EncounterId = "CULTISTS_NORMAL";
        await session.ResetAsync("SOLVER-CHOICE-FIXTURE", cancellation);
        using var environment = new CombatSolverReplayEnvironment();
        environment.Capture(session.CombatStateForSimulation, session.CaptureRewardSeed());
        session.BindTrajectoryRewardContext(environment.RewardContext);
        await environment.RestoreAsync([], cancellation);
        var purity = environment.LegalActions().Single(action => action.Native.CardId == "PURITY");
        bool sawExpandedChoiceInput = false;
        var expansionTree = new SlayTheModel.Search.PolicyValueMcts<CombatSolverMctsAction,
            SlayTheModel.Sts2.Protocol.CombatObservation>(environment, (observation, legal) =>
        {
            if (environment.State.PendingChoice)
            {
                sawExpandedChoiceInput = true;
                var expected = environment.ObserveCurrent();
                if (JsonSerializer.Serialize(observation) != JsonSerializer.Serialize(expected)
                    || observation.Choice is null)
                    throw new InvalidDataException("Expanded choice node reached the actual tree evaluator without Choice context.");
            }
            return new SlayTheModel.Search.PolicyValuePrediction(new double[legal.Count], 0);
        }, seed: 20260925);
        await expansionTree.SearchAsync([], environment.RootKey, TimeSpan.FromSeconds(20),
            TimeSpan.FromSeconds(20), cancellation, maxSimulations: environment.RootActions.Count + 1);
        if (!sawExpandedChoiceInput)
            throw new InvalidDataException("Ordinary-root tree did not evaluate its newly expanded Purity choice node.");
        await environment.RestoreAsync([], cancellation);
        await environment.ApplyAsync(purity, cancellation);
        var choices = environment.LegalActions();
        if (choices.Count != 15 || choices.Any(action => action.Native.ChoiceKey == null))
            throw new InvalidDataException($"Combat Solver Purity should expose 15 independent choice nodes, observed {choices.Count}.");
        environment.Promote(purity);
        bool sawTreeChoiceInput = false;
        var choiceInputTree = new SlayTheModel.Search.PolicyValueMcts<CombatSolverMctsAction,
            SlayTheModel.Sts2.Protocol.CombatObservation>(environment, (observation, legal) =>
        {
            sawTreeChoiceInput = true;
            if (environment.State.PendingChoice)
            {
                var expected = environment.ObserveCurrent();
                if (JsonSerializer.Serialize(observation) != JsonSerializer.Serialize(expected)
                    || observation.Choice is null)
                throw new InvalidDataException("Actual tree evaluator received a choice root without Choice context.");
            }
            return new SlayTheModel.Search.PolicyValuePrediction(new double[legal.Count], 0);
        }, seed: 20260925);
        await choiceInputTree.SearchAsync([], environment.RootKey, TimeSpan.FromSeconds(10),
            TimeSpan.FromSeconds(10), cancellation, maxSimulations: 2);
        if (!sawTreeChoiceInput)
            throw new InvalidDataException("Choice root did not reach the actual tree evaluator.");
        await environment.RestoreAsync([], cancellation);
        if (JsonSerializer.Serialize(environment.ObserveCurrent())
            != JsonSerializer.Serialize(environment.CurrentChoiceFrame.ToPolicyObservation()))
            throw new InvalidDataException("Choice frame projection differs from the shared policy observation.");
        await VerifyChoiceReplayAsync(environment, cancellation);
        await session.StepAsync(session.ToLiveSearchAction(purity), cancellation);
        if (!environment.MatchesLiveRoot(session.CombatStateForSimulation, livePendingChoice: true,
                session.ChoiceSignature))
            throw new InvalidDataException("Combat Solver pending-choice root differs from native Purity choice state.");
        var selected = choices.First(action => action.Native.SelectedCards?.Count == 3);
        await environment.ApplyAsync(selected, cancellation);
        string predicted = environment.CurrentContinuationKey;
        await session.StepAsync(session.ToLiveSearchAction(selected), cancellation);
        string actual = CombatSolver.Api.NativeMctsSimulationApi
            .CaptureLiveContinuationKey(session.CombatStateForSimulation);
        if (predicted != actual)
            throw new InvalidDataException($"Combat Solver choice continuation differs from native execution. predicted={predicted} actual={actual}");
        session.ChoiceFixture = false;
        session.EncounterId = "CULTISTS_NORMAL";
        Godot.GD.Print("SLAY_WORKER_COMBAT_SOLVER_CHOICES_MATCH purity=15 independent nodes; continuation matched native");
        await BurningPactChoiceAsync(session, cancellation);
        await DarkEmbraceUppercutAsync(session, cancellation);
    }

    private static async Task VerifyChoiceReplayAsync(CombatSolverReplayEnvironment environment, CancellationToken cancellation)
    {
        string rootKey = environment.RootKey;
        var actions = environment.RootActions.ToArray();
        if (!environment.State.PendingChoice || actions.Select(action => action.Key).Distinct().Count() != actions.Length)
            throw new InvalidDataException("Expected a unique explicit choice root.");
        var successors = new Dictionary<string, string>();
        foreach (var action in actions.Concat(actions.Reverse()))
        {
            await environment.RestoreAsync([], cancellation);
            if (environment.StateKey() != rootKey)
                throw new InvalidDataException("Restored choice root changed.");
            await environment.ApplyAsync(action, cancellation);
            if (environment.State.PendingChoice || environment.StateKey() == rootKey)
                throw new InvalidDataException("Single-layer choice failed to advance.");
            string signature = environment.StateKey() + environment.CurrentContinuationKey;
            if (successors.TryGetValue(action.Key, out var previous) && previous != signature)
                throw new InvalidDataException("Choice sibling replay polluted a successor.");
            successors[action.Key] = signature;
        }
        await environment.RestoreAsync([], cancellation);
        Godot.GD.Print($"SLAY_WORKER_CHOICE_REPLAY_MATCH branches={actions.Length} forward/reverse restore matched");
    }

    private static async Task DarkEmbraceUppercutAsync(NativeSession session, CancellationToken cancellation)
    {
        session.Checkpoint = null;
        session.ChoiceFixture = true;
        session.EncounterId = "OVICOPTER_NORMAL";
        session.ChoiceFixtureCards =
            ["DARK_EMBRACE", "BLOODLETTING", "UPPERCUT", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD"];
        session.ChoiceFixtureUpgradedCards = ["UPPERCUT"];
        await session.ResetAsync("DARK-EMBRACE-UPPERCUT", cancellation);
        using var environment = new CombatSolverReplayEnvironment();
        environment.Capture(session.CombatStateForSimulation, session.CaptureRewardSeed());
        session.BindTrajectoryRewardContext(environment.RewardContext);
        foreach (string cardId in new[] { "DARK_EMBRACE", "BLOODLETTING", "UPPERCUT" })
        {
            var action = environment.LegalActions().First(candidate => candidate.Native.CardId == cardId);
            var predicted = environment.PredictSuccessor(action);
            await session.ApplyAsync(session.ToLiveSearchAction(action), cancellation);
            string actual = CombatSolver.Api.NativeMctsSimulationApi
                .CaptureLiveContinuationKey(session.CombatStateForSimulation);
            if (predicted.ContinuationKey != actual)
            {
                string expectedText = environment.PredictSuccessorStateText(action);
                string actualText = CombatSolver.Api.NativeMctsSimulationApi
                    .CaptureLiveContinuationStateText(session.CombatStateForSimulation);
                throw new InvalidDataException($"{cardId} continuation differs. " + FirstDifference(expectedText, actualText));
            }
            environment.Promote(action);
        }
        session.ChoiceFixtureUpgradedCards.Clear();
        session.ChoiceFixtureCards =
            ["PURITY", "ARMAMENTS", "HEADBUTT", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD"];
        session.ChoiceFixture = false;
        session.EncounterId = "CULTISTS_NORMAL";
        Godot.GD.Print("SLAY_WORKER_DARK_EMBRACE_UPPERCUT_MATCH three-card continuation matched native");
    }

    private static string FirstDifference(string expected, string actual)
    {
        int length = Math.Min(expected.Length, actual.Length);
        int index = 0;
        while (index < length && expected[index] == actual[index]) index++;
        int start = Math.Max(0, index - 120);
        return $"index={index} expected={expected.Substring(start, Math.Min(300, expected.Length - start))} "
            + $"actual={actual.Substring(start, Math.Min(300, actual.Length - start))}";
    }

    private static async Task BurningPactChoiceAsync(NativeSession session, CancellationToken cancellation)
    {
        session.Checkpoint = null;
        session.ChoiceFixture = true;
        session.ChoiceFixtureCards =
            ["BURNING_PACT", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH", "HEADBUTT"];
        await session.ResetAsync("BURNING-PACT-CHOICE", cancellation);
        using var environment = new CombatSolverReplayEnvironment();
        environment.Capture(session.CombatStateForSimulation, session.CaptureRewardSeed());
        session.BindTrajectoryRewardContext(environment.RewardContext);
        await environment.RestoreAsync([], cancellation);
        var play = environment.LegalActions().Single(action => action.Native.CardId == "BURNING_PACT");
        await environment.ApplyAsync(play, cancellation);
        var choices = environment.LegalActions();
        if (choices.Count == 0 || choices.Any(action => action.Native.ChoiceKey == null))
            throw new InvalidDataException("Burning Pact did not expose native MCTS selection nodes.");
        environment.Promote(play);
        await session.StepAsync(session.ToLiveSearchAction(play), cancellation);
        if (!environment.MatchesLiveRoot(session.CombatStateForSimulation, livePendingChoice: true,
                session.ChoiceSignature))
            throw new InvalidDataException("Burning Pact pending-choice roots differ.");
        var selected = choices[0];
        await environment.ApplyAsync(selected, cancellation);
        string predicted = environment.CurrentContinuationKey;
        await session.StepAsync(session.ToLiveSearchAction(selected), cancellation);
        string actual = CombatSolver.Api.NativeMctsSimulationApi
            .CaptureLiveContinuationKey(session.CombatStateForSimulation);
        if (predicted != actual)
            throw new InvalidDataException("Burning Pact choice continuation differs from native execution.");
        session.ChoiceFixtureCards =
            ["PURITY", "ARMAMENTS", "HEADBUTT", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD"];
        session.ChoiceFixture = false;
        Godot.GD.Print("SLAY_WORKER_BURNING_PACT_CHOICE_MATCH pending root and continuation matched native");
    }

    public static async Task IpcAsync(NativeSession session, NativeCombatCheckpoint checkpoint, CancellationToken cancellation)
    {
        session.Checkpoint = checkpoint;
        await session.RestoreAsync([], cancellation);
        var before = session.Fingerprint();
        System.Environment.SetEnvironmentVariable("SLAY_THE_MODEL_WORKER_EXE", Godot.OS.GetExecutablePath());
        System.Environment.SetEnvironmentVariable("SLAY_THE_MODEL_WORKER_PROJECT", Godot.ProjectSettings.GlobalizePath("res://"));
        System.Environment.SetEnvironmentVariable("SLAY_THE_MODEL_EXPORT_DIR", Path.Combine(Path.GetDirectoryName(Godot.OS.GetExecutablePath())!, "verification"));
        using var client = new NativeWorkerClient();
        var response = await client.SearchAsync(new NativeMctsRequest(Guid.NewGuid(), checkpoint, [], before, 80), cancellation);
        if (before != session.Fingerprint()) throw new InvalidDataException("Child search changed parent state.");
        var overlapping = Enumerable.Range(0, 8).Select(_ => client.SearchAsync(
            new NativeMctsRequest(Guid.NewGuid(), checkpoint, [], before, 80,
                BudgetMilliseconds: 50), cancellation)).ToArray();
        await Task.WhenAll(overlapping);
        if (overlapping.Any(task => task.Result.Action == null))
            throw new InvalidDataException("Overlapping IPC requests did not all produce an action.");
        var continued = await client.SearchAsync(new NativeMctsRequest(Guid.NewGuid(), checkpoint, [], before, 80), cancellation);
        if (continued.Rebuilt || continued.RetainedVisits == 0)
            throw new InvalidDataException("Repeated pondering did not retain the current root.");
        var action = continued.Action ?? throw new InvalidDataException("IPC returned no action.");
        var predicted = continued.NextStateKey ?? throw new InvalidDataException("IPC returned no predicted successor state.");
        await session.StepAsync(action, cancellation);
        if (predicted != session.Fingerprint())
            throw new InvalidDataException("IPC predicted successor differs from the executed native state.");
        var second = await client.SearchAsync(new NativeMctsRequest(Guid.NewGuid(), checkpoint, [action],
            session.Fingerprint(), 80, PreviousAction: action), cancellation);
        if (second.Rebuilt || second.RetainedVisits == 0)
            throw new InvalidDataException("IPC did not retain the matching subtree.");
        Godot.GD.Print("SLAY_WORKER_IPC_MATCH " + JsonSerializer.Serialize(new {
            response.SearchMilliseconds, response.Simulations, response.StateTransitions, response.SimulatorBackend,
            ponderMilliseconds = continued.SearchMilliseconds, ponderSimulations = continued.Simulations,
            ponderRetained = continued.RetainedVisits, nextMilliseconds = second.SearchMilliseconds,
            nextSimulations = second.Simulations, nextRetained = second.RetainedVisits }));
        session.Checkpoint = null;
    }

}
