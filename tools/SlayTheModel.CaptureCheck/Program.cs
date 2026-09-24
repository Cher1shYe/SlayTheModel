using SlayTheModel.Sts2.Protocol;
using System.Text.Json;

if (args.Length != 1 || args[0] is "--help" or "-h")
{
    Console.WriteLine(
        "Usage: dotnet run --project tools/SlayTheModel.CaptureCheck -- "
        + "<decision-sample-or-result.json>");
    return args.Length == 1 ? 0 : 1;
}

var path = Path.GetFullPath(args[0]);
if (!File.Exists(path))
{
    Console.Error.WriteLine($"capture_not_found={path}");
    return 2;
}

var json = File.ReadAllText(path);
using var document = JsonDocument.Parse(json);
var root = document.RootElement;
Console.WriteLine($"capture={path}");
if (root.TryGetProperty("status", out _)
    && root.TryGetProperty("request_id", out _)
    && root.TryGetProperty("expected_state_fingerprint", out _))
{
    var result = ProtocolJson.Deserialize<OutsideCombatExecutionResult>(json);
    result.Validate();
    Console.WriteLine("kind=outside_combat_execution_result");
    Console.WriteLine($"schema={result.SchemaVersion}");
    Console.WriteLine($"episode_id={result.EpisodeId}");
    Console.WriteLine($"decision_index={result.DecisionIndex}");
    Console.WriteLine($"policy={result.PolicyId}");
    Console.WriteLine($"selected_action={result.ActionId}");
    Console.WriteLine($"status={result.Status}");
    Console.WriteLine($"fingerprint={result.ExpectedStateFingerprint}");
}
else if (root.TryGetProperty("decision", out var wrappedDecision)
    && wrappedDecision.TryGetProperty("observation", out var wrappedObservation)
    && wrappedObservation.TryGetProperty("surface", out _))
{
    var sample = ProtocolJson.Deserialize<OutsideCombatDecisionSample>(json);
    sample.Validate();
    PrintOutside(sample.Decision);
    Console.WriteLine($"episode_id={sample.EpisodeId}");
    Console.WriteLine($"policy={sample.PolicyId}");
    Console.WriteLine($"selected_action={sample.Step.ActionId}");
}
else if (root.TryGetProperty("observation", out var observation)
    && observation.TryGetProperty("surface", out _))
{
    var decision = ProtocolJson.Deserialize<OutsideCombatDecisionPoint>(json);
    decision.Validate();
    PrintOutside(decision);
}
else
{
    var decision = ProtocolJson.Deserialize<CombatDecisionPoint>(json);
    decision.Validate();
    var cards = decision.Observation.Players
        .SelectMany(player => player.Piles)
        .Sum(pile => pile.Cards.Count);
    Console.WriteLine("kind=combat_decision");
    Console.WriteLine($"schema={decision.SchemaVersion}");
    Console.WriteLine($"decision_index={decision.DecisionIndex}");
    Console.WriteLine($"round={decision.Observation.RoundNumber}");
    Console.WriteLine($"players={decision.Observation.Players.Count}");
    Console.WriteLine($"creatures={decision.Observation.Creatures.Count}");
    Console.WriteLine($"cards={cards}");
    Console.WriteLine($"legal_actions={decision.LegalActions.Count}");
    Console.WriteLine($"fingerprint={decision.StateFingerprint}");
}

return 0;

static void PrintOutside(OutsideCombatDecisionPoint decision)
{
    var cards = decision.Observation.Players.Sum(player => player.Deck.Count);
    Console.WriteLine("kind=outside_combat_decision");
    Console.WriteLine($"schema={decision.SchemaVersion}");
    Console.WriteLine($"decision_index={decision.DecisionIndex}");
    Console.WriteLine($"surface={decision.Observation.Surface}");
    Console.WriteLine($"choice_context={decision.Observation.ChoiceContext.ContextId}");
    Console.WriteLine($"choice_phase={decision.Observation.ChoiceContext.Phase}");
    Console.WriteLine($"choice_state_token={decision.Observation.ChoiceContext.StateToken}");
    Console.WriteLine($"act={decision.Observation.ActIndex}");
    Console.WriteLine($"floor={decision.Observation.TotalFloor}");
    Console.WriteLine($"players={decision.Observation.Players.Count}");
    Console.WriteLine($"deck_cards={cards}");
    Console.WriteLine($"map_points={decision.Observation.MapPoints.Count}");
    Console.WriteLine($"legal_actions={decision.LegalActions.Count}");
    Console.WriteLine($"fingerprint={decision.StateFingerprint}");
}
