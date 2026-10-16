using Godot;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using Environment = System.Environment;

namespace SlayTheModel.Headless;

/// <summary>
/// Explicit local integration-test fixture. This uses the game's developer room
/// entry and therefore does not represent a naturally reached training episode.
/// Invoke on the Godot main thread after ordinary new-run initialization finishes.
/// Unset STS2_HEADLESS_SCENARIO for ordinary play; there is no network debug action.
/// </summary>
internal static class NativeSmokeScenario
{
    internal static string? ConfiguredName
    {
        get
        {
            var value = Environment.GetEnvironmentVariable("STS2_HEADLESS_SCENARIO")?.Trim();
            return string.IsNullOrEmpty(value) ? null : value.ToLowerInvariant();
        }
    }

    /// <returns>True only when an explicitly configured test room was entered.</returns>
    internal static async Task<bool> EnterConfiguredAsync(Action<string>? log = null)
    {
        var name = ConfiguredName;
        if (name is null) return false;
        if (!RunManager.Instance.IsInProgress)
            throw new InvalidOperationException("A headless smoke scenario requires an initialized native run.");

        var eventId = name switch
        {
            "crystal-sphere" => "CRYSTAL_SPHERE",
            "fake-merchant" => "FAKE_MERCHANT",
            "trial" => "TRIAL",
            "transform" => "MORPHIC_GROVE",
            "upgrade" => "SPIRIT_GRAFTER",
            "enchant" => "WATERLOGGED_SCRIPTORIUM",
            "merchant" or "treasure" or "rest" => null,
            _ when name.StartsWith("event:", StringComparison.Ordinal) => name[6..].ToUpperInvariant(),
            _ => throw new ArgumentException(
                "Unknown STS2_HEADLESS_SCENARIO. Use crystal-sphere, merchant, fake-merchant, trial, "
                + "transform, upgrade, enchant, treasure, rest, or event:EXACT_EVENT_ID."),
        };

        EventModel? eventModel = null;
        if (eventId is not null)
        {
            // Match the native event console's canonical database lookup, including
            // ancient events. EventRoom creates the mutable event through native code.
            eventModel = ModelDb.AllEvents.Concat(ModelDb.AllAncients)
                .FirstOrDefault(model => model.Id.Entry == eventId)
                ?? throw new ArgumentException($"Native event '{eventId}' does not exist in this game version.");
        }

        var roomType = eventModel is not null ? RoomType.Event : name switch
        {
            "merchant" => RoomType.Shop,
            "treasure" => RoomType.Treasure,
            "rest" => RoomType.RestSite,
            _ => throw new InvalidOperationException("The smoke fixture did not resolve a native room."),
        };
        var pointType = eventModel is AncientEventModel ? MapPointType.Ancient
            : eventModel is not null ? MapPointType.Unknown : MapPointType.Unassigned;

        string message = $"测试场景：{name}。使用原生开发房间入口；本局不能作为正常训练轨迹。";
        GD.Print("HEADLESS_TEST_SCENARIO " + name);
        log?.Invoke(message);
        // Keep the initialized run's seed, RNG streams, player, and native events.
        // EnterRoomDebug owns room teardown/setup and history; no effect is forged.
        await RunManager.Instance.EnterRoomDebug(roomType, pointType, eventModel, showTransition: false);
        log?.Invoke($"测试场景已进入：{name}。通过正常动作菜单继续。 ");
        return true;
    }
}
