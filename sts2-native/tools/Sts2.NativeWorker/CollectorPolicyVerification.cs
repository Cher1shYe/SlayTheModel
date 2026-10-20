using System.Reflection;
using System.Runtime.Loader;
using System.Text.Json;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Runs;

/// <summary>
/// Runs the real adapter telemetry and standalone collector in the same
/// isolated native worker process. This verifies the bridge from native
/// GameAction/card objects through the collector journal without launching the
/// visible game client.
/// </summary>
internal static class CollectorPolicyVerification
{
    private const string CollectorRuntimeType =
        "SlayTheModel.Sts2.DataCollector.CollectorRuntime";
    private const string PolicyTelemetryType =
        "SlayTheModel.Sts2.ModAdapter.PolicyDecisionTelemetry";

    internal static async Task RunAsync(
        NativeSession session,
        string collectorDll,
        string adapterDll,
        CancellationToken cancellation)
    {
        collectorDll = RequireAssembly(collectorDll, "collector");
        adapterDll = RequireAssembly(adapterDll, "adapter");
        string datasetRoot = Path.Combine(
            Path.GetTempPath(),
            "SlayTheModel-policy-collector-" + Guid.NewGuid().ToString("N"));
        ConfigureCollector(datasetRoot);

        AssemblyLoadContext loadContext = AssemblyLoadContext.GetLoadContext(
            typeof(Worker).Assembly)
            ?? throw new InvalidOperationException("Native worker has no assembly load context.");

        // Initialize first so CollectorPolicyTelemetry observes the adapter's
        // subsequent AssemblyLoad event and validates the complete bridge ABI.
        Assembly collector = loadContext.LoadFromAssemblyPath(collectorDll);
        collector.GetType(
                "SlayTheModel.Sts2.DataCollector.CollectorBootstrap",
                throwOnError: true)!
            .GetMethod("Initialize", BindingFlags.Public | BindingFlags.Static)!
            .Invoke(null, null);
        Type runtime = collector.GetType(CollectorRuntimeType, throwOnError: true)!;
        RemoveStateTrackerSubscription(runtime);

        Assembly adapter = loadContext.LoadFromAssemblyPath(adapterDll);
        Type telemetry = adapter.GetType(PolicyTelemetryType, throwOnError: true)!;
        MethodInfo notifyAction = RequireStaticMethod(
            telemetry, "NotifyActionSubmitting", BindingFlags.Public);
        MethodInfo notifyChoiceRequested = RequireStaticMethod(
            telemetry, "NotifyCardChoiceRequested", BindingFlags.NonPublic);
        MethodInfo notifyChoiceCompleted = RequireStaticMethod(
            telemetry, "NotifyCardChoiceCompleted", BindingFlags.NonPublic);

        string policyJson = JsonSerializer.Serialize(new
        {
            version = 1,
            actor = "policy",
            policy_id = "native-mcts",
            model_revision = "collector-policy-verification",
            teacher_information = "native_checkpoint_privileged",
            search = new
            {
                simulations = 1,
                retained_visits = 0,
                search_milliseconds = 1.0,
                state_transitions = 1,
                rebuilt = true,
                simulator_backend = "combat_solver",
            },
        });

        session.BeforeActionEnqueuedForVerification = action =>
            InvokeTelemetry(notifyAction, action, policyJson);
        session.ChoiceRequestedForVerification = (request, cards, min, max) =>
            InvokeTelemetry(notifyChoiceRequested, request, cards, min, max);
        session.ChoiceCompletedForVerification = (request, cards, exception) =>
            InvokeTelemetry(notifyChoiceCompleted, request, cards, exception);

        try
        {
            session.Checkpoint = null;
            session.ChoiceFixture = true;
            session.ChoiceFixtureCards =
                ["HEADBUTT", "DEFEND_IRONCLAD", "DEFEND_IRONCLAD", "BASH", "STRIKE_IRONCLAD"];
            await session.ResetAsync("COLLECTOR-POLICY-CHOICE", cancellation);

            // Native test setup intentionally bypasses the ordinary run-start
            // events. Supply those exact semantic boundaries to the collector.
            RunState run = RunManager.Instance.DebugOnlyGetState()
                ?? throw new InvalidOperationException("Collector verification has no native run.");
            Call(runtime, "PrepareNewRun", run, null);
            Call(runtime, "OnRunStarted", run);
            Call(runtime, "OnCombatBegan", session.CombatStateForSimulation);

            await session.StepAsync(session.ActionForCard("DEFEND_IRONCLAD"), cancellation);
            await session.StepAsync(session.ActionForCard("DEFEND_IRONCLAD"), cancellation);
            await session.StepAsync(session.ActionForCard("HEADBUTT"), cancellation);
            await session.StepAsync(
                session.Actions().First(action => action.Selection is [1]),
                cancellation);

            Call(runtime, "OnTreeExiting");
            VerifyJournal(datasetRoot);
        }
        finally
        {
            session.BeforeActionEnqueuedForVerification = null;
            session.ChoiceRequestedForVerification = null;
            session.ChoiceCompletedForVerification = null;
            session.ChoiceFixture = false;
        }
    }

    private static string RequireAssembly(string path, string description)
    {
        string fullPath = Path.GetFullPath(path);
        if (!File.Exists(fullPath))
            throw new FileNotFoundException($"The {description} verification assembly was not found.", fullPath);
        return fullPath;
    }

    private static void ConfigureCollector(string datasetRoot)
    {
        Environment.SetEnvironmentVariable("SLAY_THE_MODEL_DATASET_DIR", datasetRoot);
        Environment.SetEnvironmentVariable("SLAY_THE_MODEL_COLLECTOR_ENABLED", "1");
        Environment.SetEnvironmentVariable("SLAY_THE_MODEL_INFORMATION_MODE", "no-sl");
        Environment.SetEnvironmentVariable("SLAY_THE_MODEL_COLLECTOR_ACTOR", "human");
        Environment.SetEnvironmentVariable("SLAY_THE_MODEL_COMBAT_POLICY", "mcts");
        Environment.SetEnvironmentVariable("SLAY_THE_MODEL_OUTSIDE_COMBAT_POLICY", "manual");
    }

    private static MethodInfo RequireStaticMethod(
        Type type,
        string name,
        BindingFlags visibility) =>
        type.GetMethod(name, BindingFlags.Static | visibility)
        ?? throw new MissingMethodException(type.FullName, name);

    private static void InvokeTelemetry(MethodInfo method, params object?[] args)
    {
        try
        {
            method.Invoke(null, args);
        }
        catch (TargetInvocationException exception) when (exception.InnerException is not null)
        {
            throw exception.InnerException;
        }
    }

    private static object? Call(Type runtime, string name, params object?[] args)
    {
        MethodInfo method = runtime.GetMethod(
            name,
            BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
            ?? throw new MissingMethodException(runtime.FullName, name);
        try
        {
            return method.Invoke(null, args);
        }
        catch (TargetInvocationException exception) when (exception.InnerException is not null)
        {
            throw exception.InnerException;
        }
    }

    private static void RemoveStateTrackerSubscription(Type runtime)
    {
        // TestMode forbids this UI-facing callback. Production retains it; the
        // integration test drives stable action/choice boundaries directly.
        object tracker = CombatManager.Instance.StateTracker;
        EventInfo changed = tracker.GetType().GetEvent("CombatStateChanged")
            ?? throw new MissingMemberException(tracker.GetType().FullName, "CombatStateChanged");
        MethodInfo callback = runtime.GetMethod(
            "OnCombatStateChanged",
            BindingFlags.Static | BindingFlags.NonPublic)
            ?? throw new MissingMethodException(runtime.FullName, "OnCombatStateChanged");
        changed.RemoveEventHandler(
            tracker,
            Delegate.CreateDelegate(changed.EventHandlerType!, callback));
    }

    private static void VerifyJournal(string datasetRoot)
    {
        string openDirectory = Path.Combine(datasetRoot, "episodes", "_open");
        string journal = Directory.GetFiles(openDirectory, "*.partial").Single();
        JsonElement[] events = ReadLinesShared(journal)
            .Select(line => JsonDocument.Parse(line).RootElement.Clone())
            .ToArray();

        JsonElement[] gaps = Events(events, "coverage_gap").ToArray();
        if (gaps.Length != 0)
            throw new InvalidDataException(
                $"Policy collector produced {gaps.Length} coverage gaps; inspect {journal}");

        foreach (var (eventType, expected) in new[]
                 {
                     ("decision", 4),
                     ("action_submitted", 4),
                     ("execution_result", 4),
                     ("reward", 4),
                 })
        {
            int actual = Events(events, eventType).Count();
            if (actual != expected)
                throw new InvalidDataException(
                    $"Policy collector wrote {actual} {eventType} events, expected {expected}; inspect {journal}");
        }

        JsonElement[] submissions = Events(events, "action_submitted").ToArray();
        foreach (JsonElement submission in submissions)
        {
            JsonElement policy = submission.GetProperty("payload").GetProperty("policy");
            if (policy.GetProperty("actor").GetString() != "policy"
                || policy.GetProperty("policy_id").GetString() != "native-mcts"
                || policy.GetProperty("teacher_information").GetString()
                    != "native_checkpoint_privileged")
            {
                throw new InvalidDataException(
                    $"Policy collector lost native MCTS provenance; inspect {journal}");
            }
        }

        Godot.GD.Print(
            "SLAY_WORKER_COLLECTOR_POLICY_MATCH "
            + "four native decisions/actions/results/rewards, native-mcts provenance, zero gaps; "
            + $"journal={journal}");
    }

    private static IEnumerable<JsonElement> Events(
        IEnumerable<JsonElement> events,
        string eventType) =>
        events.Where(item =>
            item.GetProperty("event_type").GetString() == eventType);

    private static IEnumerable<string> ReadLinesShared(string path)
    {
        using var stream = new FileStream(
            path,
            FileMode.Open,
            FileAccess.Read,
            FileShare.ReadWrite | FileShare.Delete);
        using var reader = new StreamReader(stream);
        while (reader.ReadLine() is { } line)
            yield return line;
    }
}
