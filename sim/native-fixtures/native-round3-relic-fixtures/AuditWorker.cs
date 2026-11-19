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
            string[] deck = ["BASH", "DEFEND_IRONCLAD", "STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "STRIKE_IRONCLAD", "ANGER", "POMMEL_STRIKE", "IRON_WAVE"];
            object Snapshot(MegaCrit.Sts2.Core.Entities.Players.Player p, CardModel[] original) =>
                p.Deck.Cards.Select(c=>new {card=c.Id.Entry,originalIndex=Array.IndexOf(original,c),upgraded=c.IsUpgraded}).ToArray();
            foreach(string kind in new[]{"distinguished_cape","sere_talon","leafy_poultice","neows_torment"}) {
                foreach(ulong seed in new ulong[]{0,42}) {
                    session.ChoiceFixtureCards=deck;session.InitialHp=80;session.ChoiceFixtureUpgradedCards=[];
                    await session.ResetAsync("NATIVE-RELIC-ROUND3",timeout.Token);
                    var player=session.CombatStateForSimulation.Players[0];var original=player.Deck.Cards.ToArray();
                    player.RunState.Rng.Niche.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(seed).ToSerializable());
                    player.PlayerRng.Transformations.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(seed).ToSerializable());
                    if(kind=="distinguished_cape")await RelicCmd.Obtain<DistinguishedCape>(player);
                    if(kind=="sere_talon")await RelicCmd.Obtain<SereTalon>(player);
                    if(kind=="leafy_poultice")await RelicCmd.Obtain<LeafyPoultice>(player);
                    if(kind=="neows_torment")await RelicCmd.Obtain<NeowsTorment>(player);
                    results.Add(new{test=kind,seed,hp=player.Creature.CurrentHp,maxHp=player.Creature.MaxHp,deck=Snapshot(player,original),
                        transformationOptions=MegaCrit.Sts2.Core.Factories.CardFactory.GetDefaultTransformationOptions(original[0],false).Select(c=>c.Id.Entry).ToArray(),
                        nicheCounter=player.RunState.Rng.Niche.ToSerializable().counter,
                        transformationsCounter=player.PlayerRng.Transformations.ToSerializable().counter});
                }
            }
            foreach(string kind in new[]{"leafy_hooks","leafy_no_basic","sere_tail","sere_tungsten"}) {
                session.ChoiceFixtureCards=kind=="leafy_no_basic"?["BASH","ANGER"]:deck;
                session.InitialHp=80;await session.ResetAsync("NATIVE-RELIC-ROUND3",timeout.Token);
                var player=session.CombatStateForSimulation.Players[0];var original=player.Deck.Cards.ToArray();
                player.RunState.Rng.Niche.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(42).ToSerializable());
                player.PlayerRng.Transformations.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(42).ToSerializable());
                if(kind=="leafy_hooks") {
                    await RelicCmd.Obtain<LuckyFysh>(player);await RelicCmd.Obtain<BookOfFiveRings>(player);await RelicCmd.Obtain<MoltenEgg>(player);
                    await RelicCmd.Obtain<BingBong>(player);player.GetRelic<BookOfFiveRings>()!.CardsAdded=4;
                    player.Creature.SetCurrentHpInternal(30);
                }
                if(kind=="sere_tail") {
                    await RelicCmd.Obtain<LizardTail>(player);player.Creature.SetMaxHpInternal(8);player.Creature.SetCurrentHpInternal(8);
                }
                if(kind=="sere_tungsten") {
                    await RelicCmd.Obtain<TungstenRod>(player);player.Creature.SetMaxHpInternal(10);player.Creature.SetCurrentHpInternal(10);
                }
                int gold=player.Gold;
                if(kind.StartsWith("leafy"))await RelicCmd.Obtain<LeafyPoultice>(player);else await RelicCmd.Obtain<SereTalon>(player);
                results.Add(new{test=kind,hp=player.Creature.CurrentHp,maxHp=player.Creature.MaxHp,goldBefore=gold,goldAfter=player.Gold,
                    deck=Snapshot(player,original),bookCount=player.GetRelic<BookOfFiveRings>()?.CardsAdded,
                    nicheCounter=player.RunState.Rng.Niche.ToSerializable().counter,
                    transformationsCounter=player.PlayerRng.Transformations.ToSerializable().counter});
            }
            foreach(int gold in new[]{0,2,3,4,5,6}) {
                session.ChoiceFixtureCards=deck;session.InitialHp=80;await session.ResetAsync("NATIVE-RELIC-ROUND3",timeout.Token);
                var combat=session.CombatStateForSimulation;var player=combat.Players[0];
                await RelicCmd.Obtain<SealOfGold>(player);player.Gold=gold;
                int energy=player.PlayerCombatState!.Energy;
                await player.GetRelic<SealOfGold>()!.AfterSideTurnStart(MegaCrit.Sts2.Core.Combat.CombatSide.Player,[player.Creature],combat);
                results.Add(new{test="seal_of_gold",goldBefore=gold,goldAfter=player.Gold,energyBefore=energy,energyAfter=player.PlayerCombatState.Energy});
            }
            foreach(ulong seed in new ulong[]{0,42}) {
                foreach(bool empty in new[]{false,true}) {
                    session.ChoiceFixtureCards=deck;session.InitialHp=80;session.ChoiceFixtureUpgradedCards=[];
                    await session.ResetAsync("NATIVE-RELIC-ROUND3",timeout.Token);
                    var combat=session.CombatStateForSimulation;var player=combat.Players[0];
                    foreach(var card in player.PlayerCombatState!.AllCards.ToArray())
                        await CardPileCmd.Add(card,PileType.Draw,skipVisuals:true);
                    var original=player.PlayerCombatState.DrawPile.Cards.ToArray();
                    if(empty)foreach(var card in original)CardCmd.Upgrade(card);
                    await RelicCmd.Obtain<StoneCracker>(player);
                    player.RunState.Rng.CombatCardSelection.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(seed).ToSerializable());
                    await player.GetRelic<StoneCracker>()!.AfterRoomEntered(new MegaCrit.Sts2.Core.Rooms.CombatRoom(combat));
                    results.Add(new{test="stone_cracker",seed,empty,
                        cards=original.Select((c,i)=>new{card=c.Id.Entry,originalIndex=i,upgraded=c.IsUpgraded}).ToArray(),
                        counter=player.RunState.Rng.CombatCardSelection.ToSerializable().counter});
                }
            }
            foreach(int initial in new[]{40,80}) {
                session.ChoiceFixtureCards=deck;session.InitialHp=80;session.ChoiceFixtureUpgradedCards=[];
                await session.ResetAsync("NATIVE-RELIC-ROUND3",timeout.Token);
                var combat=session.CombatStateForSimulation;var player=combat.Players[0];
                await RelicCmd.Obtain<RedSkull>(player);player.Creature.SetCurrentHpInternal(initial);
                await player.GetRelic<RedSkull>()!.AfterRoomEntered(new MegaCrit.Sts2.Core.Rooms.CombatRoom(combat));
                int initialStrength=player.Creature.GetPowerAmount<StrengthPower>();
                if(initial==40) {
                    await CreatureCmd.Heal(player.Creature,1);
                    int healedStrength=player.Creature.GetPowerAmount<StrengthPower>();
                    await CreatureCmd.Damage(choice,player.Creature,2,ValueProp.Unblockable|ValueProp.Unpowered,null,null,null);
                    results.Add(new{test="red_skull_heal_damage",initial,initialStrength,healedStrength,
                        finalHp=player.Creature.CurrentHp,finalStrength=player.Creature.GetPowerAmount<StrengthPower>()});
                } else {
                    await CreatureCmd.Damage(choice,player.Creature,40,ValueProp.Unblockable|ValueProp.Unpowered,null,null,null);
                    results.Add(new{test="red_skull_damage",initial,initialStrength,
                        finalHp=player.Creature.CurrentHp,finalStrength=player.Creature.GetPowerAmount<StrengthPower>()});
                }
            }
            foreach(bool both in new[]{false,true}) {
                session.ChoiceFixtureCards=["STRIKE_IRONCLAD","BASH"];session.InitialHp=80;session.ChoiceFixtureUpgradedCards=[];
                await session.ResetAsync("NATIVE-RELIC-ROUND3",timeout.Token);
                var combat=session.CombatStateForSimulation;var player=combat.Players[0];var enemy=combat.Enemies.First();
                enemy.SetMaxHpInternal(1000);enemy.SetCurrentHpInternal(1000);
                await RelicCmd.Obtain<FakeStrikeDummy>(player);if(both)await RelicCmd.Obtain<StrikeDummy>(player);
                await session.StepAsync(session.ActionForCard("STRIKE_IRONCLAD"),timeout.Token);
                int strike=1000-enemy.CurrentHp;
                await session.StepAsync(session.ActionForCard("BASH"),timeout.Token);
                results.Add(new{test="fake_strike_dummy",both,strike,bash=1000-strike-enemy.CurrentHp});
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
