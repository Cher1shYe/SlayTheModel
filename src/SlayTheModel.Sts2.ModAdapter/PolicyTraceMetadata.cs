using System.Reflection;
using System.Text.Json;

namespace SlayTheModel.Sts2.ModAdapter;

/// <summary>Audit-only origin metadata. Never carries a checkpoint, RNG or state key.</summary>
internal static class PolicyTraceMetadata
{
    private static string Revision => typeof(PolicyTraceMetadata).Assembly
        .GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion
        ?? typeof(PolicyTraceMetadata).Assembly.GetName().Version?.ToString() ?? "unknown";

    internal static string NativeMcts(NativeMctsResponse response) => JsonSerializer.Serialize(new
    {
        version = 1,
        actor = "policy",
        policy_id = "native-mcts",
        model_revision = Revision,
        teacher_information = "native_checkpoint_privileged",
        search = new
        {
            simulations = response.Simulations,
            retained_visits = response.RetainedVisits,
            search_milliseconds = response.SearchMilliseconds,
            state_transitions = response.StateTransitions,
            rebuilt = response.Rebuilt,
            simulator_backend = response.SimulatorBackend,
        },
    });

    internal static string FirstLegal() => JsonSerializer.Serialize(new
    {
        version = 1,
        actor = "policy",
        policy_id = "first-legal",
        model_revision = Revision,
        teacher_information = "public_observation",
    });
}
