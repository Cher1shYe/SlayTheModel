using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Entities.Relics;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Relics;
using MegaCrit.Sts2.Core.Rewards;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves.Runs;
using MegaCrit.Sts2.Core.TestSupport;

public partial class AuditWorker : Node
{
    readonly List<object> results = [];
    static object Relics(Player p) => p.Relics.Select(r => new {
        id=r.Id.Entry,wax=r.IsWax,melted=r.IsMelted,
        counter=r is PenNib pn ? pn.AttacksPlayed : r is HappyFlower hf ? hf.TurnsSeen : r is LizardTail lt ? (lt.WasUsed ? 1 : 0) : 0
    }).ToArray();
    static object Bag(Player p) => p.RelicGrabBag.ToSerializable().RelicIdLists
        .ToDictionary(x=>x.Key.ToString(),x=>x.Value.Select(id=>id.Entry).ToArray());
    static object Deck(Player p) => p.Deck.Cards.Select(c=>new {id=c.Id.Entry,upgraded=c.IsUpgraded}).ToArray();
    public override async void _Ready()
    {
        string output=System.Environment.GetEnvironmentVariable("STS2_AUDIT_OUT")!;
        try {
            TestMode.IsOn=true;NonInteractiveMode.AutoSlayerCheck=()=>true;
            MegaCrit.Sts2.Core.Context.LocalContext.NetId=1;
            if(!ProjectSettings.LoadResourcePack(System.Environment.GetEnvironmentVariable("STS2_GAME_PACK")!,false))throw new IOException("Game pack failed to load");
            await OneTimeInitialization.ExecuteVeryEarly();
            var saves=MegaCrit.Sts2.Core.Saves.SaveManager.Instance;
            saves.InitPrefsDataForTest();saves.InitProfileId();OneTimeInitialization.ExecuteEssential();saves.InitProgressData();
            typeof(NativeSession).Assembly.GetType("NativeReplayCompatibilityPatches")!.GetMethod("Install",BindingFlags.Static|BindingFlags.Public)!.Invoke(null,null);
            CombatSolver.Api.NativeMctsSimulationApi.Initialize();
            SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.CaptureEnabled=false;
            using var timeout=new CancellationTokenSource(TimeSpan.FromSeconds(90));
            var session=new NativeSession(this){ChoiceFixture=true};
            async Task<Player> Reset(ulong seed,bool empty=false) {
                RewardsSet.testSelector=null;TestRngInjector.Cleanup();
                session.ChoiceFixtureCards=["STRIKE_IRONCLAD","DEFEND_IRONCLAD","BASH"];
                session.ChoiceFixtureUpgradedCards=[];session.InitialHp=80;session.InitialRelicIds=["BURNING_BLOOD"];
                session.InitialPotions=[];
                await session.ResetAsync("NATIVE-ROUND4-STEP2-RELIC-LIFECYCLE",timeout.Token);
                var p=session.CombatStateForSimulation.Players[0];
                var relics=new RelicModel[] {
                    ModelDb.Relic<Vajra>(),ModelDb.Relic<HappyFlower>(),ModelDb.Relic<Strawberry>(),ModelDb.Relic<Anchor>(),ModelDb.Relic<BagOfPreparation>(),
                    ModelDb.Relic<PenNib>(),ModelDb.Relic<GremlinHorn>(),ModelDb.Relic<HornCleat>(),ModelDb.Relic<MeatOnTheBone>(),ModelDb.Relic<EternalFeather>(),
                    ModelDb.Relic<LizardTail>(),ModelDb.Relic<OldCoin>(),ModelDb.Relic<Mango>(),ModelDb.Relic<TungstenRod>()
                };
                var bag=new SerializableRelicGrabBag();
                foreach(var rarity in new[]{RelicRarity.Common,RelicRarity.Uncommon,RelicRarity.Rare,RelicRarity.Shop})
                    bag.RelicIdLists[rarity]=empty ? [] : relics.Where(r=>r.Rarity==rarity).Select(r=>r.Id).ToList();
                p.RelicGrabBag.LoadFromSerializable(bag);p.RunState.SharedRelicGrabBag.LoadFromSerializable(bag);
                p.PlayerRng.Rewards.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(seed).ToSerializable());
                p.RunState.Rng.Niche.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(123).ToSerializable());
                return p;
            }
            foreach(ulong seed in new ulong[]{0,42,987654321}) foreach(string mode in new[]{"all","skip","reverse_partial"}) {
                var p=await Reset(seed);var bagBefore=Bag(p);object? offered=null,inventoryAtOffer=null;
                var selected=new List<int>();
                RewardsSet.testSelector=async set=>{
                    offered=set.Rewards.OfType<RelicReward>().Select(r=>new{id=r.Relic!.Id.Entry,wax=r.Relic.IsWax}).ToArray();
                    inventoryAtOffer=Relics(p);
                    int[] indices=mode=="all"?Enumerable.Range(0,set.Rewards.Count).ToArray():mode=="skip"?[]:[4,2,0];
                    foreach(int i in indices){selected.Add(i);await RunManager.Instance.RewardsSetSynchronizer.SelectLocalReward(set.Rewards[i]);}
                    if(!RunManager.Instance.RewardsSetSynchronizer.IsRewardsSetCompleted(set))RunManager.Instance.RewardsSetSynchronizer.SkipLocalRewardsSet();
                };
                var toy=await RelicCmd.Obtain<ToyBox>(p);var afterObtain=Relics(p);
                if(p.GetRelic<PenNib>() is {} nib)for(int i=0;i<7;++i)nib.NotifyAttackPlayed();
                if(p.GetRelic<HappyFlower>() is {} flower)flower.TurnsSeen=2;
                if(p.GetRelic<LizardTail>() is {} tail)tail.WasUsed=true;
                var beforeCombats=Relics(p);var turns=new List<object>();
                var room=new CombatRoom(session.CombatStateForSimulation);
                for(int combat=1;combat<=18;++combat) {
                    await toy.AfterCombatEnd(room);
                    turns.Add(new{combat,combatsSeen=toy.CombatsSeen,isUsedUp=toy.IsUsedUp,relics=Relics(p),
                        activeHookRelics=p.RunState.IterateHookListeners(null).OfType<RelicModel>().Select(r=>r.Id.Entry).ToArray()});
                }
                results.Add(new{test="toy_box",seed,mode,bagBefore,offered,selected,inventoryAtOffer,afterObtain,beforeCombats,turns,
                    bagAfter=Bag(p),rewardCounter=p.PlayerRng.Rewards.ToSerializable().counter,nicheCounter=p.RunState.Rng.Niche.ToSerializable().counter});
            }
            foreach(ulong seed in new ulong[]{0,42,987654321})foreach(bool claim in new[]{false,true}) {
                var p=await Reset(seed);var bagBefore=Bag(p);object? offered=null,inventoryAtOffer=null;
                RewardsSet.testSelector=async set=>{
                    offered=set.Rewards.OfType<RelicReward>().Select(r=>new{id=r.Relic!.Id.Entry,wax=r.Relic.IsWax}).ToArray();inventoryAtOffer=Relics(p);
                    if(claim)await RunManager.Instance.RewardsSetSynchronizer.SelectLocalReward(set.Rewards[0]);
                    else RunManager.Instance.RewardsSetSynchronizer.SkipLocalRewardsSet();
                };
                await RelicCmd.Obtain<SmallCapsule>(p);
                results.Add(new{test="small_capsule",seed,claim,bagBefore,offered,inventoryAtOffer,after=Relics(p),bagAfter=Bag(p),
                    rewardCounter=p.PlayerRng.Rewards.ToSerializable().counter,nicheCounter=p.RunState.Rng.Niche.ToSerializable().counter});
            }
            foreach(ulong seed in new ulong[]{0,42,987654321})foreach(bool hooks in new[]{false,true}) {
                var p=await Reset(seed);if(hooks){await RelicCmd.Obtain<MoltenEgg>(p);await RelicCmd.Obtain<BingBong>(p);}
                var bagBefore=Bag(p);var before=Relics(p);var deckBefore=Deck(p);var events=new List<object>();
                p.RelicObtained+=r=>events.Add(new{id=r.Id.Entry,rewardCounter=p.PlayerRng.Rewards.ToSerializable().counter,deckCount=p.Deck.Cards.Count});
                await RelicCmd.Obtain<LargeCapsule>(p);
                results.Add(new{test="large_capsule",seed,hooks,bagBefore,before,deckBefore,after=Relics(p),deckAfter=Deck(p),events,bagAfter=Bag(p),
                    rewardCounter=p.PlayerRng.Rewards.ToSerializable().counter,nicheCounter=p.RunState.Rng.Niche.ToSerializable().counter});
            }
            foreach(string kind in new[]{"toy","large"}) {
                var p=await Reset(42,true);object? offered=null;
                RewardsSet.testSelector=async set=>{offered=set.Rewards.OfType<RelicReward>().Select(r=>new{id=r.Relic!.Id.Entry,wax=r.Relic.IsWax}).ToArray();
                    foreach(var r in set.Rewards)await RunManager.Instance.RewardsSetSynchronizer.SelectLocalReward(r);};
                if(kind=="toy")await RelicCmd.Obtain<ToyBox>(p);else await RelicCmd.Obtain<LargeCapsule>(p);
                results.Add(new{test="empty_bag",kind,offered,after=Relics(p),rewardCounter=p.PlayerRng.Rewards.ToSerializable().counter});
            }
            {
                var p=await Reset(42);var gate=new TaskCompletionSource();object? paused=null;object? offered=null;
                RewardsSet.testSelector=async set=>{
                    offered=set.Rewards.OfType<RelicReward>().Select(r=>r.Relic!.Id.Entry).ToArray();
                    paused=new{relics=Relics(p),deckCount=p.Deck.Cards.Count,rewardCounter=p.PlayerRng.Rewards.ToSerializable().counter};
                    await gate.Task;RunManager.Instance.RewardsSetSynchronizer.SkipLocalRewardsSet();
                };
                // Test-only first-relic override isolates await ordering; normal
                // random bags do not contain Ancient SmallCapsule.
                TestRngInjector.SetRelicOverride<SmallCapsule>();
                var obtain=RelicCmd.Obtain<LargeCapsule>(p);bool wasPaused=!obtain.IsCompleted;
                gate.SetResult();await obtain;
                results.Add(new{test="large_waits_for_child_reward",wasPaused,paused,offered,after=Relics(p),deckAfter=Deck(p),
                    rewardCounter=p.PlayerRng.Rewards.ToSerializable().counter,nicheCounter=p.RunState.Rng.Niche.ToSerializable().counter});
            }
            RewardsSet.testSelector=null;TestRngInjector.Cleanup();
            File.WriteAllText(output,JsonSerializer.Serialize(new{status="completed",
                gameAssemblySha256=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(ModelDb).Assembly.Location))).ToLowerInvariant(),
                gameSceneLoaded=MegaCrit.Sts2.Core.Nodes.NGame.Instance!=null,userDirectory=OS.GetUserDataDir(),
                scope="Controlled ordered-bag relic rewards, choice/skip, wax lifetime and acquisition sequencing; no relic-rule patches or full-run parity claim.",results},new JsonSerializerOptions{WriteIndented=true}));
            GD.Print("SIM_AUDIT_COMPLETED "+output);GetTree().Quit();
        }catch(Exception e){File.WriteAllText(output,JsonSerializer.Serialize(new{status="error",error=e.ToString(),results},new JsonSerializerOptions{WriteIndented=true}));GD.PrintErr(e);GetTree().Quit(1);}
    }
}
