using System.Text.Json;
using SlayTheModel.Collector;

namespace SlayTheModel.Sts2.DataCollector;

/// <summary>Validates the small optional Adapter audit channel; it is never a feature channel.</summary>
internal static class CollectorPolicyOrigin
{
    internal static PolicyTrace UnattributedInput(string configuredPolicy) =>
        configuredPolicy == "manual"
            ? new PolicyTrace(ActionActor.Human, "human-demonstration",
                TeacherInformation: "public_observation")
            : new PolicyTrace(ActionActor.Policy, "observed-automation",
                TeacherInformation: "unknown");

    internal static PolicyTrace Parse(string json)
    {
        using var document = JsonDocument.Parse(json);
        var root = document.RootElement;
        if (root.ValueKind != JsonValueKind.Object
            || root.GetProperty("version").GetInt32() != 1
            || root.GetProperty("actor").GetString() != "policy")
        {
            throw new InvalidDataException("Unsupported policy origin envelope.");
        }
        var id = root.GetProperty("policy_id").GetString();
        var teacher = root.GetProperty("teacher_information").GetString();
        if (id is not ("native-mcts" or "first-legal")
            || teacher != (id == "native-mcts"
                ? "native_checkpoint_privileged" : "public_observation"))
        {
            throw new InvalidDataException("Unrecognized policy or teacher information boundary.");
        }
        var revision = root.GetProperty("model_revision").GetString();
        if (string.IsNullOrWhiteSpace(revision))
        {
            throw new InvalidDataException("Policy implementation revision is missing.");
        }
        return new PolicyTrace(ActionActor.Policy, id, revision,
            TeacherInformation: teacher);
    }

    internal static object? SearchSummary(string json)
    {
        using var document = JsonDocument.Parse(json);
        if (!document.RootElement.TryGetProperty("search", out var search)) return null;
        // Copy named scalar counters only. Future fields cannot accidentally
        // publish a state key, RNG or a serialized checkpoint into the journal.
        return new
        {
            simulations = search.GetProperty("simulations").GetInt32(),
            retained_visits = search.GetProperty("retained_visits").GetInt32(),
            search_milliseconds = search.GetProperty("search_milliseconds").GetDouble(),
            state_transitions = search.GetProperty("state_transitions").GetInt64(),
            rebuilt = search.GetProperty("rebuilt").GetBoolean(),
            simulator_backend = search.GetProperty("simulator_backend").GetString(),
        };
    }
}
