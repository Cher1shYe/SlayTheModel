using System.Reflection;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Models;

namespace SlayTheModel.Sts2.DataCollector;

/// <summary>Optional adapter integration; the standalone collector does not load the adapter.</summary>
internal static class CollectorPolicyTelemetry
{
    private const string BridgeType = "SlayTheModel.Sts2.ModAdapter.PolicyDecisionTelemetry";
    private static readonly HashSet<Assembly> SubscribedAssemblies = [];
    private static bool _installed;
    internal static string? AdapterRevision { get; private set; }

    internal static void Install()
    {
        if (_installed) return;
        _installed = true;
        AppDomain.CurrentDomain.AssemblyLoad += (_, args) => TrySubscribe(args.LoadedAssembly);
        foreach (var assembly in AppDomain.CurrentDomain.GetAssemblies()) TrySubscribe(assembly);
    }

    private static void TrySubscribe(Assembly assembly)
    {
        lock (SubscribedAssemblies)
        {
            if (assembly.GetName().Name != "SlayTheModelAdapter"
                || SubscribedAssemblies.Contains(assembly)) return;
            try
            {
                var type = assembly.GetType(BridgeType, throwOnError: false);
                if (type is null) return; // Older adapters remain conservatively unknown.
                var hooks = new (string Name, Delegate Handler)[]
                {
                    ("ActionSubmitting", (Action<GameAction, string>)CollectorRuntime.ObservePolicyActionSubmitting),
                    ("CardChoiceRequested", (Action<object, CardModel[], int, int>)CollectorRuntime.ObserveMctsCardChoiceRequested),
                    ("CardChoiceManualFallback", (Action<object, object>)CollectorRuntime.ObserveMctsCardChoiceManualFallback),
                    ("CardChoiceCompleted", (Action<object, CardModel[]?, Exception?>)CollectorRuntime.ObserveMctsCardChoiceCompleted),
                };
                // Validate the entire ABI before installing any subscription.
                var events = hooks.Select(hook => type.GetEvent(hook.Name,
                    BindingFlags.Public | BindingFlags.Static)
                    ?? throw new MissingMemberException(type.FullName, hook.Name)).ToArray();
                for (var index = 0; index < events.Length; index++)
                    if (events[index].EventHandlerType != hooks[index].Handler.GetType())
                        throw new InvalidDataException($"Unsupported policy telemetry event {events[index].Name}.");
                AdapterRevision = assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion
                    ?? assembly.GetName().Version?.ToString();
                for (var index = 0; index < events.Length; index++)
                    events[index].AddEventHandler(null, hooks[index].Handler);
                SubscribedAssemblies.Add(assembly);
                Console.WriteLine("[SlayTheModel/Collector] native policy telemetry attached");
            }
            catch (Exception exception) when (exception is not OutOfMemoryException)
            {
                Console.Error.WriteLine($"[SlayTheModel/Collector] policy telemetry unavailable: {exception}");
            }
        }
    }
}
