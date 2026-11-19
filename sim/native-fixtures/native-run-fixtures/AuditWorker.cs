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
            foreach (ulong seed in new ulong[]{0, 42, 987654321}) {
                foreach (string kind in new[]{"mushroom", "bracelet"}) {
                    session.ChoiceFixtureCards=deck; session.InitialHp=50;
                    await session.ResetAsync("SIM-AUDIT-RUN",timeout.Token);
                    var player=session.CombatStateForSimulation.Players[0];
                    var original=player.Deck.Cards.ToArray();
                    player.RunState.Rng.Niche.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(seed).ToSerializable());
                    if(kind=="mushroom") await RelicCmd.Obtain<FragrantMushroom>(player);
                    else await RelicCmd.Obtain<BeautifulBracelet>(player);
                    results.Add(new {test=kind,seed,hp=player.Creature.CurrentHp,
                        rngCounter=player.RunState.Rng.Niche.ToSerializable().counter,deck=Snapshot(player,original)});
                }
            }
            foreach (string kind in new[]{"precise_scissors", "empty_cage", "preserved_fog", "astrolabe", "astrolabe_book"}) {
                session.ChoiceFixtureCards=deck; session.InitialHp=30;
                await session.ResetAsync("SIM-AUDIT-RUN",timeout.Token);
                var player=session.CombatStateForSimulation.Players[0];
                var original=player.Deck.Cards.ToArray();
                player.RunState.Rng.Niche.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(42).ToSerializable());
                int[] selected=kind=="precise_scissors"?[2]:kind=="empty_cage"?[4,0]:[4,0,2];
                var selector=new AuditSelector(selected.Select(i=>original[i]).ToArray());
                using var select=CardSelectCmd.PushSelector(selector);
                if(kind=="astrolabe_book") { await RelicCmd.Obtain<BookOfFiveRings>(player); player.GetRelic<BookOfFiveRings>()!.CardsAdded=4; }
                if(kind.StartsWith("astrolabe")) await RelicCmd.Obtain<Astrolabe>(player);
                else if(kind=="precise_scissors") await RelicCmd.Obtain<PreciseScissors>(player);
                else if(kind=="empty_cage") await RelicCmd.Obtain<EmptyCage>(player);
                else await RelicCmd.Obtain<PreservedFog>(player);
                results.Add(new {test=kind,seed=42,selected,selector.calls,selector.candidates,
                    hp=player.Creature.CurrentHp,bookCount=player.GetRelic<BookOfFiveRings>()?.CardsAdded,
                    rngCounter=player.RunState.Rng.Niche.ToSerializable().counter,deck=Snapshot(player,original)});
            }
            foreach (string kind in new[]{"shears_tungsten", "shears_fairy_lizard", "shears_lethal"}) {
                session.ChoiceFixtureCards=deck; session.InitialHp=16;
                await session.ResetAsync("SIM-AUDIT-SHEARS",timeout.Token);
                var player=session.CombatStateForSimulation.Players[0];
                var original=player.Deck.Cards.ToArray();
                if(kind=="shears_tungsten") await RelicCmd.Obtain<TungstenRod>(player);
                if(kind=="shears_fairy_lizard") {
                    await RelicCmd.Obtain<LizardTail>(player);
                    await PotionCmd.TryToProcure<MegaCrit.Sts2.Core.Models.Potions.FairyInABottle>(player);
                }
                using var select=CardSelectCmd.PushSelector(new AuditSelector([original[4],original[0]]));
                await RelicCmd.Obtain<PrecariousShears>(player);
                int hpAfter=player.Creature.CurrentHp;
                bool? lizardAfter=player.GetRelic<LizardTail>()?.WasUsed;
                int? hpSecond=null,hpThird=null;
                if(kind=="shears_fairy_lizard") {
                    await CreatureCmd.Damage(choice,player.Creature,player.Creature.CurrentHp,ValueProp.Unblockable|ValueProp.Unpowered,null,null);
                    hpSecond=player.Creature.CurrentHp;
                    await CreatureCmd.Damage(choice,player.Creature,player.Creature.CurrentHp,ValueProp.Unblockable|ValueProp.Unpowered,null,null);
                    hpThird=player.Creature.CurrentHp;
                }
                results.Add(new {test=kind,hpAfter,lizardAfter,hpSecond,hpThird,
                    lizardFinally=player.GetRelic<LizardTail>()?.WasUsed,dead=player.Creature.IsDead,deck=Snapshot(player,original)});
            }
            session.ChoiceFixtureCards=deck; session.InitialHp=15;
            await session.ResetAsync("SIM-AUDIT-LETHAL-MUSHROOM",timeout.Token);
            {
                var player=session.CombatStateForSimulation.Players[0];
                var original=player.Deck.Cards.ToArray();
                player.RunState.Rng.Niche.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(42).ToSerializable());
                await RelicCmd.Obtain<FragrantMushroom>(player);
                results.Add(new {test="mushroom_lethal",hp=player.Creature.CurrentHp,dead=player.Creature.IsDead,
                    rngCounter=player.RunState.Rng.Niche.ToSerializable().counter,deck=Snapshot(player,original)});
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
