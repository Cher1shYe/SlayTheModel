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
                p.Deck.Cards.Select(c=>new {card=c.Id.Entry,originalIndex=Array.IndexOf(original,c),
                    upgraded=c.IsUpgraded,enchantment=c.Enchantment?.Id.Entry,amount=c.Enchantment?.Amount}).ToArray();
            foreach(string kind in new[]{"pomander","yummy_cookie","paels_tooth"}) {
                session.ChoiceFixtureCards=deck;session.InitialHp=30;
                await session.ResetAsync("NATIVE-RELIC-ROUND2",timeout.Token);
                var player=session.CombatStateForSimulation.Players[0];var original=player.Deck.Cards.ToArray();
                player.RunState.Rng.Niche.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(42).ToSerializable());
                player.PlayerRng.Rewards.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(42).ToSerializable());
                int[] chosen=kind=="pomander"?[2]:kind=="yummy_cookie"?[5,2,3,0]:[5,4,0,2,3];
                var selector=new AuditSelector(chosen.Select(i=>original[i]).ToArray());
                using var select=CardSelectCmd.PushSelector(selector);
                if(kind=="pomander")await RelicCmd.Obtain<Pomander>(player);
                else if(kind=="yummy_cookie")await RelicCmd.Obtain<YummyCookie>(player);
                else await RelicCmd.Obtain<PaelsTooth>(player);
                results.Add(new {test=kind,chosen,selector.calls,selector.candidates,
                    nicheCounter=player.RunState.Rng.Niche.ToSerializable().counter,deck=Snapshot(player,original),
                    stored=player.GetRelic<PaelsTooth>()?.SerializableCards.Select(c=>c.Id.Entry).ToArray()});
                if(kind=="paels_tooth") {
                    await RelicCmd.Obtain<LuckyFysh>(player);await RelicCmd.Obtain<BookOfFiveRings>(player);
                    player.GetRelic<BookOfFiveRings>()!.CardsAdded=4;
                    for(int i=0;i<6;++i) {
                        await player.GetRelic<PaelsTooth>()!.AfterCombatEnd(null!);
                        results.Add(new {test="paels_tooth_return",index=i,deck=Snapshot(player,original),hp=player.Creature.CurrentHp,gold=player.Gold,
                            rewardCounter=player.PlayerRng.Rewards.ToSerializable().counter,
                            stored=player.GetRelic<PaelsTooth>()!.SerializableCards.Select(c=>c.Id.Entry).ToArray()});
                    }
                }
            }
            foreach(string kind in new[]{"war_paint","whetstone","sand_castle","war_paint_empty","sand_castle_duplicates"}) {
                foreach(ulong seed in new ulong[]{0,42}) {
                    session.ChoiceFixtureCards=kind=="sand_castle_duplicates"?Enumerable.Repeat("STRIKE_IRONCLAD",10).Concat(Enumerable.Repeat("DEFEND_IRONCLAD",8)).Concat(new[]{"BASH","ANGER"}).ToArray():deck;
                    session.ChoiceFixtureUpgradedCards=kind=="war_paint_empty"?deck.ToHashSet():[];
                    await session.ResetAsync("NATIVE-RELIC-ROUND2",timeout.Token);
                    var player=session.CombatStateForSimulation.Players[0];var original=player.Deck.Cards.ToArray();
                    player.RunState.Rng.Niche.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(seed).ToSerializable());
                    if(kind.StartsWith("war_paint"))await RelicCmd.Obtain<WarPaint>(player);
                    else if(kind=="whetstone")await RelicCmd.Obtain<Whetstone>(player);
                    else await RelicCmd.Obtain<SandCastle>(player);
                    results.Add(new {test=kind,seed,deck=Snapshot(player,original),nicheCounter=player.RunState.Rng.Niche.ToSerializable().counter});
                }
            }
            foreach(bool hooks in new[]{false,true}) {
                session.ChoiceFixtureCards=Enumerable.Repeat("STRIKE_IRONCLAD",5).Concat(Enumerable.Repeat("DEFEND_IRONCLAD",4)).Append("BASH").ToArray();
                session.ChoiceFixtureUpgradedCards=[];
                await session.ResetAsync("NATIVE-RELIC-ROUND2",timeout.Token);
                var player=session.CombatStateForSimulation.Players[0];var original=player.Deck.Cards.ToArray();
                player.Creature.SetCurrentHpInternal(30);
                player.RunState.Rng.Niche.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(42).ToSerializable());
                if(hooks) {
                    await RelicCmd.Obtain<LuckyFysh>(player);await RelicCmd.Obtain<BookOfFiveRings>(player);await RelicCmd.Obtain<MoltenEgg>(player);
                    await RelicCmd.Obtain<BingBong>(player);player.GetRelic<BookOfFiveRings>()!.CardsAdded=4;
                }
                int gold=player.Gold;
                await RelicCmd.Obtain<PandorasBox>(player);
                results.Add(new {test="pandora",hooks,deck=Snapshot(player,original),goldBefore=gold,goldAfter=player.Gold,hp=player.Creature.CurrentHp,
                    bookCount=player.GetRelic<BookOfFiveRings>()?.CardsAdded,nicheCounter=player.RunState.Rng.Niche.ToSerializable().counter});
            }
            foreach(string kind in new[]{"spiral_strike","nimble_upgraded_defend_frail","steady_retain"}) {
                session.ChoiceFixtureCards=kind=="steady_retain"?deck.Concat(new[]{"BODY_SLAM","THRASH"}).ToArray():new[]{"STRIKE_IRONCLAD","DEFEND_IRONCLAD"};
                session.ChoiceFixtureUpgradedCards=kind=="nimble_upgraded_defend_frail"?new HashSet<string>{"DEFEND_IRONCLAD"}:[];
                session.InitialHp=80;await session.ResetAsync("NATIVE-ENCHANT-ROUND2",timeout.Token);
                var combat=session.CombatStateForSimulation;var player=combat.Players[0];var pc=player.PlayerCombatState!;
                if(kind=="spiral_strike") {
                    var strike=pc.Hand.Cards.Single(c=>c.Id.Entry=="STRIKE_IRONCLAD");
                    CardCmd.Enchant<Spiral>(strike,1);var enemy=combat.Enemies.First();enemy.SetMaxHpInternal(1000);enemy.SetCurrentHpInternal(1000);
                    await session.StepAsync(session.ActionForCard("STRIKE_IRONCLAD"),timeout.Token);int first=1000-enemy.CurrentHp;
                    await CardPileCmd.Add(strike,PileType.Hand,skipVisuals:true);
                    await session.StepAsync(session.ActionForCard("STRIKE_IRONCLAD"),timeout.Token);
                    results.Add(new{test=kind,first,second=1000-first-enemy.CurrentHp});
                } else if(kind=="nimble_upgraded_defend_frail") {
                    CardCmd.Enchant<Nimble>(pc.Hand.Cards.Single(c=>c.Id.Entry=="DEFEND_IRONCLAD"),2);
                    await PowerCmd.Apply<FrailPower>(choice,player.Creature,1,player.Creature,null);
                    await session.StepAsync(session.ActionForCard("DEFEND_IRONCLAD"),timeout.Token);
                    results.Add(new{test=kind,block=player.Creature.Block});
                } else {
                    var defend=pc.Hand.Cards.Single(c=>c.Id.Entry=="DEFEND_IRONCLAD");CardCmd.Enchant<Steady>(defend,1);
                    foreach(var card in pc.Hand.Cards.Where(c=>c.Id.Entry!="STRIKE_IRONCLAD"&&c.Id.Entry!="DEFEND_IRONCLAD").ToArray())
                        await CardPileCmd.Add(card,PileType.Draw,skipVisuals:true);
                    await session.StepAsync(session.Actions().Single(a=>a.Combat?.Kind==SlayTheModel.Sts2.Protocol.CombatActionKind.EndTurn),timeout.Token);
                    results.Add(new{test=kind,handCount=pc.Hand.Cards.Count,retainedDefend=pc.Hand.Cards.Contains(defend),hand=pc.Hand.Cards.Select(c=>c.Id.Entry).ToArray()});
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
