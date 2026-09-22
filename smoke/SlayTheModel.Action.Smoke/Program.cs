using SlayTheModel.Sts2.ModAdapter;

var defaults = AdapterConfiguration.Load(_ => null);
if (defaults != AdapterConfiguration.Default)
    throw new Exception("Missing launch settings must select safe play/manual/manual defaults.");
var settings = new Dictionary<string, string?>
{
    [AdapterConfiguration.RunModeVariable] = "train",
    [AdapterConfiguration.CombatPolicyVariable] = "MCTS",
    [AdapterConfiguration.OutsideCombatPolicyVariable] = "first_legal",
};
var configured = AdapterConfiguration.Load(name => settings.GetValueOrDefault(name));
if (configured.RunMode != AdapterRunMode.Train || configured.CombatPolicy != CombatPolicyKind.Mcts
    || configured.OutsideCombatPolicy != OutsideCombatPolicyKind.FirstLegal)
    throw new Exception("Explicit launch settings were not parsed correctly.");
var legacy = AdapterConfiguration.Load(name => name == AdapterConfiguration.LegacyCombatPolicyVariable ? "first-legal" : null);
if (!legacy.UsedLegacyCombatPolicy || legacy.CombatPolicy != CombatPolicyKind.FirstLegal)
    throw new Exception("The deprecated combat policy variable must remain compatible.");
try
{
    AdapterConfiguration.Load(name => name == AdapterConfiguration.RunModeVariable ? "invalid" : null);
    throw new Exception("Unknown launch modes must be rejected.");
}
catch (ArgumentException) { }

var ponder = new PonderResultCache<string>();
ponder.Begin("predicted");
if (ponder.Publish("different", "stale") || ponder.TryGet("predicted", out _))
    throw new Exception("A prediction from a different state must not become executable.");
var firstPrediction = ponder.WaitForFirstAsync("predicted", CancellationToken.None);
if (firstPrediction.IsCompleted)
    throw new Exception("The decision point must wait until the first usable prediction exists.");
if (!ponder.Publish("predicted", "current") || await firstPrediction != "current")
    throw new Exception("A matching prediction must become available to the decision point.");
ponder.Publish("predicted", "newest");
if (!ponder.TryGet("predicted", out var newest) || newest != "newest")
    throw new Exception("Continuous pondering must expose the newest completed result.");
ponder.Begin("next");
if (ponder.TryGet("predicted", out _))
    throw new Exception("Changing roots must invalidate the previous prediction.");

var workerStart = new System.Diagnostics.ProcessStartInfo();
workerStart.Environment[NativeWorkerLaunch.SentryGodotLibraryPath] = "inherited-game-extension";
workerStart.Environment["SLAY_THE_MODEL_SENTINEL"] = "keep";
NativeWorkerLaunch.IsolateFromGameProcess(workerStart);
if (workerStart.Environment.ContainsKey(NativeWorkerLaunch.SentryGodotLibraryPath))
    throw new Exception("The worker must not inherit the game's initialized Sentry bridge path.");
if (workerStart.Environment["SLAY_THE_MODEL_SENTINEL"] != "keep")
    throw new Exception("Worker environment isolation removed an unrelated setting.");

// A choice pauses the executor (idle), but not the card's completion task.
var card = new TaskCompletionSource();
var resumedQueue = new TaskCompletionSource();
var idleRequested = false;
var waiting = NativeActionCompletion.WaitAsync(card.Task, () =>
{
    idleRequested = true;
    return resumedQueue.Task;
});
if (waiting.IsCompleted || idleRequested)
    throw new Exception("A pending choice must not release the live controller.");
card.SetResult();
if (waiting.IsCompleted)
    throw new Exception("Wait for queue cleanup after the choice completes.");
resumedQueue.SetResult();
await waiting;
if (!idleRequested) throw new Exception("Queue cleanup was skipped.");

var cancelled = new TaskCompletionSource();
var afterCancellation = false;
var cancellation = NativeActionCompletion.WaitAsync(cancelled.Task, () =>
{
    afterCancellation = true;
    return Task.CompletedTask;
});
cancelled.SetCanceled();
try
{
    await cancellation;
    throw new Exception("Cancellation must propagate.");
}
catch (OperationCanceledException) { }
if (afterCancellation) throw new Exception("Cancelled actions must not wait for idle.");
await NativeActionCompletion.WaitAsync(Task.CompletedTask, () => Task.CompletedTask);
Console.WriteLine("action completion: launch configuration, ponder cache, worker isolation, paused choice, queue cleanup, cancellation, synchronous completion passed");
