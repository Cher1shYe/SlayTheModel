using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.CardPools;
using MegaCrit.Sts2.Core.Models.Characters;
using MegaCrit.Sts2.Core.Models.Relics;
using MegaCrit.Sts2.Core.Rewards;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.TestSupport;

public partial class AuditWorker : Node
{
    readonly List<object> results=[];
    public static object CardView(CardModel c)=>new{card=c.Id.Entry,upgraded=c.IsUpgraded,cost=c.EnergyCost.GetWithModifiers(CostModifiers.Local),
        enchantment=c.Enchantment?.Id.Entry,amount=c.Enchantment?.Amount,rarity=c.Rarity.ToString()};
    public override async void _Ready() {
        string output=System.Environment.GetEnvironmentVariable("STS2_AUDIT_OUT")!;
        try {
            TestMode.IsOn=true;NonInteractiveMode.AutoSlayerCheck=()=>true;MegaCrit.Sts2.Core.Context.LocalContext.NetId=1;
            if(!ProjectSettings.LoadResourcePack(System.Environment.GetEnvironmentVariable("STS2_GAME_PACK")!,false))throw new IOException("Game pack failed");
            await OneTimeInitialization.ExecuteVeryEarly();var saves=MegaCrit.Sts2.Core.Saves.SaveManager.Instance;
            saves.InitPrefsDataForTest();saves.InitProfileId();OneTimeInitialization.ExecuteEssential();saves.InitProgressData();
            typeof(NativeSession).Assembly.GetType("NativeReplayCompatibilityPatches")!.GetMethod("Install",BindingFlags.Static|BindingFlags.Public)!.Invoke(null,null);
            CombatSolver.Api.NativeMctsSimulationApi.Initialize();SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.CaptureEnabled=false;
            using var timeout=new CancellationTokenSource(TimeSpan.FromSeconds(90));
            var session=new NativeSession(this){ChoiceFixture=true};
            var specs=new List<(string kind,string hook,ulong seed,int act,int asc,int select)>();
            foreach(string kind in new[]{"lead","arcane","dream","tome","sea_IRONCLAD","sea_SILENT","sea_REGENT","sea_NECROBINDER","sea_DEFECT"})
                foreach(ulong seed in new ulong[]{0,42,987654321})specs.Add((kind,"none",seed,0,0,0));
            foreach(string kind in new[]{"lead","dream"})foreach(int asc in new[]{0,7})foreach(ulong seed in new ulong[]{5,17,36})
                specs.Add((kind,"none",seed,2,asc,1));
            foreach(string kind in new[]{"lead","arcane","dream","sea_IRONCLAD"})
                foreach(string hook in new[]{"eggs","lens","wing","glitter","lens_glitter","glitter_lens","silver","silken","dingy","prismatic"})
                    specs.Add((kind,hook,42,1,0,0));
            specs.Add(("lead","none",42,0,0,-1));specs.Add(("sea_IRONCLAD","none",42,0,0,-1));specs.Add(("sea_SILENT","none",42,0,0,15));
            foreach(var spec in specs) {
                string[] hooks=spec.hook switch {
                    "eggs"=>["MOLTEN_EGG","TOXIC_EGG","FROZEN_EGG"],"lens"=>["FRESNEL_LENS"],"wing"=>["WING_CHARM"],"glitter"=>["GLITTER"],
                    "lens_glitter"=>["FRESNEL_LENS","GLITTER"],"glitter_lens"=>["GLITTER","FRESNEL_LENS"],"silver"=>["SILVER_CRUCIBLE"],
                    "silken"=>["SILKEN_TRESS"],"dingy"=>["DINGY_RUG"],"prismatic"=>["PRISMATIC_GEM"],_=>[]};
                session.AscensionLevel=spec.asc;session.ChoiceFixtureCards=["STRIKE_IRONCLAD","DEFEND_IRONCLAD","BASH"];
                session.ChoiceFixtureUpgradedCards=[];session.InitialRelicIds=["BURNING_BLOOD",..hooks];session.InitialPotions=[];session.InitialHp=40;session.InitialMaxHp=80;
                await session.ResetAsync("NATIVE-STEP2-CARD-REWARDS",timeout.Token);
                var player=session.CombatStateForSimulation.Players[0];var run=(RunState)player.RunState;run.CurrentActIndex=spec.act;
                run.PushRoom(new RestSiteRoom());
                player.PlayerRng.Rewards.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(spec.seed).ToSerializable());
                run.Rng.Niche.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(spec.seed).ToSerializable());
                var original=player.Deck.Cards.ToArray();float pityBefore=player.PlayerOdds.CardRarity.CurrentValue;
                string? prepared=null;uint? preparedCounter=null;
                var selector=new AuditSelector(spec.select);using var select=CardSelectCmd.PushSelector(selector);
                var offered=new List<object>();
                if(spec.kind=="lead")await RelicCmd.Obtain<LeadPaperweight>(player);
                else if(spec.kind=="arcane")await RelicCmd.Obtain<ArcaneScroll>(player);
                else if(spec.kind=="tome") {
                    var tome=(DustyTome)ModelDb.Relic<DustyTome>().ToMutable();tome.SetupForPlayer(player);
                    prepared=tome.AncientCard!.Entry;preparedCounter=(uint)player.PlayerRng.Rewards.ToSerializable().counter;
                    await RelicCmd.Obtain(tome,player);
                } else if(spec.kind.StartsWith("sea_")) {
                    var sea=(SeaGlass)ModelDb.Relic<SeaGlass>().ToMutable();sea.CharacterId=ModelDb.AllCharacters.Single(c=>c.Id.Entry==spec.kind[4..]).Id;
                    await RelicCmd.Obtain(sea,player);
                } else {
                    await RelicCmd.Obtain<DreamCatcher>(player);
                    RewardsSet.testSelector=set=>{
                        foreach(var reward in set.Rewards.OfType<CardReward>())offered.AddRange(reward.Cards.Select(CardView));
                        RunManager.Instance.RewardsSetSynchronizer.SkipLocalRewardsSet();return Task.CompletedTask;
                    };
                    await MegaCrit.Sts2.Core.Entities.RestSite.HealRestSiteOption.ExecuteRestSiteHeal(player,false);
                    RewardsSet.testSelector=null;
                }
                var silken=player.GetRelic<SilkenTress>();
                results.Add(new{test=spec.kind,hook=spec.hook,seed=spec.seed,act=spec.act,ascension=spec.asc,selection=spec.select,
                    offered=spec.kind=="dream"?offered.ToArray():selector.offered,selectorCalls=selector.calls,minSelect=selector.min,maxSelect=selector.max,
                    added=player.Deck.Cards.Where(c=>!original.Contains(c)).Select(CardView).ToArray(),prepared,preparedCounter,
                    rewardsCounter=player.PlayerRng.Rewards.ToSerializable().counter,nicheCounter=run.Rng.Niche.ToSerializable().counter,
                    pityBefore,pityAfter=player.PlayerOdds.CardRarity.CurrentValue,hp=player.Creature.CurrentHp,
                    silverUsed=player.GetRelic<SilverCrucible>()?.TimesUsed??0,
                    silkenUsed=silken==null?false:(bool)typeof(SilkenTress).GetProperty("IsUsed",BindingFlags.Instance|BindingFlags.NonPublic)!.GetValue(silken)!});
            }
            File.WriteAllText(output,JsonSerializer.Serialize(new{status="completed",gameAssemblySha256=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(ModelDb).Assembly.Location))).ToLowerInvariant(),gameSceneLoaded=MegaCrit.Sts2.Core.Nodes.NGame.Instance!=null,results},new JsonSerializerOptions{WriteIndented=true}));
            GetTree().Quit();
        }catch(Exception e){File.WriteAllText(output,JsonSerializer.Serialize(new{status="error",error=e.ToString(),results},new JsonSerializerOptions{WriteIndented=true}));GD.PrintErr(e);GetTree().Quit(1);}
    }
}
internal sealed class AuditSelector(int selection):ICardSelector {
    public int calls,min,max;public object[] offered=[];
    public Task<IEnumerable<CardModel>> GetSelectedCards(IEnumerable<CardModel> options,int minSelect,int maxSelect) {
        ++calls;min=minSelect;max=maxSelect;var cards=options.ToArray();offered=cards.Select(AuditWorker.CardView).ToArray();
        IEnumerable<CardModel> selected=selection<0?[]:selection==15?cards:[cards[Math.Min(selection,cards.Length-1)]];
        return Task.FromResult(selected);
    }
    public CardRewardSelection GetSelectedCardReward(IReadOnlyList<CardCreationResult> options,IReadOnlyList<MegaCrit.Sts2.Core.Entities.CardRewardAlternatives.CardRewardAlternative> alternatives)=>new(){card=null};
}
