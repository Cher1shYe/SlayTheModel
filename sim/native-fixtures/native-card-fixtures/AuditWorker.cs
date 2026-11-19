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
            var cases = new[] {
                (Name:"weak", Selected:"STRIKE_IRONCLAD", Weak:1, Strength:0, Pen:-1, Giant:0, EnemyVuln:0, Exhaust:0),
                (Name:"weak_strength5", Selected:"STRIKE_IRONCLAD", Weak:1, Strength:5, Pen:-1, Giant:0, EnemyVuln:0, Exhaust:0),
                (Name:"pen_nib_before8", Selected:"STRIKE_IRONCLAD", Weak:0, Strength:0, Pen:8, Giant:0, EnemyVuln:0, Exhaust:0),
                (Name:"pen_nib_before9", Selected:"STRIKE_IRONCLAD", Weak:0, Strength:0, Pen:9, Giant:0, EnemyVuln:0, Exhaust:0),
                (Name:"gigantification1", Selected:"STRIKE_IRONCLAD", Weak:0, Strength:0, Pen:-1, Giant:1, EnemyVuln:0, Exhaust:0),
                (Name:"gigantification2", Selected:"STRIKE_IRONCLAD", Weak:0, Strength:0, Pen:-1, Giant:2, EnemyVuln:0, Exhaust:0),
                (Name:"enemy_vulnerable3", Selected:"STRIKE_IRONCLAD", Weak:0, Strength:0, Pen:-1, Giant:0, EnemyVuln:3, Exhaust:0),
                (Name:"bully_enemy_vulnerable5", Selected:"BULLY", Weak:0, Strength:0, Pen:-1, Giant:0, EnemyVuln:5, Exhaust:0),
                (Name:"ashen_exhaust1", Selected:"ASHEN_STRIKE", Weak:0, Strength:0, Pen:-1, Giant:0, EnemyVuln:0, Exhaust:1),
                (Name:"perfected_includes_self", Selected:"PERFECTED_STRIKE", Weak:0, Strength:0, Pen:-1, Giant:0, EnemyVuln:0, Exhaust:0),
            };
            foreach (var fixture in cases)
            {
                session.ChoiceFixtureCards = ["THRASH", fixture.Selected, "DEFEND_IRONCLAD"];
                session.ChoiceFixtureUpgradedCards = [];
                await session.ResetAsync("SIM-AUDIT-CARD-EDGES", timeout.Token);
                var combat = session.CombatStateForSimulation;
                var player = combat.Players[0];
                var pc = player.PlayerCombatState!;
                var thrash = pc.Hand.Cards.Single(c => c.Id.Entry == "THRASH");
                var enemy = combat.Enemies.First();
                if (fixture.Weak > 0) await PowerCmd.Apply<WeakPower>(choice, player.Creature, fixture.Weak, player.Creature, null);
                if (fixture.Strength > 0) await PowerCmd.Apply<StrengthPower>(choice, player.Creature, fixture.Strength, player.Creature, null);
                if (fixture.Giant > 0) await PowerCmd.Apply<GigantificationPower>(choice, player.Creature, fixture.Giant, player.Creature, null);
                if (fixture.EnemyVuln > 0) await PowerCmd.Apply<VulnerablePower>(choice, enemy, fixture.EnemyVuln, player.Creature, null);
                if (fixture.Pen >= 0) {
                    await RelicCmd.Obtain<PenNib>(player);
                    var pen = player.GetRelic<PenNib>()!;
                    for (int i=0; i<fixture.Pen; ++i) pen.NotifyAttackPlayed();
                }
                if (fixture.Exhaust > 0) await CardCmd.Exhaust(choice, pc.Hand.Cards.Single(c => c.Id.Entry == "DEFEND_IRONCLAD"));
                decimal before = thrash.DynamicVars.Damage.BaseValue;
                int hp = enemy.CurrentHp;
                await session.StepAsync(session.ActionForCard("THRASH"), timeout.Token);
                results.Add(new { test = "thrash_" + fixture.Name, damage = hp-enemy.CurrentHp,
                    baseBefore = before, baseAfter = thrash.DynamicVars.Damage.BaseValue,
                    growth = thrash.DynamicVars.Damage.BaseValue-before,
                    giantAfter = player.Creature.GetPowerAmount<GigantificationPower>(),
                    exhausted = pc.ExhaustPile.Cards.Select(c => c.Id.Entry).ToArray() });
            }
            session.ChoiceFixtureCards = ["CINDER", "DEFEND_IRONCLAD", "STRIKE_IRONCLAD"];
            await session.ResetAsync("SIM-AUDIT-CINDER-DARK", timeout.Token);
            {
                var player=session.CombatStateForSimulation.Players[0];
                var pc=player.PlayerCombatState!;
                await CardPileCmd.Add(pc.Hand.Cards.Single(c=>c.Id.Entry=="STRIKE_IRONCLAD"),PileType.Draw,skipVisuals:true);
                await PowerCmd.Apply<DarkEmbracePower>(choice,player.Creature,1,player.Creature,null);
                await session.StepAsync(session.ActionForCard("CINDER"),timeout.Token);
                results.Add(new {test="cinder_dark_embrace",hand=pc.Hand.Cards.Select(c=>c.Id.Entry).ToArray(),
                    draw=pc.DrawPile.Cards.Select(c=>c.Id.Entry).ToArray(),exhausted=pc.ExhaustPile.Cards.Select(c=>c.Id.Entry).ToArray()});
            }
            session.ChoiceFixtureCards = ["ANGER", "DEFEND_IRONCLAD"];
            await session.ResetAsync("SIM-AUDIT-ANGER-STATUS", timeout.Token);
            {
                var player=session.CombatStateForSimulation.Players[0];var pc=player.PlayerCombatState!;
                var anger=pc.Hand.Cards.Single(c=>c.Id.Entry=="ANGER");
                CardCmd.Enchant(ModelDb.Enchantment<Sown>().ToMutable(),anger,8);
                int energyBefore=pc.Energy;
                await session.StepAsync(session.ActionForCard("ANGER"),timeout.Token);
                results.Add(new {test="anger_sown_clone_status",energyBefore,energyAfter=pc.Energy,
                    discarded=pc.DiscardPile.Cards.Select(c=>new {card=c.Id.Entry,original=ReferenceEquals(c,anger),
                        enchantment=c.Enchantment?.Id.Entry,amount=c.Enchantment?.Amount,status=c.Enchantment?.Status.ToString()}).ToArray()});
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
