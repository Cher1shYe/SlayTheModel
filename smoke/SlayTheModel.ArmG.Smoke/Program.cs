using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;

var python = Environment.GetEnvironmentVariable("ARMG_SMOKE_PYTHON");
if (string.IsNullOrWhiteSpace(python))
{
    Console.WriteLine("ArmG worker smoke skipped: set ARMG_SMOKE_PYTHON to a Python executable.");
    return;
}

var directory = Path.Combine(Path.GetTempPath(), "sts2-armg-smoke-" + Guid.NewGuid().ToString("N"));
Directory.CreateDirectory(directory);
try
{
    var worker = Path.Combine(directory, "worker.py");
    File.WriteAllText(worker, """
import json, sys
for line in sys.stdin:
    item=json.loads(line)
    d=item['decision']
    fp=d['state_fingerprint'] if d['decision_index']==0 else '0'*64
    print(json.dumps({'request_id':item['request_id'],'state_fingerprint':fp,'status':'ok',
        'action_id':'skip:0','approximate':True,'missing_features':['sample'], 'scores':[0.5]}),flush=True)
""");
    Environment.SetEnvironmentVariable("SLAY_THE_MODEL_ARMG_PYTHON", python);
    Environment.SetEnvironmentVariable("SLAY_THE_MODEL_ARMG_SERVER", worker);
    Environment.SetEnvironmentVariable("SLAY_THE_MODEL_ARMG_CHECKPOINT", "dummy");
    Environment.SetEnvironmentVariable("SLAY_THE_MODEL_ARMG_STS2_ROOT", directory);
    Environment.SetEnvironmentVariable("SLAY_THE_MODEL_ARMG_SIMULATOR", "dummy");
    Environment.SetEnvironmentVariable("SLAY_THE_MODEL_ARMG_MODE", "shadow");
    using var policy = new ArmGOutsidePolicy();
    if (policy.AutoMode || policy.AllowApproximate)
        throw new Exception("ArmG must default to a nonexecuting shadow mode.");
    var decision = new OutsideCombatDecisionPoint(1,
        new BuildIdentity("v0.111.0", new string('a', 64), Guid.Empty.ToString("D")),
        0, new string('b', 64), null!,
        [new OutsideCombatActionDescriptor("skip:0", OutsideCombatActionKind.Skip, 0)]);
    var result = await policy.SelectAsync(decision);
    if (result.Status != "ok" || result.ActionId != "skip:0" || result.Approximate != true
        || result.Scores is not [0.5f])
        throw new Exception("ArmG worker response did not round-trip.");
    if (ArmGDecisionGuard.Select(decision, result, autoMode: false, allowApproximate: true) is not null
        || ArmGDecisionGuard.Select(decision, result, autoMode: true, allowApproximate: false) is not null
        || ArmGDecisionGuard.Select(decision, result, autoMode: true, allowApproximate: true)?.ActionId != "skip:0")
        throw new Exception("Shadow or explicit approximation controls were not enforced.");
    try
    {
        ArmGDecisionGuard.Select(decision, result with { ActionId = "not-legal" }, true, true);
        throw new Exception("An illegal worker action was accepted.");
    }
    catch (InvalidDataException) { }
    if (ArmGDecisionGuard.Select(decision, result with { Status = "unsupported", ActionId = null }, true, true) is not null)
        throw new Exception("Unsupported screens must always remain manual.");
    var fallbackContext = new OutsideCombatChoiceContext("merchant", new string('c', 64),
        OutsideCombatChoicePhase.Default, null, null, 0, false, false);
    var fallbackObservation = new OutsideCombatObservation(OutsideCombatObservation.CurrentSchemaVersion,
        OutsideCombatSurfaceKind.Merchant, fallbackContext, 0, 2, 2, 0, "Shop", null, null,
        [new OutsideRunPlayerObservation(1, "CHARACTER.IRONCLAD", 70, 80, 100, 3, [], [], [])], []);
    var fallbackActions = new[] { new OutsideCombatActionDescriptor("leave:0", OutsideCombatActionKind.LeaveMerchant, 0) };
    var fallbackBuild = new BuildIdentity("v0.111.0", new string('a', 64), Guid.Empty.ToString("D"));
    var fallbackDecision = new OutsideCombatDecisionPoint(OutsideCombatDecisionPoint.CurrentSchemaVersion,
        fallbackBuild, 0, ProtocolJson.ComputeOutsideStateFingerprint(fallbackBuild, fallbackObservation, fallbackActions),
        fallbackObservation, fallbackActions);
    fallbackDecision.Validate();
    var unsupported = result with { Status = "unsupported", ActionId = null, StateFingerprint = fallbackDecision.StateFingerprint };
    var choice = ArmGFallbackPolicy.Select(fallbackDecision, unsupported, true, true, out var usedFallback);
    if (!usedFallback || choice?.ActionId != "leave:0")
        throw new Exception("Unsupported automatic screen must use the current legal fallback.");
    choice = ArmGFallbackPolicy.Select(fallbackDecision, unsupported with { Status = "error" }, true, true, out usedFallback);
    if (!usedFallback || choice?.ActionId != "leave:0")
        throw new Exception("Worker errors must fall back to a current legal action in auto mode.");
    if (ArmGFallbackPolicy.Select(fallbackDecision, unsupported, false, true, out usedFallback) is not null || usedFallback)
        throw new Exception("Unsupported shadow screen must remain manual.");
    try
    {
        ArmGFallbackPolicy.Select(fallbackDecision, unsupported with { StateFingerprint = new string('0', 64) }, true, true, out _);
        throw new Exception("A stale response reached the fallback selector.");
    }
    catch (InvalidDataException) { }
    try
    {
        ArmGFallbackPolicy.Select(fallbackDecision, unsupported with { Status = "ok", ActionId = "illegal", Approximate = true }, true, true, out _);
        throw new Exception("An illegal model action was accepted.");
    }
    catch (InvalidDataException) { }
    try
    {
        ArmGDecisionGuard.Select(decision, result with { Approximate = null }, true, true);
        throw new Exception("Undeclared approximation status was accepted.");
    }
    catch (InvalidDataException) { }
    try
    {
        await policy.SelectAsync(decision with { DecisionIndex = 1 });
        throw new Exception("A stale worker fingerprint was accepted.");
    }
    catch (InvalidDataException) { }
    var realRoot = Environment.GetEnvironmentVariable("ARMG_REAL_ROOT");
    var realServer = Environment.GetEnvironmentVariable("ARMG_REAL_SERVER");
    var realCheckpoint = Environment.GetEnvironmentVariable("ARMG_REAL_CHECKPOINT");
    var realSimulator = Environment.GetEnvironmentVariable("ARMG_REAL_SIMULATOR");
    if (new[] { realRoot, realServer, realCheckpoint, realSimulator }.All(x => !string.IsNullOrWhiteSpace(x)))
    {
        Environment.SetEnvironmentVariable("SLAY_THE_MODEL_ARMG_SERVER", realServer);
        Environment.SetEnvironmentVariable("SLAY_THE_MODEL_ARMG_STS2_ROOT", realRoot);
        Environment.SetEnvironmentVariable("SLAY_THE_MODEL_ARMG_CHECKPOINT", realCheckpoint);
        Environment.SetEnvironmentVariable("SLAY_THE_MODEL_ARMG_SIMULATOR", realSimulator);
        using var actual = new ArmGOutsidePolicy();
        var build = new BuildIdentity("v0.111.0",
            "0861bfa1df347538d932f22d580e75420f08082792eb914e53b4882764acdbe9",
            "73b63ee0-6c0a-47bb-b0d1-b21f6d94222e");
        var coord = new OutsideMapCoordinate(0, 3);
        var next = new OutsideMapCoordinate(1, 3);
        var context = new OutsideCombatChoiceContext("card_reward", new string('c', 64),
            OutsideCombatChoicePhase.Default, null, null, 0, true, false);
        var observation = new OutsideCombatObservation(OutsideCombatObservation.CurrentSchemaVersion,
            OutsideCombatSurfaceKind.CardReward, context, 0, 2, 2, 0, "Monster", null, coord,
            [new OutsideRunPlayerObservation(1, "CHARACTER.IRONCLAD", 70, 80, 100, 3,
                [new OutsideRunCardObservation(0, "CARD.STRIKE_IRONCLAD", 0, null, null)],
                [new OutsideRunRelicObservation("RELIC.BURNING_BLOOD")], [])],
            [new OutsideMapPointObservation(coord, "Ancient", true, [next]),
             new OutsideMapPointObservation(next, "Monster", false, [])]);
        var actions = new OutsideCombatActionDescriptor[]
        {
            new("choosecard:0:CARD.BASH", OutsideCombatActionKind.ChooseCard, 0, "CARD.BASH") { TargetUpgradeLevel = 1 },
            new("skip:1:-", OutsideCombatActionKind.Skip, 1),
        };
        var realDecision = new OutsideCombatDecisionPoint(OutsideCombatDecisionPoint.CurrentSchemaVersion,
            build, 0, ProtocolJson.ComputeOutsideStateFingerprint(build, observation, actions), observation, actions);
        realDecision.Validate();
        var actualResult = await actual.SelectAsync(realDecision);
        if (actualResult.Status != "ok" || actualResult.Approximate != true
            || !actions.Any(a => a.ActionId == actualResult.ActionId))
            throw new Exception($"Actual ArmG worker failed for a valid reward: {actualResult.Reason}");
        var manualObs = observation with { Surface = OutsideCombatSurfaceKind.Merchant };
        var manualActions = new[] { new OutsideCombatActionDescriptor("leave:0:-", OutsideCombatActionKind.LeaveMerchant, 0) };
        var manualDecision = new OutsideCombatDecisionPoint(OutsideCombatDecisionPoint.CurrentSchemaVersion,
            build, 1, ProtocolJson.ComputeOutsideStateFingerprint(build, manualObs, manualActions), manualObs, manualActions);
        manualDecision.Validate();
        var manualResult = await actual.SelectAsync(manualDecision);
        if (manualResult.StateFingerprint != manualDecision.StateFingerprint ||
            !(manualResult.Status == "unsupported" ||
              (manualResult.Status == "ok" && manualResult.ActionId == manualActions[0].ActionId && manualResult.Approximate == false)))
            throw new Exception("Actual ArmG worker did not safely handle the forced merchant action.");
        Console.WriteLine("Actual C# → Python → checkpoint/simulator reward inference and unsupported-screen checks passed.");
    }
    Console.WriteLine("ArmG worker JSONL, shadow defaults and stale fingerprint checks passed.");
}
finally { Directory.Delete(directory, recursive: true); }
