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
            foreach (string kind in new[]{"dense_trudge","dense_tungsten","dense_fairy","dense_tail",
                "aroma_upgrade","aroma_transform","wellspring_bathe","spirit_rejection","spirit_tungsten",
                "tablet_giveup","tablet_five","sunken_dive","this_plain","lost_search"}) {
                foreach(ulong seed in new ulong[]{0,42,987654321}) {
                    session.ChoiceFixtureCards=deck;
                    session.InitialHp=kind is "dense_fairy" or "dense_tail"?3:40;
                    session.InitialRelicIds=kind.EndsWith("tungsten")?["TUNGSTEN_ROD"]:
                        kind=="dense_tail"?["LIZARD_TAIL"]:["BURNING_BLOOD"];
                    session.InitialPotions=kind=="dense_fairy"?[(0,"FAIRY_IN_A_BOTTLE")]:[];
                    await session.ResetAsync("SIM-AUDIT-EVENT-ROUND3",timeout.Token);
                    var player=session.CombatStateForSimulation.Players[0];
                    var original=player.Deck.Cards.ToArray();
                    EventModel ev=kind.StartsWith("dense")?ModelDb.Event<MegaCrit.Sts2.Core.Models.Events.DenseVegetation>().ToMutable():
                        kind.StartsWith("aroma")?ModelDb.Event<MegaCrit.Sts2.Core.Models.Events.AromaOfChaos>().ToMutable():
                        kind.StartsWith("wellspring")?ModelDb.Event<MegaCrit.Sts2.Core.Models.Events.Wellspring>().ToMutable():
                        kind.StartsWith("spirit")?ModelDb.Event<MegaCrit.Sts2.Core.Models.Events.SpiritGrafter>().ToMutable():
                        kind.StartsWith("tablet")?ModelDb.Event<MegaCrit.Sts2.Core.Models.Events.TabletOfTruth>().ToMutable():
                        kind.StartsWith("sunken")?ModelDb.Event<MegaCrit.Sts2.Core.Models.Events.SunkenStatue>().ToMutable():
                        kind.StartsWith("this")?ModelDb.Event<MegaCrit.Sts2.Core.Models.Events.ThisOrThat>().ToMutable():
                        ModelDb.Event<MegaCrit.Sts2.Core.Models.Events.LostWisp>().ToMutable();
                    await ev.BeginEvent(player,null,false);
                    ev.Rng.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(seed).ToSerializable());
                    if(kind.StartsWith("sunken"))ev.DynamicVars.Gold.BaseValue=111;
                    if(kind.StartsWith("lost"))ev.DynamicVars.Gold.BaseValue=60;
                    ev.CalculateVars();
                    var selector=new AuditSelector([original[2]]);
                    using var select=CardSelectCmd.PushSelector(selector);
                    var steps=new List<object>();
                    int goldBefore=player.Gold;
                    if(kind.StartsWith("dense"))await InvokeEvent(ev,"TrudgeOn");
                    else if(kind.StartsWith("aroma"))await InvokeEvent(ev,kind=="aroma_transform"?"LetGo":"MaintainControl");
                    else if(kind.StartsWith("wellspring"))await InvokeEvent(ev,"Bathe");
                    else if(kind.StartsWith("spirit"))await InvokeEvent(ev,"Rejection");
                    else if(kind.StartsWith("tablet")) {
                        for(int step=0;step<(kind=="tablet_five"?5:1);++step) {
                            await InvokeEvent(ev,"Decipher");
                            steps.Add(new {hp=player.Creature.CurrentHp,maxHp=player.Creature.MaxHp,
                                rngCounter=ev.Rng.ToSerializable().counter,deck=Snapshot(player,original)});
                        }
                        if(kind=="tablet_giveup")await InvokeEvent(ev,"GiveUp");
                    } else if(kind=="sunken_dive")await InvokeEvent(ev,"DiveIntoWater");
                    else if(kind=="this_plain")await InvokeEvent(ev,"Plain");
                    else await InvokeEvent(ev,"Search");
                    results.Add(new {test=kind,seed,hp=player.Creature.CurrentHp,maxHp=player.Creature.MaxHp,
                        goldDelta=player.Gold-goldBefore,finished=ev.IsFinished,
                        rngCounter=ev.Rng.ToSerializable().counter,deck=Snapshot(player,original),steps,
                        selectorCalls=selector.calls,selector.candidates,potions=player.Potions.Select(p=>p.Id.Entry).ToArray()});
                }
            }
            foreach(string kind in new[]{"rest_entry","rest_heal","rest_upgrade","rest_mailbox_full","rest_mailbox_upgrade","dense_rest_feather"}) {
                session.ChoiceFixtureCards=deck;session.InitialHp=30;session.InitialMaxHp=80;
                session.InitialRelicIds=kind.StartsWith("rest_mailbox")?["TINY_MAILBOX"]:
                    kind=="dense_rest_feather"?["ETERNAL_FEATHER"]:["ETERNAL_FEATHER","VENERABLE_TEA_SET","REGAL_PILLOW","STONE_HUMIDIFIER"];
                session.InitialPotions=kind.StartsWith("rest_mailbox")?[(0,"FIRE_POTION"),(1,"FIRE_POTION"),(2,"FIRE_POTION")]:[];
                await session.ResetAsync("SIM-AUDIT-REST-ROUND3",timeout.Token);
                var player=session.CombatStateForSimulation.Players[0];var original=player.Deck.Cards.ToArray();
                player.PlayerRng.Rewards.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(42).ToSerializable());
                var offered=new List<string>();
                MegaCrit.Sts2.Core.Rewards.RewardsSet.testSelector=set=> {
                    offered.AddRange(set.Rewards.OfType<MegaCrit.Sts2.Core.Rewards.PotionReward>().Select(r=>r.Potion!.Id.Entry));
                    MegaCrit.Sts2.Core.Runs.RunManager.Instance.RewardsSetSynchronizer.SkipLocalRewardsSet();
                    return Task.CompletedTask;
                };
                if(kind=="dense_rest_feather") {
                    var ev=ModelDb.Event<MegaCrit.Sts2.Core.Models.Events.DenseVegetation>().ToMutable();
                    await ev.BeginEvent(player,null,false);
                    MegaCrit.Sts2.Core.Context.LocalContext.NetId=999;
                    await InvokeEvent(ev,"Rest");
                    MegaCrit.Sts2.Core.Context.LocalContext.NetId=1;
                } else {
                    MegaCrit.Sts2.Core.Context.LocalContext.NetId=999;
                    foreach(var relic in player.Relics)await relic.AfterRoomEntered(new MegaCrit.Sts2.Core.Rooms.RestSiteRoom());
                    MegaCrit.Sts2.Core.Context.LocalContext.NetId=1;
                    if(kind=="rest_heal"||kind=="rest_mailbox_full")
                        await MegaCrit.Sts2.Core.Entities.RestSite.HealRestSiteOption.ExecuteRestSiteHeal(player,false);
                    if(kind=="rest_upgrade"||kind=="rest_mailbox_upgrade")CardCmd.Upgrade(original[2]);
                }
                results.Add(new {test=kind,seed=42,hp=player.Creature.CurrentHp,maxHp=player.Creature.MaxHp,
                    teaPending=player.GetRelic<VenerableTeaSet>()?.GainEnergyInNextCombat??false,
                    potions=player.Potions.Select(p=>p.Id.Entry).ToArray(),offered,
                    rewardCounter=player.PlayerRng.Rewards.ToSerializable().counter,deck=Snapshot(player,original)});
                MegaCrit.Sts2.Core.Rewards.RewardsSet.testSelector=null;
            }
            foreach(string kind in new[]{"wellspring_bottle_full","courier_grab_full","courier_ransack_full"}) {
                foreach(ulong seed in new ulong[]{0,42,987654321}) {
                    session.ChoiceFixtureCards=deck;session.InitialHp=40;session.InitialMaxHp=80;
                    session.InitialRelicIds=["BURNING_BLOOD"];
                    session.InitialPotions=[(0,"FIRE_POTION"),(1,"FIRE_POTION"),(2,"FIRE_POTION")];
                    await session.ResetAsync("SIM-AUDIT-POTION-EVENT-ROUND3",timeout.Token);
                    var player=session.CombatStateForSimulation.Players[0];var original=player.Deck.Cards.ToArray();
                    player.PlayerRng.Rewards.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(seed).ToSerializable());
                    var offered=new List<string>();
                    MegaCrit.Sts2.Core.Rewards.RewardsSet.testSelector=set=> {
                        offered.AddRange(set.Rewards.OfType<MegaCrit.Sts2.Core.Rewards.PotionReward>().Select(r=>r.Potion!.Id.Entry));
                        MegaCrit.Sts2.Core.Runs.RunManager.Instance.RewardsSetSynchronizer.SkipLocalRewardsSet();
                        return Task.CompletedTask;
                    };
                    EventModel ev=kind.StartsWith("wellspring")?ModelDb.Event<MegaCrit.Sts2.Core.Models.Events.Wellspring>().ToMutable():
                        ModelDb.Event<MegaCrit.Sts2.Core.Models.Events.PotionCourier>().ToMutable();
                    await ev.BeginEvent(player,null,false);
                    await InvokeEvent(ev,kind.StartsWith("wellspring")?"Bottle":kind.StartsWith("courier_grab")?"GrabPotions":"Ransack");
                    results.Add(new {test=kind,seed,hp=player.Creature.CurrentHp,maxHp=player.Creature.MaxHp,
                        potions=player.Potions.Select(p=>p.Id.Entry).ToArray(),offered,
                        rewardCounter=player.PlayerRng.Rewards.ToSerializable().counter,deck=Snapshot(player,original)});
                    MegaCrit.Sts2.Core.Rewards.RewardsSet.testSelector=null;
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
