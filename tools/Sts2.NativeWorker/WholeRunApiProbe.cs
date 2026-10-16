using System.Reflection;
using System.Text;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Nodes;
using MegaCrit.Sts2.Core.Runs;

/// <summary>Read-only inventory of native whole-run entry points in the pinned assembly.</summary>
public static class WholeRunApiProbe
{
    public static void Write(string output)
    {
        var assembly = typeof(RunManager).Assembly;
        var types = assembly.GetTypes().Where(type =>
            type.FullName?.StartsWith("MegaCrit.Sts2.Core.", StringComparison.Ordinal) == true
            && (type.Name is "RunManager" or "RunState" or "ActModel" or "MapPoint" or "Map"
                or "Room" or "CombatRoom" or "EventRoom" or "RewardsRoom" or "Reward"
                or "NeowRoom" or "NeowEvent" or "NonInteractiveMode" or "EventModel"
                or "EventOption" or "EventOptionModel" or "EventOptionState"
                || type.Name.Contains("Map", StringComparison.Ordinal)
                || type.Name.Contains("Reward", StringComparison.Ordinal)
                || type.Name.Contains("Neow", StringComparison.Ordinal)
                || type.Name.Contains("Encounter", StringComparison.Ordinal)))
            .OrderBy(type => type.FullName, StringComparer.Ordinal);

        var result = new StringBuilder();
        foreach (var type in types)
        {
            var methods = type.GetMethods(BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic)
                .Where(method => method.DeclaringType == type && !method.IsSpecialName)
                .Where(method => type.Name is "RunManager" or "RunState" or "MapPoint" or "Map" or "Room" or "EventModel"
                    || HasActionName(method.Name))
                .OrderBy(method => method.Name, StringComparer.Ordinal)
                .ToArray();
            if (methods.Length == 0) continue;
            result.AppendLine(type.FullName);
            foreach (var method in methods)
            {
                string parameters = string.Join(", ", method.GetParameters().Select(parameter =>
                    parameter.ParameterType.Name + " " + parameter.Name));
                result.Append("  ").Append(method.IsPublic ? "public " : "private ")
                    .Append(method.IsStatic ? "static " : "")
                    .Append(method.ReturnType.Name).Append(' ').Append(method.Name)
                    .Append('(').Append(parameters).AppendLine(")");
            }
        }
        result.AppendLine("Selected native call chains");
        var discoveryProperty = typeof(RunManager).GetProperty("ForceDiscoveryOrderModifications",
            BindingFlags.Instance | BindingFlags.Static | BindingFlags.Public | BindingFlags.NonPublic);
        result.AppendLine("ForceDiscoveryOrderModifications: "
            + discoveryProperty?.PropertyType.Name + " getter=" + discoveryProperty?.GetMethod
            + " setter=" + discoveryProperty?.SetMethod);
        foreach (var (type, methodName) in new[]
        {
            (typeof(RunManager), "EnterMapCoord"),
            (typeof(RunManager), "EnterMapCoordInternal"),
            (typeof(RunManager), "EnterMapPointInternal"),
            (typeof(RunManager), "EnterAct"),
            (typeof(RunManager), "SetUpNewSingleplayer"),
            (typeof(RunManager), "InitializeNewRun"),
            (typeof(RunManager), "GenerateRooms"),
            (typeof(RunManager), "SetActInternal"),
            (typeof(RunManager), "ShouldApplyTutorialModifications"),
            (typeof(RunManager), "RollRoomTypeFor"),
            (typeof(RunManager), "CreateRoom"),
            (typeof(ActModel), "GenerateRooms"),
            (typeof(ActModel), "ApplyDiscoveryOrderModifications"),
            (typeof(ActModel), "ApplyActDiscoveryOrderModifications"),
            (typeof(NGame), "StartNewSingleplayerRun"),
            (typeof(NGame), "StartRun"),
            (typeof(RunState), "CreateForNewRun"),
        })
        {
            result.AppendLine($"  {type.Name}.{methodName}");
            foreach (var call in WholeRunSpeedProbe.DescribeAsyncCalls(type, methodName))
                result.AppendLine("    " + call);
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
        File.WriteAllText(output, result.ToString());
        Godot.GD.Print($"WHOLE_RUN_API_PROBE types={types.Count()} output={output}");
    }

    private static bool HasActionName(string name) =>
        new[] { "Start", "Enter", "Travel", "Proceed", "Select", "Choose", "Claim", "Grant", "Finish", "Generate", "Resolve", "Create" }
            .Any(token => name.Contains(token, StringComparison.OrdinalIgnoreCase));
}
