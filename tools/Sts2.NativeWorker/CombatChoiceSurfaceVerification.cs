using CombatSolver.Api;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Potions;
using MegaCrit.Sts2.Core.Models.Powers;
using MegaCrit.Sts2.Core.Models.Relics;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;

internal static class CombatChoiceSurfaceVerification
{
    internal static async Task RunAsync(NativeSession session, CancellationToken cancellation)
    {
        VerifyChoiceSignatureCompatibility();
        await VerifyOpeningRelicAsync<Toolbox>(session, cancellation);
        await VerifyOpeningRelicAsync<ChoicesParadox>(session, cancellation);
        await VerifyOpeningRelicAsync<ToastyMittens>(session, cancellation);
        await VerifySeekerStrikeAsync(session, cancellation);
        await VerifyTurnPowerAsync<InfiniteBladesPower>(session, cancellation);
        await VerifyTurnPowerAsync<ForegoneConclusionPower>(session, cancellation);
        await VerifyTurnPowerAsync<StratagemPower>(session, cancellation);
        await VerifyTurnPowerAsync<EntropyPower>(session, cancellation);
        await VerifyTurnPowerAsync<ToolsOfTheTradePower>(session, cancellation);
        await VerifyTurnPowerAsync<TyrannyPower>(session, cancellation);
        await VerifyPotionAsync<BlockPotion>(session, expectsChoice: false, cancellation);
        await VerifyPotionAsync<AttackPotion>(session, expectsChoice: true, cancellation);
        await VerifyPotionAsync<SkillPotion>(session, expectsChoice: true, cancellation);
        await VerifyPotionAsync<PowerPotion>(session, expectsChoice: true, cancellation);
        await VerifyPotionAsync<ColorlessPotion>(session, expectsChoice: true, cancellation);
        await VerifyPotionAsync<Ashwater>(session, expectsChoice: true, cancellation);
        await VerifyPotionAsync<DropletOfPrecognition>(session, expectsChoice: true, cancellation);
        await VerifyPotionAsync<GamblersBrew>(session, expectsChoice: true, cancellation);
        await VerifyPotionAsync<LiquidMemories>(
            session, expectsChoice: true, cancellation, prepareDiscard: true);
        await VerifyPotionAsync<TouchOfInsanity>(session, expectsChoice: true, cancellation);

        session.Checkpoint = null;
        session.ChoiceFixture = false;
        session.ChoiceFixtureUpgradedCards.Clear();
        session.ChoiceFixtureCards =
            ["PURITY", "ARMAMENTS", "HEADBUTT", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD"];
        session.EnterRoomForVerification = null;
    }

    private static void VerifyChoiceSignatureCompatibility()
    {
        (string Predicted, string Native, bool Matches)[] cases =
        [
            ("1:1:A,B", "1:1:A,B", true),
            ("0:2:A,B", "0:2:A,B", true),
            ("1:1:A,B", "0:1:A,B", true),
            ("1:2:A,B", "0:2:A,B", false),
            ("0:1:A,B", "1:1:A,B", false),
            ("1:1:A,B", "0:1:A,C", false),
            ("1:1:A,B", "0:2:A,B", false),
        ];
        foreach (var test in cases)
        {
            if (CombatSolverReplayEnvironment.ChoiceSignaturesMatch(
                    test.Predicted, test.Native) != test.Matches)
            {
                throw new InvalidDataException(
                    $"Choice signature compatibility differs: predicted={test.Predicted} native={test.Native}.");
            }
        }
        Godot.GD.Print($"SLAY_WORKER_CHOICE_SIGNATURE_MATCH cases={cases.Length}");
    }

    private static async Task VerifyOpeningRelicAsync<TRelic>(
        NativeSession session,
        CancellationToken cancellation)
        where TRelic : RelicModel
    {
        session.Checkpoint = null;
        session.ChoiceFixture = false;
        session.CaptureOpeningRoot = true;
        session.EnterRoomForVerification = async (run, encounter) =>
        {
            run.Players.Single().AddRelicInternal(ModelDb.Relic<TRelic>().ToMutable());
            await RunManager.Instance.EnterRoomDebug(RoomType.Monster, model: encounter);
        };
        try
        {
            await session.ResetAsync($"MCTS-{typeof(TRelic).Name}-CHOICE", cancellation);
        }
        finally
        {
            session.CaptureOpeningRoot = false;
            session.EnterRoomForVerification = null;
        }

        if (!session.HasPendingChoice)
            throw new InvalidDataException($"{typeof(TRelic).Name} did not open a native combat choice.");
        using var simulation = new CombatSolverReplayEnvironment();
        simulation.Capture(session.OpeningRoot
            ?? throw new InvalidDataException($"{typeof(TRelic).Name} opening root was not captured."), session.Hp);
        RequireMatchingChoice(session, simulation, typeof(TRelic).Name);
        CombatSolverMctsAction selected = simulation.LegalActions()
            .OrderByDescending(action => action.Native.SelectedCards?.Count ?? 0)
            .First();
        await ApplyAndCompareAsync(session, simulation, selected, cancellation, typeof(TRelic).Name);
        Godot.GD.Print($"SLAY_WORKER_OPENING_CHOICE_MATCH source={typeof(TRelic).Name} full continuation");
    }

    private static async Task VerifySeekerStrikeAsync(
        NativeSession session,
        CancellationToken cancellation)
    {
        session.Checkpoint = null;
        session.ChoiceFixture = true;
        session.ChoiceFixtureCards =
        [
            "SEEKER_STRIKE", "SEEKER_STRIKE", "SEEKER_STRIKE", "SEEKER_STRIKE", "SEEKER_STRIKE",
            "STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH", "ARMAMENTS", "HEADBUTT",
        ];

        for (var attempt = 0; attempt < 16; attempt++)
        {
            await session.ResetAsync($"MCTS-SEEKER-CHOICE-{attempt}", cancellation);
            using var simulation = new CombatSolverReplayEnvironment();
            simulation.Capture(session.CombatStateForSimulation, session.Hp);
            CombatSolverMctsAction? seeker = simulation.LegalActions().FirstOrDefault(action =>
                action.Native.Kind == "PlayCard" && action.Native.CardId == "SEEKER_STRIKE");
            if (seeker is null)
                continue;

            await simulation.ApplyAsync(seeker, cancellation);
            await session.StepAsync(session.ToLiveSearchAction(seeker), cancellation);
            RequireMatchingChoice(session, simulation, "SeekerStrike");
            CombatSolverMctsAction selected = simulation.LegalActions()
                .OrderBy(action => action.Native.Key, StringComparer.Ordinal)
                .First();
            await ApplyAndCompareAsync(session, simulation, selected, cancellation, "SeekerStrike");
            Godot.GD.Print("SLAY_WORKER_CARD_CHOICE_MATCH source=SEEKER_STRIKE randomized draw subset, identity and full continuation");
            return;
        }

        throw new InvalidDataException("Could not produce a playable Seeker Strike fixture.");
    }

    private static async Task VerifyTurnPowerAsync<TPower>(
        NativeSession session,
        CancellationToken cancellation)
        where TPower : PowerModel
    {
        session.Checkpoint = null;
        session.ChoiceFixture = false;
        await session.ResetAsync($"MCTS-{typeof(TPower).Name}-CHOICE", cancellation);
        var player = session.CombatStateForSimulation.Players.Single();
        await PowerCmd.Apply<TPower>(
            new ThrowingPlayerChoiceContext(), player.Creature, 1, player.Creature, null);

        using var simulation = new CombatSolverReplayEnvironment();
        simulation.Capture(session.CombatStateForSimulation, session.Hp);
        CombatSolverMctsAction endTurn = simulation.LegalActions()
            .Single(action => action.Native.Kind == "EndTurn");
        await simulation.ApplyAsync(endTurn, cancellation);
        await session.StepAsync(session.ToLiveSearchAction(endTurn), cancellation);
        bool surfacedChoice = session.HasPendingChoice;
        bool simulatedChoice = simulation.ChoiceSignature.Length > 0;
        if (surfacedChoice != simulatedChoice)
            throw new InvalidDataException(
                $"{typeof(TPower).Name} choice boundary differs: " +
                $"native={session.ChoiceSignature} simulated={simulation.ChoiceSignature}.");
        if (surfacedChoice)
        {
            RequireMatchingChoice(session, simulation, typeof(TPower).Name);
            CombatSolverMctsAction selected = simulation.LegalActions()
                .OrderBy(action => action.Native.Key, StringComparer.Ordinal)
                .First();
            await ApplyAndCompareAsync(session, simulation, selected, cancellation, typeof(TPower).Name);
        }
        else
        {
            RequireContinuationMatch(session, simulation, typeof(TPower).Name);
        }
        Godot.GD.Print($"SLAY_WORKER_TURN_CHOICE_MATCH source={typeof(TPower).Name} " +
            $"surfaced={surfacedChoice} full continuation");
    }

    private static async Task VerifyPotionAsync<TPotion>(
        NativeSession session,
        bool expectsChoice,
        CancellationToken cancellation,
        bool prepareDiscard = false)
        where TPotion : PotionModel
    {
        session.Checkpoint = null;
        session.ChoiceFixture = false;
        session.EnterRoomForVerification = async (run, encounter) =>
        {
            var player = run.Players.Single();
            var potion = ModelDb.Potion<TPotion>().ToMutable();
            int slot = Enumerable.Range(0, player.PotionSlots.Count)
                .First(index => player.GetPotionAtSlotIndex(index) == null);
            if (!player.AddPotionInternal(potion, slot, silent: false).success)
                throw new InvalidDataException($"Could not inject {typeof(TPotion).Name}.");
            await RunManager.Instance.EnterRoomDebug(RoomType.Monster, model: encounter);
        };
        try
        {
            await session.ResetAsync($"MCTS-{typeof(TPotion).Name}-CHOICE", cancellation);
        }
        finally
        {
            session.EnterRoomForVerification = null;
        }

        if (prepareDiscard)
            await session.StepAsync(session.ActionForCard("DEFEND_IRONCLAD"), cancellation);

        using var simulation = new CombatSolverReplayEnvironment();
        simulation.Capture(session.CombatStateForSimulation, session.Hp);
        CombatSolverMctsAction potionAction = simulation.LegalActions().Single(action =>
            action.Native.Kind == "UsePotion" && action.Native.PotionId == ModelDb.Potion<TPotion>().Id.Entry);
        SearchAction livePotion = session.ToLiveSearchAction(potionAction);
        if (livePotion.Combat?.PotionIndex != potionAction.Native.PotionSlot)
            throw new InvalidDataException($"{typeof(TPotion).Name} physical slot was not preserved.");

        await simulation.ApplyAsync(potionAction, cancellation);
        await session.StepAsync(livePotion, cancellation);
        bool surfacedChoice = session.HasPendingChoice;
        bool simulatedChoice = simulation.ChoiceSignature.Length > 0;
        if (surfacedChoice != simulatedChoice)
            throw new InvalidDataException(
                $"{typeof(TPotion).Name} choice boundary differs: " +
                $"native={session.ChoiceSignature} simulated={simulation.ChoiceSignature}.");
        if (expectsChoice && surfacedChoice)
        {
            RequireMatchingChoice(session, simulation, typeof(TPotion).Name);
            CombatSolverMctsAction selected;
            if (typeof(TPotion) == typeof(GamblersBrew))
            {
                var checkpoint = NativeCombatCheckpoint.Latest
                    ?? throw new InvalidDataException("Missing potion choice checkpoint.");
                System.Environment.SetEnvironmentVariable(
                    "SLAY_THE_MODEL_WORKER_EXE", Godot.OS.GetExecutablePath());
                System.Environment.SetEnvironmentVariable(
                    "SLAY_THE_MODEL_WORKER_PROJECT", Godot.ProjectSettings.GlobalizePath("res://"));
                System.Environment.SetEnvironmentVariable(
                    "SLAY_THE_MODEL_EXPORT_DIR",
                    Path.Combine(Path.GetDirectoryName(Godot.OS.GetExecutablePath())!, "verification"));
                using var client = new NativeWorkerClient();
                NativeMctsResponse response = await client.SearchAsync(new NativeMctsRequest(
                    Guid.NewGuid(), checkpoint, [livePotion], session.StateKey(), session.Hp,
                    PreviousAction: livePotion, BudgetMilliseconds: 500), cancellation);
                int[] returned = response.Action?.Selection
                    ?? throw new InvalidDataException(
                        "Cold worker did not recover the potion card choice.");
                selected = simulation.LegalActions().Single(candidate =>
                    (session.ToLiveSearchAction(candidate).Selection ?? [])
                    .SequenceEqual(returned));
                Godot.GD.Print(
                    "SLAY_WORKER_POTION_RESTART_MATCH cold worker recovered suspended potion choice");
            }
            else
            {
                selected = simulation.LegalActions()
                    .OrderByDescending(action => action.Native.SelectedCards?.Count ?? 0)
                    .ThenBy(action => action.Native.Key, StringComparer.Ordinal)
                    .First();
            }
            await ApplyAndCompareAsync(session, simulation, selected, cancellation, typeof(TPotion).Name);
        }
        else
        {
            RequireContinuationMatch(session, simulation, typeof(TPotion).Name);
        }
        Godot.GD.Print($"SLAY_WORKER_POTION_CHOICE_MATCH source={typeof(TPotion).Name} " +
            $"choice={expectsChoice} surfaced={surfacedChoice} slot and full continuation");
    }

    private static void RequireMatchingChoice(
        NativeSession session,
        CombatSolverReplayEnvironment simulation,
        string source)
    {
        if (!session.HasPendingChoice || !CombatSolverReplayEnvironment.ChoiceSignaturesMatch(
                simulation.ChoiceSignature, session.ChoiceSignature))
        {
            throw new InvalidDataException(
                $"{source} choice differs: native={session.ChoiceSignature} " +
                $"simulated={simulation.ChoiceSignature} diagnostics={simulation.ChoiceDiagnostics}");
        }
        session.ValidateSimulationActions(simulation.LegalActions());
    }

    private static async Task ApplyAndCompareAsync(
        NativeSession session,
        CombatSolverReplayEnvironment simulation,
        CombatSolverMctsAction selected,
        CancellationToken cancellation,
        string source)
    {
        SearchAction live = session.ToLiveSearchAction(selected);
        await simulation.ApplyAsync(selected, cancellation);
        await session.StepAsync(live, cancellation);
        RequireContinuationMatch(session, simulation, source);
    }

    private static void RequireContinuationMatch(
        NativeSession session,
        CombatSolverReplayEnvironment simulation,
        string source)
    {
        string actual = NativeMctsSimulationApi.CaptureLiveContinuationKey(
            session.CombatStateForSimulation);
        if (simulation.CurrentContinuationKey != actual)
            throw new InvalidDataException($"{source} full continuation differs from native execution.");
    }
}
