using CombatSolver.Api;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Potions;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Search;
using SlayTheModel.Sts2.Protocol;

internal static class CombatPotionCatalogVerification
{
    private const string AutomaticPotionId = "FAIRY_IN_A_BOTTLE";
    private const string DeprecatedPotionId = "DEPRECATED_POTION";
    private const string TestPotionId = "MOCK_DISCARD_AND_ADD_SHIVS_POTION";

    internal static async Task RunAsync(NativeSession session, CancellationToken cancellation)
    {
        (string Id, string Type)[] catalog = ModelDb.AllPotions
            .Select(potion => (Id: potion.Id.Entry, Type: potion.GetType().Name))
            .OrderBy(potion => potion.Id, StringComparer.Ordinal)
            .ToArray();
        string[] duplicateIds = catalog.GroupBy(potion => potion.Id, StringComparer.Ordinal)
            .Where(group => group.Count() != 1)
            .Select(group => group.Key)
            .ToArray();
        if (duplicateIds.Length > 0)
            throw new InvalidDataException(
                $"Potion catalog contains duplicate IDs: {string.Join(',', duplicateIds)}.");
        Godot.GD.Print(
            $"SLAY_WORKER_POTION_CATALOG ids={string.Join(',', catalog.Select(potion => potion.Id))}");

        var verified = new HashSet<string>(StringComparer.Ordinal);
        foreach ((string potionId, string potionType) in catalog)
        {
            if (potionId is AutomaticPotionId or DeprecatedPotionId or TestPotionId)
                await VerifyNonManualPotionBoundaryAsync(session, potionId, potionType, cancellation);
            else
                await VerifyManualPotionAsync(session, potionId, potionType, cancellation);
            verified.Add(potionId);
        }

        if (!verified.SetEquals(catalog.Select(potion => potion.Id)))
            throw new InvalidDataException("Potion catalog verification did not cover every native potion ID.");

        await VerifyReplayMctsVisitsPotionAsync(session, cancellation);
        ResetFixture(session);
        Godot.GD.Print(
            $"SLAY_WORKER_POTION_CATALOG_MATCH total={catalog.Length} " +
            $"gameplayManual={catalog.Length - 3} automatic=1 internal=2 all native potion IDs covered");
    }

    private static async Task VerifyManualPotionAsync(
        NativeSession session,
        string potionId,
        string potionType,
        CancellationToken cancellation)
    {
        await ResetWithPotionAsync(session, potionId, cancellation);
        if (potionId == "LIQUID_MEMORIES")
            await session.StepAsync(session.ActionForCard("DEFEND_IRONCLAD"), cancellation);

        using var simulation = new CombatSolverReplayEnvironment();
        simulation.Capture(session.CombatStateForSimulation, session.Hp);
        CombatSolverMctsAction[] potionActions = simulation.LegalActions()
            .Where(action => action.Native.Kind == "UsePotion"
                && action.Native.PotionId == potionId)
            .ToArray();
        if (potionActions.Length == 0)
        {
            throw new InvalidDataException(
                $"Native MCTS does not expose manual potion {potionId} ({potionType}).");
        }

        CombatSolverMctsAction selectedPotion = potionActions
            .OrderBy(action => action.Native.TargetCombatId)
            .ThenBy(action => action.Key, StringComparer.Ordinal)
            .First();
        SearchAction livePotion = session.ToLiveSearchAction(selectedPotion);
        if (!session.Actions().Any(action => action.Combat == livePotion.Combat))
            throw new InvalidDataException($"Native game does not expose predicted potion action {potionId}.");

        await simulation.ApplyAsync(selectedPotion, cancellation);
        await session.StepAsync(livePotion, cancellation);
        int choiceDepth = 0;
        while (simulation.ChoiceSignature.Length > 0 || session.HasPendingChoice)
        {
            if (++choiceDepth > 8)
                throw new InvalidDataException($"Potion {potionId} exceeded the supported nested choice depth.");
            RequireMatchingChoice(session, simulation, potionId);
            CombatSolverMctsAction selectedChoice = simulation.LegalActions()
                .OrderByDescending(action => action.Native.SelectedCards?.Count ?? 0)
                .ThenBy(action => action.Key, StringComparer.Ordinal)
                .First();
            SearchAction liveChoice = session.ToLiveSearchAction(selectedChoice);
            await simulation.ApplyAsync(selectedChoice, cancellation);
            await session.StepAsync(liveChoice, cancellation);
        }

        RequireContinuationMatch(session, simulation, potionId);
        Godot.GD.Print(
            $"SLAY_WORKER_POTION_MATCH id={potionId} type={potionType} " +
            $"targets={potionActions.Length} choices={choiceDepth} full continuation");
    }

    private static async Task VerifyNonManualPotionBoundaryAsync(
        NativeSession session,
        string potionId,
        string potionType,
        CancellationToken cancellation)
    {
        await ResetWithPotionAsync(session, potionId, cancellation);
        using var simulation = new CombatSolverReplayEnvironment();
        simulation.Capture(session.CombatStateForSimulation, session.Hp);
        if (simulation.LegalActions().Any(action => action.Native.Kind == "UsePotion"
                && action.Native.PotionId == potionId))
        {
            throw new InvalidDataException(
                $"Non-gameplay potion {potionId} must not be exposed as a Native MCTS input.");
        }
        if (potionId == AutomaticPotionId
            && session.Actions().Any(action => action.Combat?.Kind == CombatActionKind.UsePotion))
        {
            throw new InvalidDataException($"Non-manual potion {potionId} is exposed in the native action set.");
        }
        string kind = potionId switch
        {
            AutomaticPotionId => "automatic",
            DeprecatedPotionId => "deprecated",
            _ => "test-fixture",
        };
        Godot.GD.Print(
            $"SLAY_WORKER_POTION_NON_MANUAL_MATCH id={potionId} type={potionType} " +
            $"kind={kind} manual=false");
    }

    private static async Task VerifyReplayMctsVisitsPotionAsync(
        NativeSession session,
        CancellationToken cancellation)
    {
        session.ChoiceFixture = true;
        session.ChoiceFixtureCards = ["DEFEND_IRONCLAD"];
        await ResetWithPotionAsync(session, "BLOCK_POTION", cancellation);
        using var simulation = new CombatSolverReplayEnvironment();
        simulation.Capture(session.CombatStateForSimulation, session.Hp);
        var tree = new ReplayMcts<CombatSolverMctsAction>(simulation, seed: 20261019);
        TimedSearchResult<CombatSolverMctsAction> result = await tree.SearchAsync(
            [], simulation.RootKey, TimeSpan.FromSeconds(1), TimeSpan.FromSeconds(1),
            cancellation, maxDepth: 20);
        RootActionStatistics<CombatSolverMctsAction>? potion = result.Statistics
            .FirstOrDefault(statistic => statistic.Action.Native.Kind == "UsePotion"
                && statistic.Action.Native.PotionId == "BLOCK_POTION");
        if (potion == null || potion.Visits <= 0)
        {
            throw new InvalidDataException(
                "ReplayMcts did not expand and visit the BLOCK_POTION root action.");
        }
        Godot.GD.Print(
            $"SLAY_WORKER_POTION_MCTS_VISIT_MATCH visits={potion.Visits} " +
            $"simulations={result.CompletedSimulations}");
    }

    private static async Task ResetWithPotionAsync(
        NativeSession session,
        string potionId,
        CancellationToken cancellation)
    {
        session.Checkpoint = null;
        session.ChoiceFixtureUpgradedCards.Clear();
        session.EnterRoomForVerification = async (run, encounter) =>
        {
            var player = run.Players.Single();
            PotionModel potion = ModelDb.AllPotions.Single(candidate =>
                candidate.Id.Entry.Equals(potionId, StringComparison.Ordinal)).ToMutable();
            int slot = Enumerable.Range(0, player.PotionSlots.Count)
                .First(index => player.GetPotionAtSlotIndex(index) == null);
            if (!player.AddPotionInternal(potion, slot, silent: false).success)
                throw new InvalidDataException($"Could not inject potion {potionId}.");
            await RunManager.Instance.EnterRoomDebug(RoomType.Monster, model: encounter);
        };
        try
        {
            await session.ResetAsync($"MCTS-POTION-{potionId}", cancellation);
        }
        finally
        {
            session.EnterRoomForVerification = null;
        }
    }

    private static void RequireMatchingChoice(
        NativeSession session,
        CombatSolverReplayEnvironment simulation,
        string potionId)
    {
        if (!session.HasPendingChoice || !CombatSolverReplayEnvironment.ChoiceSignaturesMatch(
                simulation.ChoiceSignature, session.ChoiceSignature))
        {
            throw new InvalidDataException(
                $"Potion {potionId} choice differs: native={session.ChoiceSignature} " +
                $"simulated={simulation.ChoiceSignature} diagnostics={simulation.ChoiceDiagnostics}");
        }
        session.ValidateSimulationActions(simulation.LegalActions());
    }

    private static void RequireContinuationMatch(
        NativeSession session,
        CombatSolverReplayEnvironment simulation,
        string potionId)
    {
        string actual = NativeMctsSimulationApi.CaptureLiveContinuationKey(
            session.CombatStateForSimulation);
        if (simulation.CurrentContinuationKey != actual)
        {
            throw new InvalidDataException(
                $"Potion {potionId} full continuation differs from native execution.");
        }
    }

    private static void ResetFixture(NativeSession session)
    {
        session.Checkpoint = null;
        session.ChoiceFixture = false;
        session.ChoiceFixtureCards =
            ["PURITY", "ARMAMENTS", "HEADBUTT", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD"];
        session.ChoiceFixtureUpgradedCards.Clear();
        session.EnterRoomForVerification = null;
    }
}
