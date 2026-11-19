using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Entities.Rngs;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Cards;
using MegaCrit.Sts2.Core.Models.CardPools;
using MegaCrit.Sts2.Core.Models.Orbs;
using MegaCrit.Sts2.Core.Models.Powers;
using MegaCrit.Sts2.Core.TestSupport;

public partial class AuditWorker : Node
{
    readonly List<object> results = [];
    static object Card(CardModel c) => new {id=c.Id.Entry, upgraded=c.IsUpgraded,
        cost=c.EnergyCost.GetWithModifiers(CostModifiers.All), x=c.EnergyCost.CostsX,
        damage=c.DynamicVars.TryGetValue("Damage",out var d)?d.BaseValue:0,
        block=c.DynamicVars.TryGetValue("Block",out var b)?b.BaseValue:0};
    static object Snapshot(Player p) {
        var pc=p.PlayerCombatState!;var combat=p.Creature.CombatState!;
        return new {hp=p.Creature.CurrentHp,block=p.Creature.Block,energy=pc.Energy,
            powers=p.Creature.Powers.Select(x=>new{id=x.Id.Entry,amount=x.Amount}).ToArray(),
            enemies=combat.Enemies.Select(x=>new{id=x.Monster!.Id.Entry,hp=x.CurrentHp,block=x.Block,
                powers=x.Powers.Select(y=>new{id=y.Id.Entry,amount=y.Amount}).ToArray()}).ToArray(),
            hand=pc.Hand.Cards.Select(Card).ToArray(),draw=pc.DrawPile.Cards.Select(Card).ToArray(),
            discard=pc.DiscardPile.Cards.Select(Card).ToArray(),exhaust=pc.ExhaustPile.Cards.Select(Card).ToArray(),
            capacity=pc.OrbQueue.Capacity,orbs=pc.OrbQueue.Orbs.Select(o=>new{id=o.Id.Entry,passive=o.PassiveVal,evoke=o.EvokeVal}).ToArray(),
            targets=p.RunState.Rng.CombatTargets.ToSerializable().counter,
            shuffle=p.RunState.Rng.Shuffle.ToSerializable().counter,
            cardgen=p.RunState.Rng.CombatCardGeneration.ToSerializable().counter,
            orbgen=p.RunState.Rng.CombatOrbGeneration.ToSerializable().counter};
    }
    public override async void _Ready() {
        string output=System.Environment.GetEnvironmentVariable("STS2_AUDIT_OUT")!;
        try {
            TestMode.IsOn=true;NonInteractiveMode.AutoSlayerCheck=()=>true;
            MegaCrit.Sts2.Core.Context.LocalContext.NetId=1;
            if(!ProjectSettings.LoadResourcePack(System.Environment.GetEnvironmentVariable("STS2_GAME_PACK")!,false)) throw new IOException("Game pack load failed");
            await OneTimeInitialization.ExecuteVeryEarly();
            var saves=MegaCrit.Sts2.Core.Saves.SaveManager.Instance;
            saves.InitPrefsDataForTest();saves.InitProfileId();OneTimeInitialization.ExecuteEssential();saves.InitProgressData();
            typeof(NativeSession).Assembly.GetType("NativeReplayCompatibilityPatches")!.GetMethod("Install",BindingFlags.Public|BindingFlags.Static)!.Invoke(null,null);
            CombatSolver.Api.NativeMctsSimulationApi.Initialize();
            SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.CaptureEnabled=false;
            using var timeout=new CancellationTokenSource(TimeSpan.FromSeconds(90));
            var session=new NativeSession(this){ChoiceFixture=true};
            var choice=new ThrowingPlayerChoiceContext();
            var cards=ModelDb.CardPool<DefectCardPool>().AllCards.Where(c=>c.MultiplayerConstraint!=CardMultiplayerConstraint.MultiplayerOnly).ToArray();
            if(cards.Length!=86)throw new Exception("Expected 86 single-player Defect cards");
            foreach(var canonical in cards)foreach(bool upgraded in new[]{false,true}) {
                string id=canonical.Id.Entry;
                session.ChoiceFixtureCards=[id,"STRIKE_IRONCLAD","DEFEND_IRONCLAD","WOUND"];
                session.ChoiceFixtureUpgradedCards=upgraded?new HashSet<string>{id}:[];
                await session.ResetAsync("NATIVE-ROUND4-DEFECT",timeout.Token);
                var combat=session.CombatStateForSimulation;var p=combat.Players[0];var pc=p.PlayerCombatState!;
                foreach(var e in combat.Enemies) {
                    foreach(var power in e.Powers.ToArray())await PowerCmd.Remove(power);
                    e.SetMaxHpInternal(10000);e.SetCurrentHpInternal(10000);
                }
                foreach(var power in p.Creature.Powers.ToArray())await PowerCmd.Remove(power);
                await PlayerCmd.SetEnergy(6,p);
                // Four deterministic draw cards, two discard choices, plus a
                // Status in hand exercise the cards' nonempty paths.
                foreach(var c in pc.Hand.Cards.Where(c=>c.Id.Entry=="STRIKE_IRONCLAD").ToArray())await CardPileCmd.Add(c,PileType.Discard,skipVisuals:true);
                var fuel=combat.CreateCard<Fuel>(p);await CardPileCmd.AddGeneratedCardToCombat(fuel,PileType.Discard,p);
                foreach(var model in new CardModel[]{ModelDb.Card<StrikeIronclad>(),ModelDb.Card<DefendIronclad>(),ModelDb.Card<Fuel>(),ModelDb.Card<Wound>()})
                    await CardPileCmd.AddGeneratedCardToCombat(combat.CreateCard(model,p),PileType.Draw,p);
                await OrbCmd.AddSlots(p,3);
                await OrbCmd.Channel<LightningOrb>(choice,p);await OrbCmd.Channel<FrostOrb>(choice,p);await OrbCmd.Channel<DarkOrb>(choice,p);
                foreach(var kind in new[]{RunRngType.CombatTargets,RunRngType.Shuffle,RunRngType.CombatCardGeneration,RunRngType.CombatOrbs})p.RunState.Rng.MockRng(kind,42);
                var before=Snapshot(p);var selector=new AuditSelector();
                using(CardSelectCmd.PushSelector(selector))await session.StepAsync(session.ActionForCard(id),timeout.Token);
                results.Add(new{test="card",id,upgraded,before,after=Snapshot(p),choices=selector.calls});
            }
            // Direct Orb commands isolate Focus, mutable Dark/Glass values,
            // targeted/random damage, dequeue behavior, and capacity limits.
            foreach(int focus in new[]{-10,-2,0,3}) {
                session.ChoiceFixtureCards=["DEFEND_IRONCLAD"];session.ChoiceFixtureUpgradedCards=[];
                await session.ResetAsync("NATIVE-ROUND4-DEFECT-ORBS",timeout.Token);
                var combat=session.CombatStateForSimulation;var p=combat.Players[0];var pc=p.PlayerCombatState!;
                foreach(var e in combat.Enemies){foreach(var power in e.Powers.ToArray())await PowerCmd.Remove(power);e.SetMaxHpInternal(10000);e.SetCurrentHpInternal(10000);}
                await PowerCmd.Apply<FocusPower>(choice,p.Creature,focus,p.Creature,null);
                await OrbCmd.AddSlots(p,5);await OrbCmd.Channel<LightningOrb>(choice,p);await OrbCmd.Channel<FrostOrb>(choice,p);
                await OrbCmd.Channel<DarkOrb>(choice,p);await OrbCmd.Channel<PlasmaOrb>(choice,p);await OrbCmd.Channel<GlassOrb>(choice,p);
                p.RunState.Rng.MockRng(RunRngType.CombatTargets,42);
                var before=Snapshot(p);var transitions=new List<object>();
                foreach(var orb in pc.OrbQueue.Orbs.ToArray()){await orb.Passive(choice,null);transitions.Add(new{operation="passive",orb=orb.Id.Entry,state=Snapshot(p)});}
                await OrbCmd.EvokeNext(choice,p,false);transitions.Add(new{operation="evoke_first_keep",orb="LIGHTNING_ORB",state=Snapshot(p)});
                while(pc.OrbQueue.Orbs.Count>0){var orb=pc.OrbQueue.Orbs[0];await OrbCmd.EvokeNext(choice,p);transitions.Add(new{operation="evoke_first",orb=orb.Id.Entry,state=Snapshot(p)});}
                results.Add(new{test="orbs",focus,before,transitions});
            }
            File.WriteAllText(output,JsonSerializer.Serialize(new{status="completed",gameAssemblySha256=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(ModelDb).Assembly.Location))).ToLowerInvariant(),gameSceneLoaded=MegaCrit.Sts2.Core.Nodes.NGame.Instance!=null,userDirectory=OS.GetUserDataDir(),scope="Controlled single-player cross-character cards/orbs; not whole Defect runs or multiplayer parity",results},new JsonSerializerOptions{WriteIndented=true}));
            GD.Print("SIM_AUDIT_COMPLETED "+output);GetTree().Quit();
        }catch(Exception e){File.WriteAllText(output,JsonSerializer.Serialize(new{status="error",error=e.ToString(),results},new JsonSerializerOptions{WriteIndented=true}));GD.PrintErr(e);GetTree().Quit(1);}
    }
}
internal sealed class AuditSelector : ICardSelector {
    public List<object> calls=[];
    public Task<IEnumerable<CardModel>> GetSelectedCards(IEnumerable<CardModel> options,int minSelect,int maxSelect) {
        var candidates=options.ToArray();var selected=candidates.Take(minSelect).ToArray();
        calls.Add(new{minSelect,maxSelect,candidates=candidates.Select(c=>c.Id.Entry).ToArray(),selected=selected.Select(c=>c.Id.Entry).ToArray()});
        return Task.FromResult<IEnumerable<CardModel>>(selected);
    }
    public CardRewardSelection GetSelectedCardReward(IReadOnlyList<CardCreationResult> options,IReadOnlyList<MegaCrit.Sts2.Core.Entities.CardRewardAlternatives.CardRewardAlternative> alternatives)=>throw new NotSupportedException();
}
