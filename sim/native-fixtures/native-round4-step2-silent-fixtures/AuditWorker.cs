using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Combat.History.Entries;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.CardPools;
using MegaCrit.Sts2.Core.Models.Powers;
using MegaCrit.Sts2.Core.TestSupport;

public partial class AuditWorker:Node {
    readonly List<object> results=[];
    static object CardView(CardModel c)=>new{id=c.Id.Entry,upgraded=c.IsUpgraded,cost=c.EnergyCost.GetWithModifiers(CostModifiers.Local),x=c.EnergyCost.CostsX,
        retain=c.ShouldRetainThisTurn,sly=c.IsSlyThisTurn,enchantment=c.Enchantment?.Id.Entry,amount=c.Enchantment?.Amount,replay=c.BaseReplayCount};
    static object View(ICombatState combat){
        var p=combat.Players[0];var pc=p.PlayerCombatState!;
        return new{hp=p.Creature.CurrentHp,maxHp=p.Creature.MaxHp,block=p.Creature.Block,energy=pc.Energy,
            powers=p.Creature.Powers.Select(v=>new{id=v.Id.Entry,amount=v.Amount}).ToArray(),
            enemies=combat.Enemies.Select(e=>new{id=e.Monster!.Id.Entry,hp=e.CurrentHp,maxHp=e.MaxHp,block=e.Block,alive=e.IsAlive,powers=e.Powers.Select(v=>new{id=v.Id.Entry,amount=v.Amount}).ToArray()}).ToArray(),
            hand=pc.Hand.Cards.Select(CardView).ToArray(),draw=pc.DrawPile.Cards.Select(CardView).ToArray(),discard=pc.DiscardPile.Cards.Select(CardView).ToArray(),exhaust=pc.ExhaustPile.Cards.Select(CardView).ToArray(),
            drawnCombat=CombatManager.Instance.History.Entries.OfType<CardDrawnEntry>().Count(e=>e.Actor==p.Creature),
            discardedTurn=CombatManager.Instance.History.Entries.OfType<CardDiscardedEntry>().Count(e=>e.Actor==p.Creature&&e.HappenedThisTurn(combat)),
            attacksFinishedTurn=CombatManager.Instance.History.CardPlaysFinished.Count(e=>e.CardPlay.Player==p&&e.HappenedThisTurn(combat)&&e.CardPlay.Card.Type==CardType.Attack),
            skillsFinishedTurn=CombatManager.Instance.History.CardPlaysFinished.Count(e=>e.CardPlay.Player==p&&e.HappenedThisTurn(combat)&&e.CardPlay.Card.Type==CardType.Skill),
            shivsFinishedTurn=CombatManager.Instance.History.CardPlaysFinished.Count(e=>e.CardPlay.Player==p&&e.HappenedThisTurn(combat)&&e.CardPlay.Card.Id.Entry=="SHIV"),
            targetCounter=combat.RunState.Rng.CombatTargets.ToSerializable().counter,
            shuffleCounter=combat.RunState.Rng.Shuffle.ToSerializable().counter};
    }
    static async Task<CardModel> Add(ICombatState combat,string id,PileType pile,bool upgraded=false){
        var p=combat.Players[0];var card=combat.CreateCard(ModelDb.AllCards.Single(c=>c.Id.Entry==id),p);
        if(upgraded)CardCmd.Upgrade(card);
        await CardPileCmd.AddGeneratedCardToCombat(card,pile,p);return card;
    }
    public override async void _Ready(){
        string output=System.Environment.GetEnvironmentVariable("STS2_AUDIT_OUT")!;
        try{
            TestMode.IsOn=true;NonInteractiveMode.AutoSlayerCheck=()=>true;MegaCrit.Sts2.Core.Context.LocalContext.NetId=1;
            if(!ProjectSettings.LoadResourcePack(System.Environment.GetEnvironmentVariable("STS2_GAME_PACK")!,false))throw new IOException("Game pack failed");
            await OneTimeInitialization.ExecuteVeryEarly();var saves=MegaCrit.Sts2.Core.Saves.SaveManager.Instance;
            saves.InitPrefsDataForTest();saves.InitProfileId();OneTimeInitialization.ExecuteEssential();saves.InitProgressData();
            typeof(NativeSession).Assembly.GetType("NativeReplayCompatibilityPatches")!.GetMethod("Install",BindingFlags.Static|BindingFlags.Public)!.Invoke(null,null);
            CombatSolver.Api.NativeMctsSimulationApi.Initialize();SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.CaptureEnabled=false;
            using var timeout=new CancellationTokenSource(TimeSpan.FromSeconds(100));
            var session=new NativeSession(this){ChoiceFixture=true,ChoiceFixtureCards=["STRIKE_IRONCLAD","DEFEND_IRONCLAD"],InitialRelicIds=[],InitialPotions=[]};
            var specs=new List<(string id,bool up,string mode)>();
            foreach(var card in ModelDb.CardPool<SilentCardPool>().AllCards)foreach(bool up in new[]{false,true})specs.Add((card.Id.Entry,up,"base"));
            foreach(string id in new[]{"SHIV","AFTERIMAGE","SERPENT_FORM","STRANGLE","ACROBATICS","PREPARED","HIDDEN_DAGGERS","STORM_OF_STEEL","SHADOW_STEP","CALCULATED_GAMBLE"})foreach(bool up in new[]{false,true})specs.Add((id,up,"replay"));
            foreach(string id in new[]{"SHIV","ENVENOM","POISONED_STAB","BOUNCING_FLASK","HAZE","OUTBREAK","MALAISE","PIERCING_WAIL"})specs.Add((id,false,"artifact"));
            foreach(string id in new[]{"SHIV","AFTERIMAGE","SERPENT_FORM","STRANGLE","ENVENOM","MASTER_PLANNER","FAN_OF_KNIVES","PHANTOM_BLADES","TRACKING","CORROSIVE_WAVE","SPEEDSTER","BURST","NOXIOUS_FUMES","INFINITE_BLADES","NIGHTMARE","TOOLS_OF_THE_TRADE","WRAITH_FORM","BLUR","WELL_LAID_PLANS","SHADOW_STEP","ANTICIPATE","DODGE_AND_ROLL","PREDATOR","SIDESTEP"})specs.Add((id,false,"followup"));
            foreach(string id in new[]{"SURVIVOR","PREPARED","CALCULATED_GAMBLE","HIDDEN_DAGGERS","STORM_OF_STEEL","SHADOW_STEP"})specs.Add((id,false,"sly"));
            foreach(var spec in specs){
                await session.ResetAsync("NATIVE-STEP2-SILENT",timeout.Token);
                var combat=session.CombatStateForSimulation;var p=combat.Players[0];var pc=p.PlayerCombatState!;var choice=new ThrowingPlayerChoiceContext();
                foreach(var card in pc.AllCards.ToArray())await CardPileCmd.RemoveFromCombat(card,skipVisuals:true);
                foreach(var e in combat.Enemies){e.SetMaxHpInternal(10000);e.SetCurrentHpInternal(10000);}
                var main=await Add(combat,spec.id,PileType.Hand,spec.up);
                await Add(combat,spec.mode=="sly"?"REFLEX":"DEFEND_SILENT",PileType.Hand);
                await Add(combat,spec.mode=="sly"?"TACTICIAN":"STRIKE_SILENT",PileType.Hand);
                foreach(string id in new[]{"DEFEND_IRONCLAD","STRIKE_IRONCLAD","BASH","DEFLECT","SLICE","NEUTRALIZE"})await Add(combat,id,PileType.Draw);
                if(spec.id=="GRAND_FINALE")foreach(var card in pc.DrawPile.Cards.ToArray())await CardPileCmd.Add(card,PileType.Discard,skipVisuals:true);
                if(spec.id=="KNIFE_TRAP"){await Add(combat,"SHIV",PileType.Exhaust);await Add(combat,"SHIV",PileType.Exhaust,true);}
                if(spec.id=="BUBBLE_BUBBLE"||spec.id=="MIRAGE")foreach(var e in combat.Enemies)await PowerCmd.Apply<PoisonPower>(choice,e,3,p.Creature,null);
                if(spec.mode=="replay")main.BaseReplayCount=1;
                if(spec.mode=="artifact")foreach(var e in combat.Enemies)await PowerCmd.Apply<ArtifactPower>(choice,e,2,p.Creature,null);
                if(spec.id=="SHIV"){
                    await PowerCmd.Apply<AccuracyPower>(choice,p.Creature,4,p.Creature,null);
                    await PowerCmd.Apply<PhantomBladesPower>(choice,p.Creature,9,p.Creature,null);
                }
                if(spec.id=="OUTBREAK")await PowerCmd.Apply<AccelerantPower>(choice,p.Creature,2,p.Creature,null);
                if(spec.id=="TRACKING")foreach(var e in combat.Enemies)await PowerCmd.Apply<WeakPower>(choice,e,2,p.Creature,null);
                await PlayerCmd.SetEnergy(3,p);
                combat.RunState.Rng.CombatTargets.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(42).ToSerializable());
                combat.RunState.Rng.Shuffle.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(42).ToSerializable());
                var before=View(combat);var selector=new AuditSelector();using var selection=CardSelectCmd.PushSelector(selector);
                bool forcedAlly=main.TargetType==TargetType.AnyAlly;
                await CardCmd.AutoPlay(choice,main,forcedAlly?p.Creature:combat.Enemies.First());
                var immediate=View(combat);
                if(spec.mode=="followup"){
                    if(new[]{"CORROSIVE_WAVE","SPEEDSTER"}.Contains(spec.id))await CardPileCmd.Draw(choice,2,p);
                    else if(new[]{"NOXIOUS_FUMES","INFINITE_BLADES","NIGHTMARE","TOOLS_OF_THE_TRADE","WRAITH_FORM","BLUR","WELL_LAID_PLANS","SHADOW_STEP","ANTICIPATE","DODGE_AND_ROLL","PREDATOR","SIDESTEP"}.Contains(spec.id)){
                        await session.StepAsync(session.Actions().First(a=>a.Combat?.Kind.ToString()=="EndTurn"),timeout.Token);
                    }else{
                        var next=await Add(combat,spec.id=="BURST"?"DEFEND_SILENT":spec.id=="SHIV"||spec.id=="FAN_OF_KNIVES"||spec.id=="PHANTOM_BLADES"?"SHIV":"STRIKE_SILENT",PileType.Hand);
                        await CardCmd.AutoPlay(choice,next,combat.Enemies.First());
                    }
                }
                results.Add(new{id=spec.id,upgraded=spec.up,mode=spec.mode,forcedAlly,before,immediate,after=View(combat),selections=selector.calls});
            }
            File.WriteAllText(output,JsonSerializer.Serialize(new{status="completed",gameAssemblySha256=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(ModelDb).Assembly.Location))).ToLowerInvariant(),gameSceneLoaded=MegaCrit.Sts2.Core.Nodes.NGame.Instance!=null,results},new JsonSerializerOptions{WriteIndented=true}));GetTree().Quit();
        }catch(Exception e){File.WriteAllText(output,JsonSerializer.Serialize(new{status="error",error=e.ToString(),results},new JsonSerializerOptions{WriteIndented=true}));GD.PrintErr(e);GetTree().Quit(1);}
    }
}
internal sealed class AuditSelector:ICardSelector{
    public List<object> calls=[];
    public Task<IEnumerable<CardModel>> GetSelectedCards(IEnumerable<CardModel> options,int minSelect,int maxSelect){
        var cards=options.ToArray();var chosen=cards.Take(Math.Min(minSelect,cards.Length)).ToArray();
        calls.Add(new{minSelect,maxSelect,options=cards.Select(c=>c.Id.Entry).ToArray(),chosen=chosen.Select(c=>c.Id.Entry).ToArray()});
        return Task.FromResult<IEnumerable<CardModel>>(chosen);
    }
    public CardRewardSelection GetSelectedCardReward(IReadOnlyList<CardCreationResult> options,IReadOnlyList<MegaCrit.Sts2.Core.Entities.CardRewardAlternatives.CardRewardAlternative> alternatives)=>new(){card=null};
}
