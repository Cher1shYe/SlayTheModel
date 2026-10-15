using System.Reflection;
using System.Text.Json;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Sts2.ModAdapter;

internal static class CollectorVerification
{
    internal static async Task RunAsync(NativeSession session, string collectorDll, CancellationToken cancellation)
    {
        var root = Path.Combine(Path.GetTempPath(), "SlayTheModel-policy-collector-" + Guid.NewGuid().ToString("N"));
        Environment.SetEnvironmentVariable("SLAY_THE_MODEL_DATASET_DIR", root);
        Environment.SetEnvironmentVariable("SLAY_THE_MODEL_COMBAT_POLICY", "mcts");
        Environment.SetEnvironmentVariable("SLAY_THE_MODEL_COLLECTOR_ENABLED", "1");
        var assembly = System.Runtime.Loader.AssemblyLoadContext.GetLoadContext(typeof(Worker).Assembly)!
            .LoadFromAssemblyPath(Path.GetFullPath(collectorDll));
        assembly.GetType("SlayTheModel.Sts2.DataCollector.CollectorBootstrap")!
            .GetMethod("Initialize")!.Invoke(null, null);
        var runtime = assembly.GetType("SlayTheModel.Sts2.DataCollector.CollectorRuntime")!;
        // TestMode forbids UI-facing StateTracker subscriptions. Production
        // keeps this subscription; exercise the action/choice hooks here.
        var tracker = MegaCrit.Sts2.Core.Combat.CombatManager.Instance.StateTracker;
        var changed = tracker.GetType().GetEvent("CombatStateChanged")!;
        changed.RemoveEventHandler(tracker, Delegate.CreateDelegate(changed.EventHandlerType!,
            runtime.GetMethod("OnCombatStateChanged", BindingFlags.Static | BindingFlags.NonPublic)!));
        object? Call(string name, params object?[] args) => runtime.GetMethod(name,
            BindingFlags.Static | BindingFlags.NonPublic)!.Invoke(null, args);
        session.Checkpoint = null;
        session.ChoiceFixture = true;
        session.ChoiceFixtureCards = ["HEADBUTT", "DEFEND_IRONCLAD", "DEFEND_IRONCLAD", "BASH", "STRIKE_IRONCLAD"];
        await session.ResetAsync("COLLECTOR-POLICY-CHOICE", cancellation);
        // SetUpTest intentionally bypasses native new-run/save setup. Supply
        // those lifecycle boundaries explicitly in this isolated test process.
        var run = RunManager.Instance.DebugOnlyGetState()!;
        Call("PrepareNewRun", run, null);
        Call("OnRunStarted", run);
        Call("OnCombatBegan", session.CombatStateForSimulation);
        await session.StepAsync(session.ActionForCard("DEFEND_IRONCLAD"), cancellation);
        await session.StepAsync(session.ActionForCard("DEFEND_IRONCLAD"), cancellation);
        await session.StepAsync(session.ActionForCard("HEADBUTT"), cancellation);
        var options = (CardModel[])typeof(NativeSession).GetField("_options", BindingFlags.Instance | BindingFlags.NonPublic)!.GetValue(session)!;
        var choice = session.Actions().First(action => action.Selection is [1]);
        PolicyChoiceCapture.Record(options, 1, 1, [options[1]]);
        await session.StepAsync(choice, cancellation);
        Call("OnTreeExiting");
        var path = Directory.GetFiles(Path.Combine(root, "episodes", "_open"), "*.partial").Single();
        var events = File.ReadLines(path).Select(line => JsonDocument.Parse(line)).ToArray();
        var choices = events.Where(item => item.RootElement.GetProperty("event_type").GetString() == "decision"
            && item.RootElement.GetProperty("payload").ToString().Contains("mcts_card_choice", StringComparison.Ordinal)).ToArray();
        var gaps = events.Where(item => item.RootElement.GetProperty("event_type").GetString() == "coverage_gap").ToArray();
        if (choices.Length != 1 || gaps.Length != 0)
            throw new InvalidDataException($"Policy collector: choices={choices.Length}, gaps={gaps.Length}; inspect {path}");
        foreach (var kind in new[] { "decision", "action_submitted", "execution_result", "reward" })
            if (events.Count(item => item.RootElement.GetProperty("event_type").GetString() == kind) != 4)
                throw new InvalidDataException($"Policy collector lost {kind} records; inspect {path}");
        if (events.Where(item => item.RootElement.GetProperty("event_type").GetString() == "action_submitted")
            .Any(item => item.RootElement.GetProperty("payload").GetProperty("policy").GetProperty("actor").GetString() != "policy"))
            throw new InvalidDataException("Automated input was mislabeled as human.");
        Godot.GD.Print($"SLAY_WORKER_COLLECTOR_POLICY_MATCH four decisions/actions/results/rewards, policy actor, zero gaps; journal={path}");
        foreach (var item in events) item.Dispose();
    }
}
