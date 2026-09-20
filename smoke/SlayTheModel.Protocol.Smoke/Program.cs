using SlayTheModel.Sts2.Protocol;

var card = new CardSnapshot(11, "Strike", 1, null, 0, [], "{\"id\":\"Strike\"}");
var player = new PlayerCombatSnapshot(
    7,
    "Ironclad",
    3,
    0,
    99,
    1,
    "play",
    [new CombatPileSnapshot("hand", [card])],
    [],
    [],
    [],
    new PlayerRngSnapshot(7, []));
var playerCreature = new CreatureSnapshot(7, 7, null, 70, 80, 0, []);
var enemy = new CreatureSnapshot(42, null, "JawWorm", 40, 40, 0, []);
var state = new CombatSnapshot(
    CombatSnapshot.CurrentSchemaVersion,
    new BuildIdentity("v0.111.0", new string('a', 64), Guid.Empty.ToString("D")),
    0,
    1,
    CombatSide.Player,
    [player],
    [playerCreature, enemy],
    new RunRngSnapshot("smoke", [new NamedRngSnapshot("shuffle", new RngSnapshot(0, 1, 2, 3, 4))]),
    new DeterminismCounters(null, null, [0], [0]),
    1234);
var fingerprint = ProtocolJson.ComputeStateFingerprint(state);
var decision = new CombatDecisionPoint(
    CombatDecisionPoint.CurrentSchemaVersion,
    state.DecisionIndex,
    fingerprint,
    DecisionObservationProjector.ToCombat(state),
    [
        new CombatActionDescriptor(CombatActionKind.PlayCard, 7, 11, TargetCreatureId: 42),
        new CombatActionDescriptor(CombatActionKind.EndTurn, 7),
    ]);
var searchPoint = new CombatSearchPoint(
    state,
    DecisionObservationProjector.ToRun(state),
    decision);

searchPoint.Validate();
var before = decision.StateFingerprint;
var json = ProtocolJson.Serialize(decision);
var roundTripped = ProtocolJson.Deserialize<CombatDecisionPoint>(json);
roundTripped.Validate();
var after = roundTripped.StateFingerprint;

if (!string.Equals(before, after, StringComparison.Ordinal))
{
    throw new InvalidOperationException("Protocol fingerprint changed after JSON round-trip.");
}

var recaptured = ProtocolJson.ComputeStateFingerprint(state with { DecisionIndex = 999 });
if (!string.Equals(before, recaptured, StringComparison.Ordinal))
{
    throw new InvalidOperationException("Capture sequence number changed the semantic state fingerprint.");
}

var changedPlayer = state.Players[0] with { Energy = 2 };
var changedState = state with { Players = [changedPlayer] };
if (string.Equals(before, ProtocolJson.ComputeStateFingerprint(changedState), StringComparison.Ordinal))
{
    throw new InvalidOperationException("A semantic state change did not change the fingerprint.");
}

var step = new CombatStepRequest(Guid.NewGuid(), before, decision.LegalActions[0]);
CombatStepGuard.RequireExpectedState(step, state);
var staleWasRejected = false;
try
{
    CombatStepGuard.RequireExpectedState(step, changedState);
}
catch (StaleCombatStateException)
{
    staleWasRejected = true;
}

if (!staleWasRejected)
{
    throw new InvalidOperationException("A stale combat action was not rejected.");
}

if (json.Contains("\"gold\"", StringComparison.Ordinal)
    || json.Contains("run_rng", StringComparison.Ordinal)
    || json.Contains("native_card_json", StringComparison.Ordinal))
{
    throw new InvalidOperationException("Combat policy payload leaked simulator or run-only state.");
}

var runJson = ProtocolJson.Serialize(searchPoint.RunObservation);
if (!runJson.Contains("\"gold\":99", StringComparison.Ordinal))
{
    throw new InvalidOperationException("Run observation did not retain player gold.");
}

Console.WriteLine($"schema={roundTripped.SchemaVersion}");
Console.WriteLine($"actions={roundTripped.LegalActions.Count}");
Console.WriteLine($"fingerprint={after}");
