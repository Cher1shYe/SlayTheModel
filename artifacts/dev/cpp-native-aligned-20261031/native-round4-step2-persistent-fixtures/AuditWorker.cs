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
            using var timeout = new CancellationTokenSource(TimeSpan.FromSeconds(90));
            var session = new NativeSession(this) { ChoiceFixture = true };
            var choice = new ThrowingPlayerChoiceContext();
            async Task Reset(string[] ids,string seed="NATIVE-PERSISTENT",string[]? relics=null) {
                session.ChoiceFixtureCards=ids;session.ChoiceFixtureUpgradedCards=[];
                session.InitialRelicIds=relics??[];
                await session.ResetAsync(seed,timeout.Token);
                foreach(var e in session.CombatStateForSimulation.Enemies){e.SetMaxHpInternal(10000);e.SetCurrentHpInternal(10000);}
            }
            object Cards(IEnumerable<CardModel> cards,CardModel[] originals)=>cards.Select(c=>new{id=c.Id.Entry,upgraded=c.IsUpgraded,cost=c.EnergyCost.GetWithModifiers(CostModifiers.Local),originalIndex=Array.IndexOf(originals,c)}).ToArray();
            foreach(bool startsUsed in new[]{false,true}) {
                await Reset(["BASH","DEFEND_IRONCLAD","STRIKE_IRONCLAD","WOUND","BYRDONIS_EGG"]);
                var p=session.CombatStateForSimulation.Players[0];var pc=p.PlayerCombatState!;
                var tea=await RelicCmd.Obtain<BoneTea>(p);tea.CombatsLeft=startsUsed?0:1;
                var original=pc.Hand.Cards.ToArray();var before=Cards(pc.Hand.Cards,original);
                await tea.AfterPlayerTurnStart(choice,p);
                var first=Cards(pc.Hand.Cards,original);
                var late=session.CombatStateForSimulation.CreateCard<MegaCrit.Sts2.Core.Models.Cards.Bash>(p);await CardPileCmd.AddGeneratedCardToCombat(late,PileType.Hand,p);
                await tea.AfterPlayerTurnStart(choice,p);
                results.Add(new{test="bone_tea",startsUsed,before,first,second=Cards(pc.Hand.Cards,original),left=tea.CombatsLeft});
            }
            await Reset(["BASH","DEFEND_IRONCLAD","STRIKE_IRONCLAD","WOUND","BYRDONIS_EGG"],relics:["BONE_TEA"]);
            {var p=session.CombatStateForSimulation.Players[0];results.Add(new{test="bone_initial",hand=Cards(p.PlayerCombatState!.Hand.Cards,[]),deck=Cards(p.Deck.Cards,[]),left=p.GetRelic<BoneTea>().CombatsLeft});}
            foreach(int rests in new[]{0,1,2}) {
                await Reset(["BASH"]);var p=session.CombatStateForSimulation.Players[0];var tea=await RelicCmd.Obtain<FakeVenerableTeaSet>(p);
                for(int i=0;i<rests;++i)await tea.AfterRoomEntered(new MegaCrit.Sts2.Core.Rooms.RestSiteRoom());
                var armed=tea.GainEnergyInNextCombat;await PlayerCmd.SetEnergy(3,p);await tea.AfterEnergyReset(p);
                var first=p.PlayerCombatState!.Energy;var consumed=!tea.GainEnergyInNextCombat;
                await PlayerCmd.SetEnergy(3,p);await tea.AfterEnergyReset(p);
                results.Add(new{test="fake_tea",rests,armed,first,second=p.PlayerCombatState.Energy,consumed});
            }
            foreach(string seed in new[]{"0","42"})
            foreach(string hooks in new[]{"none","molten","bing","fresnel_lucky_book"}) {
                await Reset(["BASH","BYRDONIS_EGG","DEFEND_IRONCLAD","BYRDONIS_EGG"],seed);
                var combat=session.CombatStateForSimulation;var p=combat.Players[0];var pc=p.PlayerCombatState!;
                if(hooks=="molten")await RelicCmd.Obtain<MoltenEgg>(p);
                if(hooks=="bing")await RelicCmd.Obtain<BingBong>(p);
                if(hooks=="fresnel_lucky_book"){await RelicCmd.Obtain<FresnelLens>(p);await RelicCmd.Obtain<LuckyFysh>(p);await RelicCmd.Obtain<BookOfFiveRings>(p);p.GetRelic<BookOfFiveRings>().CardsAdded=3;p.Creature.SetCurrentHpInternal(30);}
                var deckOriginal=p.Deck.Cards.ToArray();var combatOriginal=pc.AllCards.ToArray();
                var handEgg=pc.Hand.Cards.First(c=>c.Id.Entry=="BYRDONIS_EGG");await CardPileCmd.Add(handEgg,PileType.Draw,skipVisuals:true);
                var drawEgg=pc.Hand.Cards.First(c=>c.Id.Entry=="BYRDONIS_EGG");await CardPileCmd.Add(drawEgg,PileType.Discard,skipVisuals:true);
                var exhaustEgg=combat.CreateCard<MegaCrit.Sts2.Core.Models.Cards.ByrdonisEgg>(p);await CardPileCmd.AddGeneratedCardToCombat(exhaustEgg,PileType.Exhaust,p);
                var beforeNiche=p.RunState.Rng.Niche.ToSerializable().counter;var beforeTransforms=p.PlayerRng.Transformations.ToSerializable().counter;var beforeGold=p.Gold;
                var byrd=await RelicCmd.Obtain<MegaCrit.Sts2.Core.Models.Relics.Byrdpip>(p);
                results.Add(new{test="byrd_transform",seed=p.RunState.Rng.Seed,hooks,skin=byrd.Skin,deck=Cards(p.Deck.Cards,deckOriginal),
                    draw=Cards(pc.DrawPile.Cards,combatOriginal),discard=Cards(pc.DiscardPile.Cards,combatOriginal),exhaust=Cards(pc.ExhaustPile.Cards,combatOriginal),
                    petCount=pc.Pets.Count,petIds=pc.Pets.Select(c=>c.Monster.Id.Entry).ToArray(),hasEventPet=p.HasEventPet(),
                    hp=p.Creature.CurrentHp,goldDelta=p.Gold-beforeGold,bookCount=p.GetRelic<BookOfFiveRings>()?.CardsAdded??0,
                    nicheDelta=p.RunState.Rng.Niche.ToSerializable().counter-beforeNiche,transformDelta=p.PlayerRng.Transformations.ToSerializable().counter-beforeTransforms,
                    enchants=p.Deck.Cards.Select(c=>c.Enchantment?.Id.Entry).ToArray()});
            }
            foreach(bool pet in new[]{false,true})foreach(bool upgraded in new[]{false,true}) {
                await Reset(["BYRD_SWOOP","DEFEND_IRONCLAD"]);var combat=session.CombatStateForSimulation;var p=combat.Players[0];
                if(pet)await RelicCmd.Obtain<MegaCrit.Sts2.Core.Models.Relics.Byrdpip>(p);
                var c=p.PlayerCombatState!.Hand.Cards.Single(c=>c.Id.Entry=="BYRD_SWOOP");if(upgraded)CardCmd.Upgrade(c);
                await PowerCmd.Apply<StrengthPower>(choice,p.Creature,3,p.Creature,null);
                await session.StepAsync(session.ActionForCard("BYRD_SWOOP"),timeout.Token);
                results.Add(new{test="byrd_attack",pet,upgraded,damage=combat.Enemies.Select(e=>10000-e.CurrentHp).ToArray(),petCount=p.PlayerCombatState.Pets.Count});
            }
            File.WriteAllText(output, JsonSerializer.Serialize(new {status="completed",gameAssemblySha256=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(ModelDb).Assembly.Location))).ToLowerInvariant(),gameSceneLoaded=MegaCrit.Sts2.Core.Nodes.NGame.Instance!=null,userDirectory=OS.GetUserDataDir(),scope="Controlled persistent relic hooks, Byrdpip transforms/pet/ByrdSwoop. Not full runs or general hook order parity.",results},new JsonSerializerOptions{WriteIndented=true}));
            GD.Print("SIM_AUDIT_COMPLETED "+output);GetTree().Quit();
        }
        catch(Exception e) { File.WriteAllText(output,JsonSerializer.Serialize(new{status="error",error=e.ToString(),results},new JsonSerializerOptions{WriteIndented=true}));GD.PrintErr(e);GetTree().Quit(1); }
    }
}
