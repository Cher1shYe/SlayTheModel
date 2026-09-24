using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.ModAdapter;

/// <summary>
/// Projects native run state into the stable outside-combat protocol and writes
/// policy samples. Native UI nodes are intentionally owned by the controller's
/// private bindings and never cross this boundary.
/// </summary>
internal static class OutsideCombatCaptureService
{
    private static readonly object Gate = new();
    private static RunState? _episodeRun;
    private static Guid _episodeId = Guid.NewGuid();
    private static long _decisionIndex;
    private static OutsideCombatDecisionPoint? _lastDecision;

    internal static OutsideCombatDecisionPoint BuildDecisionPoint(
        RunState state,
        OutsideCombatSurfaceKind surface,
        OutsideCombatChoiceContext choiceContext,
        IReadOnlyList<OutsideCombatActionDescriptor> legalActions)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(choiceContext);
        ArgumentNullException.ThrowIfNull(legalActions);
        lock (Gate)
        {
            EnsureEpisode(state);
            var observation = BuildObservation(state, surface, choiceContext);
            var fingerprint = ProtocolJson.ComputeOutsideStateFingerprint(
                CombatCaptureService.CurrentBuild,
                observation,
                legalActions);
            if (_lastDecision is { } previous
                && string.Equals(
                    previous.StateFingerprint,
                    fingerprint,
                    StringComparison.Ordinal))
            {
                return previous;
            }

            var decision = new OutsideCombatDecisionPoint(
                OutsideCombatDecisionPoint.CurrentSchemaVersion,
                CombatCaptureService.CurrentBuild,
                _decisionIndex++,
                fingerprint,
                observation,
                legalActions);
            decision.Validate();
            _lastDecision = decision;
            return decision;
        }
    }

    internal static OutsideCombatObservation BuildObservation(
        RunState state,
        OutsideCombatSurfaceKind surface,
        OutsideCombatChoiceContext choiceContext)
    {
        ArgumentNullException.ThrowIfNull(state);
        ArgumentNullException.ThrowIfNull(choiceContext);
        var currentRoom = state.CurrentRoom;
        var mapPoints = BuildMapObservation(state);
        var mapCoordinates = mapPoints.Select(point => point.Coordinate).ToHashSet();
        var players = state.Players
            .OrderBy(player => player.NetId)
            .Select(player => new OutsideRunPlayerObservation(
                player.NetId,
                player.Character.Id.ToString(),
                player.Creature.CurrentHp,
                player.Creature.MaxHp,
                player.Gold,
                player.MaxPotionCount,
                player.Deck.Cards
                    .Select((card, index) => new OutsideRunCardObservation(
                        index,
                        card.Id.ToString(),
                        card.CurrentUpgradeLevel,
                        card.Enchantment?.Id.ToString(),
                        card.Affliction?.Id.ToString()))
                    .ToArray(),
                player.Relics
                    .Select(relic => new OutsideRunRelicObservation(
                        relic.Id.ToString(),
                        relic.StackCount,
                        relic.IsUsedUp,
                        relic.Status.ToString(),
                        relic.DisplayAmount))
                    .ToArray(),
                player.PotionSlots
                    .Select((potion, index) => new { Potion = potion, Index = index })
                    .Where(entry => entry.Potion is not null)
                    .Select(entry => new PotionObservation(
                        entry.Index,
                        entry.Potion!.Id.ToString()))
                    .ToArray()))
            .ToArray();

        var observation = new OutsideCombatObservation(
            OutsideCombatObservation.CurrentSchemaVersion,
            surface,
            choiceContext,
            state.CurrentActIndex,
            state.ActFloor,
            state.TotalFloor,
            state.AscensionLevel,
            currentRoom?.RoomType.ToString() ?? "Unknown",
            currentRoom?.ModelId?.ToString(),
            state.CurrentMapCoord is { } coordinate
                && mapCoordinates.Contains(ToCoordinate(coordinate))
                ? ToCoordinate(coordinate)
                : null,
            players,
            mapPoints);
        observation.Validate();
        return observation;
    }

    internal static OutsideCombatDecisionSample RecordSelection(
        IOutsideCombatPolicy policy,
        OutsideCombatDecisionPoint decision,
        OutsideCombatStepRequest step)
    {
        ArgumentNullException.ThrowIfNull(policy);
        ArgumentNullException.ThrowIfNull(decision);
        ArgumentNullException.ThrowIfNull(step);

        lock (Gate)
        {
            var sample = new OutsideCombatDecisionSample(
                OutsideCombatDecisionSample.CurrentSchemaVersion,
                _episodeId,
                policy.PolicyId,
                decision,
                step);
            sample.Validate();
            try
            {
                var outputDirectory = CombatCaptureService.GetOutputDirectory();
                Directory.CreateDirectory(outputDirectory);
                WriteAtomically(
                    Path.Combine(outputDirectory, "latest-outside-decision.json"),
                    ProtocolJson.Serialize(decision));
                WriteAtomically(
                    Path.Combine(outputDirectory, "latest-outside-sample.json"),
                    ProtocolJson.Serialize(sample));

                if (CaptureHistoryEnabled())
                {
                    var historyPath = Path.Combine(
                        outputDirectory,
                        $"outside-decision-{_episodeId:N}-{decision.DecisionIndex:D8}"
                        + $"-{step.RequestId:N}-{decision.StateFingerprint[..12]}.json");
                    File.WriteAllText(historyPath, ProtocolJson.Serialize(sample));
                    File.AppendAllText(
                        Path.Combine(outputDirectory, "outside-trajectory.jsonl"),
                        ProtocolJson.Serialize(sample) + Environment.NewLine);
                }
            }
            catch (Exception exception)
            {
                // Capture is observational. A full disk or malformed optional
                // export path must not strand a live run on a decision screen.
                Console.Error.WriteLine(
                    $"[SlayTheModel] outside decision capture failed: {exception}");
            }

            return sample;
        }
    }

    internal static void RecordExecution(
        OutsideCombatDecisionSample sample,
        OutsideCombatExecutionStatus status,
        string? detail = null)
    {
        ArgumentNullException.ThrowIfNull(sample);
        var result = new OutsideCombatExecutionResult(
            OutsideCombatExecutionResult.CurrentSchemaVersion,
            sample.EpisodeId,
            sample.Decision.DecisionIndex,
            sample.PolicyId,
            sample.Step.RequestId,
            sample.Step.ExpectedStateFingerprint,
            sample.Step.ActionId,
            status,
            detail);
        result.Validate();

        lock (Gate)
        {
            try
            {
                var outputDirectory = CombatCaptureService.GetOutputDirectory();
                Directory.CreateDirectory(outputDirectory);
                var json = ProtocolJson.Serialize(result);
                WriteAtomically(
                    Path.Combine(outputDirectory, "latest-outside-result.json"),
                    json);

                if (CaptureHistoryEnabled())
                {
                    var historyPath = Path.Combine(
                        outputDirectory,
                        $"outside-result-{result.EpisodeId:N}-{result.DecisionIndex:D8}"
                        + $"-{result.RequestId:N}.json");
                    File.WriteAllText(historyPath, json);
                    File.AppendAllText(
                        Path.Combine(outputDirectory, "outside-results.jsonl"),
                        json + Environment.NewLine);
                }
            }
            catch (Exception exception)
            {
                Console.Error.WriteLine(
                    $"[SlayTheModel] outside execution capture failed: {exception}");
            }
        }
    }

    internal static void Reset()
    {
        lock (Gate)
        {
            _episodeRun = null;
            _episodeId = Guid.NewGuid();
            _decisionIndex = 0;
            _lastDecision = null;
        }
    }

    private static void EnsureEpisode(RunState state)
    {
        if (ReferenceEquals(_episodeRun, state))
        {
            return;
        }

        _episodeRun = state;
        _episodeId = Guid.NewGuid();
        _decisionIndex = 0;
        _lastDecision = null;
    }

    private static bool CaptureHistoryEnabled() => string.Equals(
        RuntimeConfiguration.Get("SLAY_THE_MODEL_CAPTURE_HISTORY"),
        "1",
        StringComparison.Ordinal);

    private static IReadOnlyList<OutsideMapPointObservation> BuildMapObservation(
        RunState state)
    {
        if (state.Map?.StartingMapPoint is not { } start)
        {
            return [];
        }

        var visited = state.VisitedMapCoords.ToHashSet();
        var pending = new Queue<MapPoint>();
        var seen = new HashSet<MapPoint>();
        pending.Enqueue(start);
        seen.Add(start);
        while (pending.TryDequeue(out var point))
        {
            foreach (var child in point.Children)
            {
                if (seen.Add(child))
                {
                    pending.Enqueue(child);
                }
            }
        }

        return seen
            .Select(point => new OutsideMapPointObservation(
                ToCoordinate(point.coord),
                point.PointType.ToString(),
                visited.Contains(point.coord),
                point.Children
                    .Select(child => ToCoordinate(child.coord))
                    .OrderBy(child => child.Row)
                    .ThenBy(child => child.Column)
                    .ToArray()))
            .OrderBy(point => point.Coordinate.Row)
            .ThenBy(point => point.Coordinate.Column)
            .ToArray();
    }

    private static OutsideMapCoordinate ToCoordinate(MapCoord coordinate) =>
        new(coordinate.row, coordinate.col);

    private static void WriteAtomically(string path, string contents)
    {
        var temporaryPath = path + ".tmp";
        File.WriteAllText(temporaryPath, contents);
        File.Move(temporaryPath, path, overwrite: true);
    }
}
