using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Enchantments;
using MegaCrit.Sts2.Core.TestSupport;

public partial class AuditWorker : Node
{
    readonly List<object> results = [];
    static int Cost(CardModel c, CostModifiers m) => c.EnergyCost.CostsX ? -1 :
        c.Keywords.Contains(CardKeyword.Unplayable) && c.EnergyCost.GetWithModifiers(m) < 0 ? -2 : c.EnergyCost.GetWithModifiers(m);
    static object CardSnapshot(CardModel c) => new {
        card=c.Id.Entry, upgraded=c.IsUpgraded, baseCost=Cost(c,CostModifiers.None), cost=Cost(c,CostModifiers.Local),
        damage=c.DynamicVars.ContainsKey("Damage")?c.DynamicVars.Damage.BaseValue:0,
        retain=c.Keywords.Contains(CardKeyword.Retain), ethereal=c.Keywords.Contains(CardKeyword.Ethereal),
        exhaust=c.Keywords.Contains(CardKeyword.Exhaust), unplayable=c.Keywords.Contains(CardKeyword.Unplayable),
        replay=c.BaseReplayCount, enchantment=c.Enchantment?.Id.Entry, enchantmentAmount=c.Enchantment?.Amount,
        enchantmentStatus=c.Enchantment?.Status.ToString()
    };
    public override async void _Ready()
    {
        string output = System.Environment.GetEnvironmentVariable("STS2_AUDIT_OUT")!;
        try {
            TestMode.IsOn=true; NonInteractiveMode.AutoSlayerCheck=()=>true;
            MegaCrit.Sts2.Core.Context.LocalContext.NetId=1;
            if(!ProjectSettings.LoadResourcePack(System.Environment.GetEnvironmentVariable("STS2_GAME_PACK")!,false)) throw new IOException("Game pack failed to load");
            await OneTimeInitialization.ExecuteVeryEarly();
            var saves=MegaCrit.Sts2.Core.Saves.SaveManager.Instance;
            saves.InitPrefsDataForTest();saves.InitProfileId();OneTimeInitialization.ExecuteEssential();saves.InitProgressData();
            typeof(NativeSession).Assembly.GetType("NativeReplayCompatibilityPatches")!.GetMethod("Install",BindingFlags.Static|BindingFlags.Public)!.Invoke(null,null);
            CombatSolver.Api.NativeMctsSimulationApi.Initialize();
            SlayTheModel.Sts2.ModAdapter.NativeCombatCheckpoint.CaptureEnabled=false;
            using var timeout=new CancellationTokenSource(TimeSpan.FromSeconds(90));
            var session=new NativeSession(this){ChoiceFixture=true};
            foreach(var spec in new (string card,string modifier)[]{
                ("BARRICADE","plain"),("BARRICADE","turn0"),("BARRICADE","turn1"),("BARRICADE","cap1"),
                ("BARRICADE","free0"),("BARRICADE","keywords"),("BARRICADE","steady"),("BARRICADE","replay"),
                ("DARK_EMBRACE","plain"),("DARK_EMBRACE","turn0"),("CORRUPTION","plain"),("ENTRENCH","plain"),
                ("WHIRLWIND","plain"),("APPARITION","plain"),("STRIKE_IRONCLAD","vigorous"),
                ("MAUL","growth"),("THRASH","growth"),("RAMPAGE","growth"),("DAZED","plain")
            }) {
                var card=ModelDb.AllCards.Single(c=>c.Id.Entry==spec.card).ToMutable();
                if(card.IsUpgradable){card.UpgradeInternal();card.FinalizeUpgradeInternal();}
                if(spec.modifier=="turn0")card.EnergyCost.SetThisTurnOrUntilPlayed(0);
                if(spec.modifier=="turn1")card.EnergyCost.SetThisTurnOrUntilPlayed(1);
                if(spec.modifier=="cap1")card.EnergyCost.SetThisCombat(1,true);
                if(spec.modifier=="free0")card.EnergyCost.SetThisCombat(0);
                if(spec.modifier=="keywords"){card.AddKeyword(CardKeyword.Retain);card.AddKeyword(CardKeyword.Ethereal);}
                if(spec.modifier=="steady")CardCmd.Enchant<Steady>(card,1);
                if(spec.modifier=="vigorous")CardCmd.Enchant<Vigorous>(card,3);
                if(spec.modifier=="replay")card.BaseReplayCount=2;
                if(spec.modifier=="growth") {
                    decimal growth=spec.card=="THRASH"?4.5m:5m;
                    string field=spec.card=="THRASH"?"_extraDamage":spec.card=="MAUL"?"_extraDamageFromMaulPlays":"_extraDamageFromPlays";
                    card.GetType().GetField(field,BindingFlags.Instance|BindingFlags.NonPublic)!.SetValue(card,growth);
                    card.DynamicVars.Damage.BaseValue+=growth;
                }
                var before=CardSnapshot(card);var same=card;
                CardCmd.Downgrade(card);var after=CardSnapshot(card);
                card.EnergyCost.EndOfTurnCleanup();var afterTurn=CardSnapshot(card);
                results.Add(new{test="direct",spec.card,spec.modifier,before,after,afterTurn,sameInstance=ReferenceEquals(card,same)});
            }
            string[] deck=["BARRICADE","CORRUPTION","DARK_EMBRACE","ENTRENCH","BASH","IRON_WAVE","POMMEL_STRIKE","ANGER","STRIKE_IRONCLAD","DEFEND_IRONCLAD"];
            foreach(string kind in new[]{"reflections","wongo","wongo_no_upgrade"})foreach(ulong seed in new ulong[]{0,42,987654321}) {
                session.ChoiceFixtureCards=deck;session.InitialHp=40;session.InitialRelicIds=["BURNING_BLOOD"];session.InitialPotions=[];
                await session.ResetAsync("SIM-AUDIT-DOWNGRADE-STEP1",timeout.Token);
                var player=session.CombatStateForSimulation.Players[0];var original=player.Deck.Cards.ToArray();
                if(kind!="wongo_no_upgrade")foreach(var card in original.Take(4)){card.UpgradeInternal();card.FinalizeUpgradeInternal();}
                CardCmd.Enchant<Steady>(original[0],1);original[0].BaseReplayCount=2;
                EventModel ev=kind=="reflections"?ModelDb.Event<MegaCrit.Sts2.Core.Models.Events.Reflections>().ToMutable():
                    ModelDb.Event<MegaCrit.Sts2.Core.Models.Events.WelcomeToWongos>().ToMutable();
                await ev.BeginEvent(player,null,false);
                ev.Rng.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(seed).ToSerializable());
                var before=player.Deck.Cards.Select(CardSnapshot).ToArray();
                await (Task)ev.GetType().GetMethod(kind=="reflections"?"TouchAMirror":"Leave",BindingFlags.Instance|BindingFlags.NonPublic)!.Invoke(ev,null)!;
                results.Add(new{test=kind,seed,before,after=player.Deck.Cards.Select(CardSnapshot).ToArray(),
                    sameInstances=player.Deck.Cards.Select((c,i)=>ReferenceEquals(c,original[i])).All(x=>x),
                    rngCounter=ev.Rng.ToSerializable().counter,finished=ev.IsFinished});
            }
            File.WriteAllText(output,JsonSerializer.Serialize(new{status="completed",
                gameAssemblySha256=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(ModelDb).Assembly.Location))).ToLowerInvariant(),
                gameSceneLoaded=MegaCrit.Sts2.Core.Nodes.NGame.Instance!=null,userDirectory=OS.GetUserDataDir(),
                scope="Controlled downgrade/Reflections/Wongo-leave fixtures; not full event or full-run parity. No rule patches.",results},new JsonSerializerOptions{WriteIndented=true}));
            GD.Print("SIM_AUDIT_COMPLETED "+output);GetTree().Quit();
        }catch(Exception e){File.WriteAllText(output,JsonSerializer.Serialize(new{status="error",error=e.ToString(),results},new JsonSerializerOptions{WriteIndented=true}));GD.PrintErr(e);GetTree().Quit(1);}
    }
}
