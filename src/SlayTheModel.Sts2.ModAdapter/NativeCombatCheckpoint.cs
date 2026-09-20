using System.Security.Cryptography;
using HarmonyLib;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.Multiplayer.Serialization;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves;
using MegaCrit.Sts2.Core.Saves.Runs;

namespace SlayTheModel.Sts2.ModAdapter;

public sealed record NativeCombatCheckpoint(string AssemblyHash, string RunPacket, string RoomPacket,
    int ActFloor, uint NextActionId, uint NextHookId, List<uint> ChoiceIds, List<int> RewardIds)
{
    private static readonly string CurrentAssemblyHash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(RunManager).Assembly.Location)));
    public static bool CaptureEnabled { get; set; } = true;
    public static NativeCombatCheckpoint? Latest { get; private set; }

    public static void EnableCapture()
    {
        new Harmony("SlayTheModel.Checkpoint").Patch(
            AccessTools.Method(typeof(CombatRoom), "StartCombat"),
            prefix: new HarmonyMethod(typeof(NativeCombatCheckpoint), nameof(Capture)));
    }

    private static void Capture(CombatRoom __instance)
    {
        if (!CaptureEnabled) return;
        Latest = null;
        try
        {
            var manager = RunManager.Instance;
            var run = manager.DebugOnlyGetState();
            if (run == null || run.Players.Count != 1) return;
            Latest = new NativeCombatCheckpoint(
                CurrentAssemblyHash,
                Encode(manager.ToSave(null)), Encode(__instance.ToSerializable()), run.ActFloor,
                manager.ActionQueueSet.NextActionId, manager.ActionQueueSynchronizer.NextHookId,
                manager.PlayerChoiceSynchronizer.ChoiceIds.ToList(), manager.RewardsSetSynchronizer.GetNextRewardIds().ToList());
        }
        catch (Exception exception)
        {
            // A checkpoint failure must never prevent the real combat from starting.
            Console.Error.WriteLine("[SlayTheModel] checkpoint unavailable: " + exception);
        }
    }

    public static string Encode<T>(T value) where T : IPacketSerializable
    {
        var writer = new PacketWriter();
        writer.Write(value);
        return Convert.ToBase64String(writer.Buffer, 0, writer.BytePosition);
    }

    public static T Decode<T>(string value) where T : IPacketSerializable, new()
    {
        var reader = new PacketReader();
        reader.Reset(Convert.FromBase64String(value));
        return reader.Read<T>();
    }

    public static string StateKey()
    {
        var run = RunManager.Instance.DebugOnlyGetState() ?? throw new InvalidOperationException("No run.");
        var packet = Convert.FromBase64String(Encode(NetFullCombatState.FromRun(run, null)));
        return Convert.ToHexString(SHA256.HashData(packet));
    }
}
