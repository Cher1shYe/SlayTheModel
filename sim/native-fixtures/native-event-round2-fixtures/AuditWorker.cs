using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Enchantments;
using MegaCrit.Sts2.Core.Models.Powers;
using MegaCrit.Sts2.Core.Models.Relics;
using MegaCrit.Sts2.Core.TestSupport;
using MegaCrit.Sts2.Core.ValueProps;

public partial class AuditWorker : Node
{
    readonly List<object> results = [];
    public override async void _Ready()
    {
        string output = System.Environment.GetEnvironmentVariable("STS2_AUDIT_OUT")!;
        try
        {
            TestMode.IsOn = true;
            NonInteractiveMode.AutoSlayerCheck = () => true;
            MegaCrit.Sts2.Core.Context.LocalContext.NetId = 1;
            if (!ProjectSettings.LoadResourcePack(System.Environment.GetEnvironmentVariable("STS2_GAME_PACK")!, false))
                throw new IOException("Game pack failed to load");
            await OneTimeInitialization.ExecuteVeryEarly();
            var saves = MegaCrit.Sts2.Core.Saves.SaveManager.Instance;
            saves.InitPrefsDataForTest();
            saves.InitProfileId();
            OneTimeInitialization.ExecuteEssential();
            saves.InitProgressData();
            typeof(NativeSession).Assembly.GetType("NativeReplayCompatibilityPatches")!
                .GetMethod("Install", BindingFlags.Static | BindingFlags.Public)!.Invoke(null, null);
            CombatSolver.Api.NativeMctsSimulationApi.Initialize();
            SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.CaptureEnabled = false;
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(90));
            var session = new NativeSession(this) { ChoiceFixture = true };
            var choice = new ThrowingPlayerChoiceContext();
            string[] deck = ["STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH", "ANGER", "POMMEL_STRIKE", "IRON_WAVE"];
            object Snapshot(MegaCrit.Sts2.Core.Entities.Players.Player p, CardModel[] original) =>
                p.Deck.Cards.Select(c=>new { card=c.Id.Entry, originalIndex=Array.IndexOf(original,c),
                    upgraded=c.IsUpgraded, enchantment=c.Enchantment?.Id.Entry, amount=c.Enchantment?.Amount }).ToArray();
            async Task InvokeEvent(EventModel e,string method) {
                var task=(Task)e.GetType().GetMethod(method,BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(e,null)!;
                await task;
            }
            foreach (string kind in new[]{"baths_immerse","baths_abstain","treasury_small","treasury_large","doors_light"}) {
                foreach(ulong seed in new ulong[]{0,42,987654321}) {
                    session.ChoiceFixtureCards=deck; session.InitialHp=40;
                    await session.ResetAsync("SIM-AUDIT-EVENT",timeout.Token);
                    var player=session.CombatStateForSimulation.Players[0];
                    var original=player.Deck.Cards.ToArray();
                    EventModel ev=kind.StartsWith("baths")?ModelDb.Event<MegaCrit.Sts2.Core.Models.Events.AbyssalBaths>().ToMutable():
                        kind.StartsWith("treasury")?ModelDb.Event<MegaCrit.Sts2.Core.Models.Events.SunkenTreasury>().ToMutable():
                        ModelDb.Event<MegaCrit.Sts2.Core.Models.Events.DoorsOfLightAndDark>().ToMutable();
                    await ev.BeginEvent(player,null,false);
                    ev.Rng.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(seed).ToSerializable());
                    var steps=new List<object>();
                    int goldBefore=player.Gold;
                    if(kind=="baths_immerse") {
                        await InvokeEvent(ev,"Immerse");
                        steps.Add(new {hp=player.Creature.CurrentHp,maxHp=player.Creature.MaxHp});
                        for(int step=0;step<5;++step) {
                            await InvokeEvent(ev,"Linger");
                            steps.Add(new {hp=player.Creature.CurrentHp,maxHp=player.Creature.MaxHp});
                        }
                        await InvokeEvent(ev,"ExitBaths");
                    } else if(kind=="baths_abstain") await InvokeEvent(ev,"Abstain");
                    else if(kind.StartsWith("treasury")) {
                        ev.DynamicVars["SmallChestGold"].BaseValue=60;
                        ev.DynamicVars["LargeChestGold"].BaseValue=333;
                        ev.CalculateVars();
                        steps.Add(new {small=ev.DynamicVars["SmallChestGold"].IntValue,large=ev.DynamicVars["LargeChestGold"].IntValue});
                        await InvokeEvent(ev,kind=="treasury_small"?"FirstChest":"SecondChest");
                    } else await InvokeEvent(ev,"Light");
                    results.Add(new {test=kind,seed,hp=player.Creature.CurrentHp,maxHp=player.Creature.MaxHp,
                        goldDelta=player.Gold-goldBefore,finished=ev.IsFinished,
                        rngCounter=ev.Rng.ToSerializable().counter,deck=Snapshot(player,original),steps});
                }
            }
            File.WriteAllText(output, JsonSerializer.Serialize(new { status = "completed",
                gameAssemblySha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(ModelDb).Assembly.Location))).ToLowerInvariant(),
                gameSceneLoaded = MegaCrit.Sts2.Core.Nodes.NGame.Instance != null,
                userDirectory = OS.GetUserDataDir(),
                scope = "Controlled native fixtures, not natural runs or full-run parity. No simulator rule patches.", results }, new JsonSerializerOptions { WriteIndented = true }));
            GD.Print("SIM_AUDIT_COMPLETED " + output);
            GetTree().Quit();
        }
        catch (Exception e)
        {
            File.WriteAllText(output, JsonSerializer.Serialize(new { status = "error", error = e.ToString(), results }, new JsonSerializerOptions { WriteIndented = true }));
            GD.PrintErr(e);
            GetTree().Quit(1);
        }
    }
}

internal sealed class AuditSelector(CardModel[] chosen) : ICardSelector {
    public int calls;
    public object? candidates;
    public Task<IEnumerable<CardModel>> GetSelectedCards(IEnumerable<CardModel> options,int minSelect,int maxSelect) {
        ++calls;
        var available=options.ToArray();
        candidates=new {minSelect,maxSelect,cards=available.Select(c=>c.Id.Entry).ToArray()};
        if(chosen.Any(c=>!available.Contains(c))) throw new InvalidOperationException("Requested card absent");
        return Task.FromResult<IEnumerable<CardModel>>(chosen);
    }
    public CardRewardSelection GetSelectedCardReward(IReadOnlyList<CardCreationResult> options,
        IReadOnlyList<MegaCrit.Sts2.Core.Entities.CardRewardAlternatives.CardRewardAlternative> alternatives)
        => throw new NotSupportedException();
}
