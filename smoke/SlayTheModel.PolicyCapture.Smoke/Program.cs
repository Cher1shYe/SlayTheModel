using System.Runtime.CompilerServices;
using System.Reflection;
using System.Text.Json;
using HarmonyLib;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using SlayTheModel.Collector;
using SlayTheModel.Sts2.DataCollector;
using SlayTheModel.Sts2.ModAdapter;

var count = 0;
// Inspect the loaded, version-pinned native method, rather than trusting the
// decompiled reference copy. No queue or engine singleton is instantiated.
var enqueue = typeof(ActionQueueSet).GetMethod(nameof(ActionQueueSet.EnqueueWithoutSynchronizing))!;
var instructions = PatchProcessor.GetOriginalInstructions(enqueue).ToArray();
var enqueuedCallback = Array.FindIndex(instructions, item =>
    item.operand is FieldInfo field && field.Name == "ActionEnqueued");
var changedCallback = Array.FindIndex(instructions, item =>
    item.operand is FieldInfo field && field.Name == "ActionQueueChanged");
var onEnqueued = Array.FindIndex(instructions, item =>
    item.operand is MethodInfo method && method.DeclaringType == typeof(GameAction)
        && method.Name == nameof(GameAction.OnEnqueued));
var cancellations = instructions.Select((item, index) => (item, index))
    .Where(pair => pair.item.operand is MethodInfo method
        && method.DeclaringType == typeof(GameAction) && method.Name == nameof(GameAction.Cancel))
    .Select(pair => pair.index).ToArray();
Check(onEnqueued >= 0 && enqueuedCallback > onEnqueued && changedCallback > enqueuedCallback,
    "native enqueue callback follows identity assignment and precedes execution trigger");
Check(cancellations.Length == 3 && cancellations.All(index => index > enqueuedCallback),
    "native immediate cancellations all occur after capture callback");
var response = new NativeMctsResponse(Guid.NewGuid(), null, null,
    Simulations: 73, RetainedVisits: 121, SearchMilliseconds: 8.5,
    NextStateKey: "must-never-be-written", StateTransitions: 900);
var json = PolicyTraceMetadata.NativeMcts(response);
var trace = CollectorPolicyOrigin.Parse(json);
Check(trace.Actor == ActionActor.Policy && trace.PolicyId == "native-mcts",
    "exact MCTS origin");
Check(trace.TeacherInformation == "native_checkpoint_privileged"
      && !string.IsNullOrWhiteSpace(trace.ModelRevision), "privileged teacher and implementation revision");
Check(trace.MctsVisitCounts is null, "search total is not fabricated into per-action visits");
Check(!json.Contains("must-never") && !json.Contains("checkpoint\""), "no search state in metadata");
var summary = JsonSerializer.Serialize(CollectorPolicyOrigin.SearchSummary(json));
Check(summary.Contains("73") && !summary.Contains("NextStateKey"), "scalar search summary only");
var first = CollectorPolicyOrigin.Parse(PolicyTraceMetadata.FirstLegal());
Check(first.PolicyId == "first-legal" && first.TeacherInformation == "public_observation",
    "first-legal public teacher");
Reject(json.Replace("native_checkpoint_privileged", "public_observation"),
    "MCTS cannot claim public teacher");
Reject(json.Replace("native-mcts", "unrecognized-bot"), "unknown teacher rejected");
Reject(json.Replace("\"version\":1", "\"version\":2"), "unknown bridge ABI rejected");

var action = (GameAction)RuntimeHelpers.GetUninitializedObject(typeof(EndPlayerTurnAction));
GameAction? observedAction = null;
string? observedJson = null;
Action<GameAction, string> failing = (_, _) => throw new InvalidOperationException("expected observer failure");
Action<GameAction, string> observing = (actual, metadata) => (observedAction, observedJson) = (actual, metadata);
PolicyDecisionTelemetry.ActionSubmitting += failing;
PolicyDecisionTelemetry.ActionSubmitting += observing;
try
{
    PolicyDecisionTelemetry.NotifyActionSubmitting(action, json);
    Check(ReferenceEquals(observedAction, action) && observedJson == json,
        "observer failure isolated and exact native object retained");
}
finally
{
    PolicyDecisionTelemetry.ActionSubmitting -= failing;
    PolicyDecisionTelemetry.ActionSubmitting -= observing;
}

var settings = new Dictionary<string, string>
{
    [CollectorConfiguration.InformationModeVariable] = "auto",
    [CollectorConfiguration.ActorVariable] = "human",
    ["SLAY_THE_MODEL_COMBAT_POLICY"] = "mcts",
    ["SLAY_THE_MODEL_OUTSIDE_COMBAT_POLICY"] = "manual",
};
var previous = settings.Keys.ToDictionary(key => key, Environment.GetEnvironmentVariable);
try
{
    foreach (var (key, value) in settings) Environment.SetEnvironmentVariable(key, value);
    var configuration = CollectorConfiguration.Load();
    Check(configuration.InformationMode == CollectorInformationMode.Auto,
        "automated capture does not upgrade unknown to no-SL");
    Check(CollectorPolicyOrigin.UnattributedInput(configuration.CombatPolicy).PolicyId == "observed-automation",
        "unattributed native manual API in automated combat stays unproven");
    Check(CollectorPolicyOrigin.UnattributedInput(configuration.OutsideCombatPolicy).Actor == ActionActor.Human,
        "manual outside inputs are not relabeled as MCTS by combat configuration");
    Environment.SetEnvironmentVariable(CollectorConfiguration.InformationModeVariable, "no-sl");
    Check(CollectorConfiguration.Load().InformationMode == CollectorInformationMode.NoSl
          && trace.TeacherInformation == "native_checkpoint_privileged",
        "explicit student regime and teacher information remain separate");
}
finally
{
    foreach (var (key, value) in previous) Environment.SetEnvironmentVariable(key, value);
}
Console.WriteLine($"Policy capture smoke passed: {count} checks; no game launched.");

void Check(bool condition, string name)
{
    if (!condition) throw new InvalidOperationException(name);
    count++;
}
void Reject(string value, string name)
{
    try { CollectorPolicyOrigin.Parse(value); }
    catch (InvalidDataException) { count++; return; }
    throw new InvalidOperationException(name);
}
