using SlayTheModel.Sts2.Protocol;

if (args.Length != 1 || args[0] is "--help" or "-h")
{
    Console.WriteLine(
        "Usage: dotnet run --project tools/SlayTheModel.CaptureCheck -- <combat-decision.json>");
    return args.Length == 1 ? 0 : 1;
}

var path = Path.GetFullPath(args[0]);
if (!File.Exists(path))
{
    Console.Error.WriteLine($"capture_not_found={path}");
    return 2;
}

var decision = ProtocolJson.Deserialize<CombatDecisionPoint>(File.ReadAllText(path));
decision.Validate();
var cards = decision.Observation.Players
    .SelectMany(player => player.Piles)
    .Sum(pile => pile.Cards.Count);

Console.WriteLine($"capture={path}");
Console.WriteLine($"schema={decision.SchemaVersion}");
Console.WriteLine($"decision_index={decision.DecisionIndex}");
Console.WriteLine($"round={decision.Observation.RoundNumber}");
Console.WriteLine($"players={decision.Observation.Players.Count}");
Console.WriteLine($"creatures={decision.Observation.Creatures.Count}");
Console.WriteLine($"cards={cards}");
Console.WriteLine($"legal_actions={decision.LegalActions.Count}");
Console.WriteLine($"fingerprint={decision.StateFingerprint}");
return 0;
