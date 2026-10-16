using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text.Json;
using HarmonyLib;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Hooks;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Cards;
using MegaCrit.Sts2.Core.Models.Encounters;
using MegaCrit.Sts2.Core.Models.Relics;
using MegaCrit.Sts2.Core.Multiplayer;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Sts2.DataCollector;

// Production capture source is linked unchanged. Native data objects are
// initialized in this process by reflection; a small diagnostic sink replaces
// the journal. Lifecycle callbacks are explicitly driven, not a game run.
Set(RunManager.Instance, "<NetService>k__BackingField", Blank<NetSingleplayerGameService>());

var original = AccessTools.Method(typeof(Hook), nameof(Hook.BeforeCombatStart),
    [typeof(IRunState), typeof(ICombatState)])
    ?? throw new Exception("Native BeforeCombatStart ABI missing");
var patcher = new Harmony("SlayTheModel.ActRewardCapture.Smoke");
patcher.Patch(original, prefix: new HarmonyMethod(typeof(CollectorRuntime), nameof(CollectorRuntime.TestPrefix)));
Check(Harmony.GetPatchInfo(original)!.Prefixes.Any(patch => patch.owner == patcher.Id), "native hook patch ABI");
patcher.Unpatch(original, HarmonyPatchType.All, patcher.Id);

var ordinary = Fixture(boss: false);
CollectorRuntime.TestReset();
CollectorRuntime.CaptureActRewardCombatStart(ordinary.Run, ordinary.State);
CollectorRuntime.CaptureActRewardCombatStart(ordinary.Run, ordinary.State);
Check(CollectorRuntime.Events.Count == 1, "duplicate combat start");
var start = CollectorRuntime.Events[0].Data;
Check(start.GetProperty("hp").GetInt32() == 70, "start HP frozen");
Check(start.GetProperty("upgraded_cards").GetInt32() == 2, "permanent deck upgrade count");
Check(start.GetProperty("relics").GetInt32() == 1, "starting relic included");
Check(start.GetProperty("won").ValueKind == JsonValueKind.Null, "start outcome unknown");
Check(start.GetProperty("combat_id").GetGuid() == CollectorRuntime.TestCombatId(ordinary.State), "shared combat ID");
Set(ordinary.Player.Creature, "_currentHp", 66);
CollectorRuntime.TestWon(ordinary.Room);
CollectorRuntime.TestEnded(ordinary.Room);
CollectorRuntime.TestWon(ordinary.Room);
Check(CollectorRuntime.Events.Count == 2, "duplicate victory/end notifications");
var end = CollectorRuntime.Events[1].Data;
Check(end.GetProperty("hp").GetInt32() == 66 && start.GetProperty("hp").GetInt32() == 70, "end HP sampled separately");
Check(!end.GetProperty("act_completed").GetBoolean(), "ordinary victory is not act completion");
Check(end.GetProperty("combat_id").GetGuid() == start.GetProperty("combat_id").GetGuid(), "paired IDs");

foreach (var (doubleBoss, second, completes) in new[] { (false, false, true), (true, false, false), (true, true, true) })
{
    var boss = Fixture(boss: true, doubleBoss, second);
    CollectorRuntime.TestReset();
    CollectorRuntime.CaptureActRewardCombatStart(boss.Run, boss.State);
    CollectorRuntime.TestWon(boss.Room);
    Check(CollectorRuntime.Events[1].Data.GetProperty("act_completed").GetBoolean() == completes, "native final boss map condition");
}

var fatal = Fixture(boss: true);
CollectorRuntime.TestReset();
CollectorRuntime.CaptureActRewardCombatStart(fatal.Run, fatal.State);
Set(fatal.Player.Creature, "_currentHp", 0);
Set(fatal.Run, "<Map>k__BackingField", null); // Terminal loss must not need a surviving map.
CollectorRuntime.TestTerminal(new RunHistory { Win = false, WasAbandoned = false });
CollectorRuntime.TestEnded(fatal.Room);
Check(CollectorRuntime.Events.Count == 2, "terminal death fallback once");
Check(!CollectorRuntime.Events[1].Data.GetProperty("won").GetBoolean(), "death not inferred as victory");
Check(!CollectorRuntime.Events[1].Data.GetProperty("act_completed").GetBoolean(), "boss death does not complete act");

var abandoned = Fixture(boss: false);
CollectorRuntime.TestReset();
CollectorRuntime.CaptureActRewardCombatStart(abandoned.Run, abandoned.State);
CollectorRuntime.TestTerminal(new RunHistory { Win = false, WasAbandoned = true });
Check(CollectorRuntime.Events[1].Code == "act_reward_boundary_unavailable", "abandonment is not combat loss");

var unsupported = Fixture(boss: false);
Set(unsupported.Run, "<Acts>k__BackingField", new ActModel[4]);
CollectorRuntime.TestReset();
CollectorRuntime.CaptureActRewardCombatStart(unsupported.Run, unsupported.State);
Check(CollectorRuntime.Events.Single().Code == "act_reward_boundary_unavailable", "unsupported act count fails closed");

CollectorRuntime.TestReset();
Check(CollectorRuntime.TestCombatId(ordinary.State) is null, "detach/load reset clears prior identity");
CollectorRuntime.CaptureActRewardCombatStart(ordinary.Run, ordinary.State);
Check(CollectorRuntime.Events.Count == 1, "reset admits a new capture");
Console.WriteLine("act_reward_capture_smoke=ok native_objects=true lifecycle=simulated game_started=false");

static void Check(bool condition, string description)
{
    if (!condition) throw new Exception(description);
}

static T Blank<T>() => (T)RuntimeHelpers.GetUninitializedObject(typeof(T));

static void Set(object target, string name, object? value)
{
    for (var type = target.GetType(); type is not null; type = type.BaseType)
    {
        if (type.GetField(name, BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly) is { } field)
        {
            field.SetValue(target, value);
            return;
        }
    }
    throw new MissingFieldException(target.GetType().FullName, name);
}

static (RunState Run, CombatState State, CombatRoom Room, Player Player) Fixture(
    bool boss, bool doubleBoss = false, bool second = false)
{
    var run = Blank<RunState>();
    var player = Blank<Player>();
    var creature = Blank<Creature>();
    Set(creature, "<Player>k__BackingField", player);
    Set(creature, "_currentHp", 70);
    Set(creature, "_maxHp", 80);
    Set(player, "<Creature>k__BackingField", creature);
    var cards = Enumerable.Range(0, 3).Select(index =>
    {
        var card = Blank<StrikeIronclad>();
        Set(card, "_currentUpgradeLevel", index == 0 ? 0 : 1);
        return (CardModel)card;
    }).ToList();
    var deck = new CardPile(PileType.Deck);
    Set(deck, "_cards", cards);
    Set(player, "<Deck>k__BackingField", deck);
    Set(player, "_relics", new List<RelicModel> { Blank<BurningBlood>() });
    Set(run, "_players", new List<Player> { player });
    Set(run, "<Acts>k__BackingField", new ActModel[3]);
    var map = new TestActMap(doubleBoss);
    Set(run, "<Map>k__BackingField", map);
    Set(run, "_visitedMapCoords", new List<MapCoord> { second ? map.SecondBossMapPoint!.coord : map.BossMapPoint.coord });
    var state = Blank<CombatState>();
    Set(state, "<RunState>k__BackingField", run);
    Set(state, "_allies", new List<Creature> { creature });
    Set(state, "_enemies", new List<Creature>());
    Set(state, "_encounter", boss ? Blank<WaterfallGiantBoss>() : (EncounterModel)Blank<CultistsNormal>());
    var room = new CombatRoom(state);
    Set(run, "_currentRooms", new List<AbstractRoom> { room });
    return (run, state, room, player);
}

sealed class TestActMap(bool doubleBoss) : ActMap
{
    public override MapPoint BossMapPoint { get; } = new(3, 16);
    public override MapPoint? SecondBossMapPoint { get; } = doubleBoss ? new(3, 17) : null;
    public override MapPoint StartingMapPoint { get; } = new(3, 0);
    protected override MapPoint?[,] Grid { get; } = new MapPoint?[7, 18];
}

namespace SlayTheModel.Sts2.DataCollector
{
    internal static partial class CollectorRuntime
    {
        private sealed class TestEpisodeSink
        {
            public bool HasActiveEpisode => true;
        }

        private static readonly TestEpisodeSink _episodes = new();
        internal static List<(string Code, JsonElement Data)> Events { get; } = [];
        internal static void RecordDiagnostic(string code, object data) =>
            Events.Add((code, JsonSerializer.SerializeToElement(data)));
        internal static void TestPrefix(IRunState runState, ICombatState? combatState) =>
            CaptureActRewardCombatStart(runState, combatState);
        internal static void TestWon(CombatRoom room) => OnActRewardCombatWon(room);
        internal static void TestEnded(CombatRoom room) => CaptureActRewardCombatEnded(room);
        internal static void TestTerminal(RunHistory history) => CaptureActRewardTerminalBoundary(history);
        internal static Guid? TestCombatId(CombatState state) => ActRewardCombatId(state);
        internal static void TestReset()
        {
            ResetActRewardCapture();
            Events.Clear();
        }
    }
}
