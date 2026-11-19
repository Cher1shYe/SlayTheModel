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
            foreach(bool upgraded in new[]{false,true}) {
                foreach(string id in new[]{"CONFLAGRATION","SPITE","DOMINATE","FORGOTTEN_RITUAL","PACTS_END","VOLLEY","RIP_AND_TEAR","SWORD_BOOMERANG","FUEL","SOUL","NOT_YET"}) {
                    foreach(bool powered in new[]{false,true}) {
                        session.ChoiceFixtureCards=[id,"DEFEND_IRONCLAD","STRIKE_IRONCLAD","BASH"];
                        session.ChoiceFixtureUpgradedCards=upgraded?new HashSet<string>{id}:[];
                        await session.ResetAsync("NATIVE-ROUND3-CARD",timeout.Token);
                        var combat=session.CombatStateForSimulation;var player=combat.Players[0];var pc=player.PlayerCombatState!;var enemy=combat.Enemies.First();
                        foreach(var e in combat.Enemies) { e.SetMaxHpInternal(10000);e.SetCurrentHpInternal(10000); }
                        await CardPileCmd.Add(pc.Hand.Cards.Single(c=>c.Id.Entry=="STRIKE_IRONCLAD"),PileType.Draw,skipVisuals:true);
                        await CardPileCmd.Add(pc.Hand.Cards.Single(c=>c.Id.Entry=="BASH"),PileType.Draw,skipVisuals:true);
                        await PlayerCmd.SetEnergy(3,player);
                        if(id=="NOT_YET") player.Creature.SetCurrentHpInternal(40);
                        if(powered && id=="SPITE") await CreatureCmd.Damage(choice,player.Creature,1,ValueProp.Unblockable|ValueProp.Unpowered,null);
                        if(powered && new[]{"CONFLAGRATION","VOLLEY","RIP_AND_TEAR","SWORD_BOOMERANG"}.Contains(id)) {
                            await PowerCmd.Apply<StrengthPower>(choice,player.Creature,3,player.Creature,null);
                            await PowerCmd.Apply<VigorPower>(choice,player.Creature,4,player.Creature,null);
                        }
                        if(powered && id=="DOMINATE") await PowerCmd.Apply<VulnerablePower>(choice,enemy,2,player.Creature,null);
                        await session.StepAsync(session.ActionForCard(id),timeout.Token);
                        results.Add(new {test="card_effect",id,upgraded,powered,damage=10000-enemy.CurrentHp,totalDamage=combat.Enemies.Sum(e=>10000-e.CurrentHp),enemyCount=combat.Enemies.Count(),hp=player.Creature.CurrentHp,energy=pc.Energy,strength=player.Creature.GetPowerAmount<StrengthPower>(),vulnerable=enemy.GetPowerAmount<VulnerablePower>(),hand=pc.Hand.Cards.Select(c=>c.Id.Entry).ToArray(),exhaust=pc.ExhaustPile.Cards.Select(c=>c.Id.Entry).ToArray()});
                    }
                }
                foreach(bool duplicate in new[]{false,true}) {
                    session.ChoiceFixtureCards=["DRUM_OF_BATTLE","DEFEND_IRONCLAD"];
                    session.ChoiceFixtureUpgradedCards=upgraded?new HashSet<string>{"DRUM_OF_BATTLE"}:[];
                    await session.ResetAsync("NATIVE-ROUND3-DRUM",timeout.Token);
                    var player=session.CombatStateForSimulation.Players[0];var pc=player.PlayerCombatState!;
                    if(duplicate) await PowerCmd.Apply<DuplicationPower>(choice,player.Creature,1,player.Creature,null);
                    await CardCmd.Exhaust(choice,pc.Hand.Cards.Single(c=>c.Id.Entry=="DRUM_OF_BATTLE"));
                    results.Add(new {test="drum_exhaust",upgraded,duplicate,energy=pc.Energy,duplication=player.Creature.GetPowerAmount<DuplicationPower>()});
                }
                foreach(string modifier in new[]{"none","rupture","tungsten","buffer","injured","small_max"}) {
                    session.ChoiceFixtureCards=["BRIGHTEST_FLAME","DEFEND_IRONCLAD"];
                    session.ChoiceFixtureUpgradedCards=upgraded?new HashSet<string>{"BRIGHTEST_FLAME"}:[];
                    await session.ResetAsync("NATIVE-ROUND3-BRIGHTEST",timeout.Token);
                    var player=session.CombatStateForSimulation.Players[0];var pc=player.PlayerCombatState!;
                    player.Creature.SetMaxHpInternal(modifier=="small_max"?2:80);player.Creature.SetCurrentHpInternal(modifier=="small_max"?2:modifier=="injured"?40:80);
                    if(modifier=="rupture") await PowerCmd.Apply<RupturePower>(choice,player.Creature,2,player.Creature,null);
                    if(modifier=="tungsten") await RelicCmd.Obtain<TungstenRod>(player);
                    if(modifier=="buffer") await PowerCmd.Apply<BufferPower>(choice,player.Creature,1,player.Creature,null);
                    await session.StepAsync(session.ActionForCard("BRIGHTEST_FLAME"),timeout.Token);
                    results.Add(new {test="brightest_max_hp",upgraded,modifier,hp=player.Creature.CurrentHp,max=player.Creature.MaxHp,energy=pc.Energy,strength=player.Creature.GetPowerAmount<StrengthPower>(),buffer=player.Creature.GetPowerAmount<BufferPower>()});
                }
            }
            session.ChoiceFixtureCards=["SECOND_WIND","DEFEND_IRONCLAD","SHRUG_IT_OFF","STRIKE_IRONCLAD","BASH"];
            session.ChoiceFixtureUpgradedCards=[];await session.ResetAsync("NATIVE-ROUND3-SECOND-WIND",timeout.Token);
            {
                var player=session.CombatStateForSimulation.Players[0];var pc=player.PlayerCombatState!;
                await CardPileCmd.Add(pc.Hand.Cards.Single(c=>c.Id.Entry=="STRIKE_IRONCLAD"),PileType.Draw,skipVisuals:true);
                await CardPileCmd.Add(pc.Hand.Cards.Single(c=>c.Id.Entry=="BASH"),PileType.Draw,skipVisuals:true);
                await PowerCmd.Apply<DarkEmbracePower>(choice,player.Creature,1,player.Creature,null);
                var handBefore=pc.Hand.Cards.Select(c=>c.Id.Entry).ToArray();
                await session.StepAsync(session.ActionForCard("SECOND_WIND"),timeout.Token);
                results.Add(new {test="second_wind_snapshot",handBefore,block=player.Creature.Block,hand=pc.Hand.Cards.Select(c=>c.Id.Entry).ToArray(),exhaust=pc.ExhaustPile.Cards.Select(c=>c.Id.Entry).ToArray()});
            }
            session.ChoiceFixtureCards=["CATASTROPHE","WOUND","STRIKE_IRONCLAD","BASH"];
            await session.ResetAsync("NATIVE-ROUND3-CATASTROPHE",timeout.Token);
            {
                var combat=session.CombatStateForSimulation;var player=combat.Players[0];var pc=player.PlayerCombatState!;var enemy=combat.Enemies.First();foreach(var e in combat.Enemies) { e.SetMaxHpInternal(10000);e.SetCurrentHpInternal(10000); }
                foreach(var c in pc.Hand.Cards.Where(c=>c.Id.Entry!="CATASTROPHE").ToArray()) await CardPileCmd.Add(c,PileType.Draw,skipVisuals:true);
                await session.StepAsync(session.ActionForCard("CATASTROPHE"),timeout.Token);
                results.Add(new {test="catastrophe_playable_priority",damage=10000-enemy.CurrentHp,totalDamage=combat.Enemies.Sum(e=>10000-e.CurrentHp),draw=pc.DrawPile.Cards.Select(c=>c.Id.Entry).ToArray(),discard=pc.DiscardPile.Cards.Select(c=>c.Id.Entry).ToArray()});
            }
            session.ChoiceFixtureCards=["ANOINTED","FEED","FIEND_FIRE","IMPERVIOUS","DEFEND_IRONCLAD"];
            await session.ResetAsync("NATIVE-ROUND3-ANOINTED",timeout.Token);
            {
                var combat=session.CombatStateForSimulation;var player=combat.Players[0];var pc=player.PlayerCombatState!;
                foreach(var c in pc.Hand.Cards.Where(c=>new[]{"FEED","FIEND_FIRE","IMPERVIOUS"}.Contains(c.Id.Entry)).ToArray()) await CardPileCmd.Add(c,PileType.Draw,skipVisuals:true);
                for(int i=0;i<7;i++) await CardPileCmd.AddGeneratedCardToCombat(combat.CreateCard<MegaCrit.Sts2.Core.Models.Cards.DefendIronclad>(player),PileType.Hand,player);
                await session.StepAsync(session.ActionForCard("ANOINTED"),timeout.Token);
                results.Add(new{test="anointed_free_slots",handCount=pc.Hand.Cards.Count,draw=pc.DrawPile.Cards.Select(c=>c.Id.Entry).ToArray(),discard=pc.DiscardPile.Cards.Select(c=>c.Id.Entry).ToArray()});
            }
            session.ChoiceFixtureCards=["HIDDEN_GEM","STRIKE_IRONCLAD","BASH","SLIMED"];
            await session.ResetAsync("NATIVE-ROUND3-HIDDEN-GEM",timeout.Token);
            {
                var player=session.CombatStateForSimulation.Players[0];var pc=player.PlayerCombatState!;
                pc.Hand.Cards.Single(c=>c.Id.Entry=="STRIKE_IRONCLAD").BaseReplayCount=1;
                foreach(var c in pc.Hand.Cards.Where(c=>c.Id.Entry!="HIDDEN_GEM").ToArray()) await CardPileCmd.Add(c,PileType.Draw,skipVisuals:true);
                await session.StepAsync(session.ActionForCard("HIDDEN_GEM"),timeout.Token);
                results.Add(new{test="hidden_gem_candidates",draw=pc.DrawPile.Cards.Select(c=>new {id=c.Id.Entry,replay=c.BaseReplayCount}).ToArray()});
            }
            foreach(bool upgraded in new[]{false,true}) {
                session.ChoiceFixtureCards=["MAUL","DEFEND_IRONCLAD"];
                session.ChoiceFixtureUpgradedCards=upgraded?new HashSet<string>{"MAUL"}:[];
                await session.ResetAsync("NATIVE-ROUND3-MAUL",timeout.Token);
                var combat=session.CombatStateForSimulation;var player=combat.Players[0];var pc=player.PlayerCombatState!;var maul=pc.Hand.Cards.Single(c=>c.Id.Entry=="MAUL");var enemy=combat.Enemies.First();enemy.SetMaxHpInternal(10000);enemy.SetCurrentHpInternal(10000);
                var other=combat.CreateCard<MegaCrit.Sts2.Core.Models.Cards.Maul>(player);await CardPileCmd.AddGeneratedCardToCombat(other,PileType.Draw,player);
                maul.BaseReplayCount=1;
                await session.StepAsync(session.ActionForCard("MAUL"),timeout.Token);
                results.Add(new{test="maul_self_growth_replay",upgraded,damage=10000-enemy.CurrentHp,selfDamage=maul.DynamicVars.Damage.BaseValue,otherDamage=other.DynamicVars.Damage.BaseValue});
            }
            foreach(string modifier in new[]{"negative_strength","mangle","plow","imbalanced"}) {
                session.ChoiceFixtureCards=["REND","DEFEND_IRONCLAD"];session.ChoiceFixtureUpgradedCards=[];
                await session.ResetAsync("NATIVE-ROUND3-REND",timeout.Token);
                var combat=session.CombatStateForSimulation;var player=combat.Players[0];var enemy=combat.Enemies.First();enemy.SetMaxHpInternal(10000);enemy.SetCurrentHpInternal(10000);
                if(modifier=="negative_strength") await PowerCmd.Apply<StrengthPower>(choice,enemy,-2,player.Creature,null);
                if(modifier=="mangle") await PowerCmd.Apply<ManglePower>(choice,enemy,2,player.Creature,null);
                if(modifier=="plow") await PowerCmd.Apply<PlowPower>(choice,enemy,1,player.Creature,null);
                if(modifier=="imbalanced") await PowerCmd.Apply<ImbalancedPower>(choice,enemy,1,player.Creature,null);
                await session.StepAsync(session.ActionForCard("REND"),timeout.Token);
                results.Add(new{test="rend_debuff",modifier,damage=10000-enemy.CurrentHp});
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
