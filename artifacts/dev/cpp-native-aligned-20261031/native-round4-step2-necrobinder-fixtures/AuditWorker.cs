using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Hooks;
using MegaCrit.Sts2.Core.Models;
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
            if (!ProjectSettings.LoadResourcePack(System.Environment.GetEnvironmentVariable("STS2_GAME_PACK")!, false)) throw new IOException("Game pack failed to load");
            await OneTimeInitialization.ExecuteVeryEarly();
            var saves = MegaCrit.Sts2.Core.Saves.SaveManager.Instance;
            saves.InitPrefsDataForTest(); saves.InitProfileId();
            OneTimeInitialization.ExecuteEssential(); saves.InitProgressData();
            typeof(NativeSession).Assembly.GetType("NativeReplayCompatibilityPatches")!.GetMethod("Install", BindingFlags.Static | BindingFlags.Public)!.Invoke(null, null);
            CombatSolver.Api.NativeMctsSimulationApi.Initialize();
            SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.CaptureEnabled = false;
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(300));
            var session = new NativeSession(this) { ChoiceFixture=true, CharacterId="NECROBINDER" };
            var choice = new ThrowingPlayerChoiceContext();
            async Task Reset(string id,bool up=false) {
                session.ChoiceFixtureCards=[id];session.ChoiceFixtureUpgradedCards=up?[id]:[];
                session.InitialRelicIds=["BOUND_PHYLACTERY"];
                await session.ResetAsync("NATIVE-NECROBINDER",timeout.Token);
                var combat=session.CombatStateForSimulation;var p=combat.Players[0];
                foreach(var e in combat.Enemies){e.SetMaxHpInternal(1000);e.SetCurrentHpInternal(1000);}
                await PlayerCmd.SetEnergy(id is "DIRGE" or "ERADICATE"?4:20,p);
                await OstyCmd.Summon(choice,p,9,null);
            }
            async Task<CardModel> Add(string id,PileType pile,bool up=false) {
                var combat=session.CombatStateForSimulation;var p=combat.Players[0];
                var c=combat.CreateCard(ModelDb.AllCards.Single(m=>m.Id.Entry==id),p);
                if(up)CardCmd.Upgrade(c);
                await CardPileCmd.AddGeneratedCardToCombat(c,pile,p);return c;
            }
            object Cards(IEnumerable<CardModel> cards)=>cards.Select(c=>new{id=c.Id.Entry,upgraded=c.IsUpgraded,cost=c.EnergyCost.GetWithModifiers(CostModifiers.Local),ethereal=c.Keywords.Contains(CardKeyword.Ethereal),retain=c.Keywords.Contains(CardKeyword.Retain),replay=c.BaseReplayCount}).ToArray();
            object State(){var combat=session.CombatStateForSimulation;var p=combat.Players[0];var pc=p.PlayerCombatState!;
                return new{hp=p.Creature.CurrentHp,block=p.Creature.Block,energy=pc.Energy,ostyHp=p.Osty?.CurrentHp??0,ostyMaxHp=p.Osty?.MaxHp??0,
                    playerPowers=p.Creature.Powers.ToDictionary(x=>x.Id.Entry,x=>x.Amount),
                    enemies=combat.Enemies.Select(e=>new{hp=e.CurrentHp,block=e.Block,powers=e.Powers.ToDictionary(x=>x.Id.Entry,x=>x.Amount)}).ToArray(),
                    hand=Cards(pc.Hand.Cards),draw=Cards(pc.DrawPile.Cards),discard=Cards(pc.DiscardPile.Cards),exhaust=Cards(pc.ExhaustPile.Cards),
                    rng=new{shuffle=p.RunState.Rng.Shuffle.ToSerializable().counter,generate=p.RunState.Rng.CombatCardGeneration.ToSerializable().counter,selection=p.RunState.Rng.CombatCardSelection.ToSerializable().counter,targets=p.RunState.Rng.CombatTargets.ToSerializable().counter}};
            }
            var ids=ModelDb.AllCards.Where(c=>c.Pool is MegaCrit.Sts2.Core.Models.CardPools.NecrobinderCardPool).Select(c=>c.Id.Entry).Concat(new[]{"SOUL","SWEEPING_GAZE"}).Distinct().Order().ToArray();
            foreach(string id in ids)foreach(bool up in new[]{false,true}){
                await Reset(id,up);var combat=session.CombatStateForSimulation;var p=combat.Players[0];
                await Add("STRIKE_NECROBINDER",PileType.Hand);await Add("DEFEND_NECROBINDER",PileType.Hand);await Add("BANSHEES_CRY",PileType.Hand);
                for(int i=0;i<6;++i)await Add(i%2==0?"STRIKE_NECROBINDER":"DEFEND_NECROBINDER",PileType.Draw);
                await Add("STRIKE_NECROBINDER",PileType.Discard);await Add("DEFEND_NECROBINDER",PileType.Discard);await Add("STRIKE_NECROBINDER",PileType.Discard);
                await Add("SOUL",PileType.Exhaust);await Add("DEFILE",PileType.Exhaust);await Add("WOUND",PileType.Exhaust);
                await PowerCmd.Apply<StrengthPower>(choice,p.Creature,3,p.Creature,null);
                await PowerCmd.Apply<DexterityPower>(choice,p.Creature,2,p.Creature,null);
                await PowerCmd.Apply<DoomPower>(choice,combat.Enemies[0],10,p.Creature,null);
                var before=State();var selections=new List<object>();
                var legal=session.Actions().Where(a=>a.Combat?.Kind==SlayTheModel.Sts2.Protocol.CombatActionKind.PlayCard).ToArray();
                try {
                    var action=session.ActionForCard(id);await session.StepAsync(action,timeout.Token);
                    while(session.HasPendingChoice){
                        var options=session.PendingChoiceOptions.Select(c=>c.Id.Entry).ToArray();
                        var a=session.Actions().First();selections.Add(new{options,min=session.PendingChoiceMin,max=session.PendingChoiceMax,selected=a.Selection});
                        await session.StepAsync(a,timeout.Token);
                    }
                    results.Add(new{test="card",id,upgraded=up,before,after=State(),selections});
                } catch(InvalidOperationException e) when(e.Message.Contains("Sequence contains no")){
                    results.Add(new{test="no_single_player_target",id,upgraded=up,before,error=e.Message});
                }
            }
            foreach(string scenario in new[]{"redirect","redirect_block","redirect_overkill","redirect_tungsten","redirect_buffer","osty_thorns","sacrifice_mastery","doom_end","soul_powers","ethereal_history","osty_multihit","debilitate"}){
                await Reset("BODYGUARD");var combat=session.CombatStateForSimulation;var p=combat.Players[0];var pc=p.PlayerCombatState!;
                if(scenario=="redirect_block")await CreatureCmd.GainBlock(p.Creature,4,ValueProp.Unpowered,null);
                if(scenario=="redirect_tungsten")await RelicCmd.Obtain<TungstenRod>(p);
                if(scenario=="redirect_buffer")await PowerCmd.Apply<BufferPower>(choice,p.Creature,1,p.Creature,null);
                var before=State();
                if(scenario.StartsWith("redirect"))await CreatureCmd.Damage(choice,p.Creature,scenario=="redirect_overkill"?14:7,ValueProp.Move,combat.Enemies[0]);
                if(scenario=="osty_thorns"){
                    await PowerCmd.Apply<ThornsPower>(choice,combat.Enemies[0],3,null,null);await Add("POKE",PileType.Hand);await session.StepAsync(session.ActionForCard("POKE"),timeout.Token);
                }
                if(scenario=="sacrifice_mastery"){
                    await PowerCmd.Apply<NecroMasteryPower>(choice,p.Creature,2,p.Creature,null);await Add("SACRIFICE",PileType.Hand);await session.StepAsync(session.ActionForCard("SACRIFICE"),timeout.Token);
                }
                if(scenario=="doom_end"){
                    combat.Enemies[0].SetCurrentHpInternal(8);await PowerCmd.Apply<DoomPower>(choice,combat.Enemies[0],10,p.Creature,null);
                    await DoomPower.DoomKill(DoomPower.GetDoomedCreatures(combat.Enemies));
                }
                if(scenario=="soul_powers"){
                    await PowerCmd.Apply<DevourLifePower>(choice,p.Creature,2,p.Creature,null);await PowerCmd.Apply<HauntPower>(choice,p.Creature,7,p.Creature,null);
                    await Add("SOUL",PileType.Hand);await session.StepAsync(session.ActionForCard("SOUL"),timeout.Token);
                }
                if(scenario=="ethereal_history"){
                    await Add("BANSHEES_CRY",PileType.Hand);await Add("DEFILE",PileType.Hand);await session.StepAsync(session.ActionForCard("DEFILE"),timeout.Token);
                    await Add("BANSHEES_CRY",PileType.Discard);await Add("PULL_FROM_BELOW",PileType.Hand);await session.StepAsync(session.ActionForCard("PULL_FROM_BELOW"),timeout.Token);
                }
                if(scenario=="osty_multihit"){
                    await Add("SIC_EM",PileType.Hand);await session.StepAsync(session.ActionForCard("SIC_EM"),timeout.Token);
                    await Add("RATTLE",PileType.Hand);await session.StepAsync(session.ActionForCard("RATTLE"),timeout.Token);
                }
                if(scenario=="debilitate"){
                    await Add("DEBILITATE",PileType.Hand);await session.StepAsync(session.ActionForCard("DEBILITATE"),timeout.Token);
                    await PowerCmd.Apply<VulnerablePower>(choice,combat.Enemies[0],1,p.Creature,null);
                    await Add("STRIKE_NECROBINDER",PileType.Hand);await session.StepAsync(session.ActionForCard("STRIKE_NECROBINDER"),timeout.Token);
                }
                results.Add(new{test="mechanism",scenario,before,after=State()});
            }
            File.WriteAllText(output, JsonSerializer.Serialize(new {status="completed",numericSeed=session.CombatStateForSimulation.Players[0].RunState.Rng.Seed,gameAssemblySha256=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(ModelDb).Assembly.Location))).ToLowerInvariant(),gameSceneLoaded=MegaCrit.Sts2.Core.Nodes.NGame.Instance!=null,userDirectory=OS.GetUserDataDir(),scope="Necrobinder base and upgraded cards plus Osty/Doom/Soul interactions. Controlled single-player states; not full-run parity.",results},new JsonSerializerOptions{WriteIndented=true}));
            GD.Print("SIM_AUDIT_COMPLETED "+output);GetTree().Quit();
        }
        catch(Exception e) { File.WriteAllText(output,JsonSerializer.Serialize(new{status="error",error=e.ToString(),results},new JsonSerializerOptions{WriteIndented=true}));GD.PrintErr(e);GetTree().Quit(1); }
    }
}
