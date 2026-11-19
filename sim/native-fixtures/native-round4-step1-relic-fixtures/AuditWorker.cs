using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Relics;
using MegaCrit.Sts2.Core.TestSupport;

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
            async Task<Player> Reset()
            {
                session.ChoiceFixtureCards = ["STRIKE_IRONCLAD", "DEFEND_IRONCLAD", "BASH"];
                session.InitialHp = 80;
                session.ChoiceFixtureUpgradedCards = [];
                await session.ResetAsync("NATIVE-ROUND4-STEP1-RELIC", timeout.Token);
                var p = session.CombatStateForSimulation.Players[0];
                foreach (var r in p.Relics.ToArray()) await RelicCmd.Remove(r);
                p.RunState.Rng.Niche.LoadFromSerializable(new MegaCrit.Sts2.Core.Random.Rng(42).ToSerializable());
                return p;
            }
            object Snapshot(Player p) => p.Relics.Select(r => new {
                id=r.Id.Entry, floor=r.FloorAddedToDeck, wax=r.IsWax,
                counter=r is PenNib pn ? pn.AttacksPlayed : r is HappyFlower hf ? hf.TurnsSeen : r is LizardTail lt ? (lt.WasUsed ? 1 : 0) : 0
            }).ToArray();
            RelicModel Starter(string id) => id switch {
                "BURNING_BLOOD" => ModelDb.Relic<BurningBlood>().ToMutable(),
                "BLACK_BLOOD" => ModelDb.Relic<BlackBlood>().ToMutable(),
                "RING_OF_THE_SNAKE" => ModelDb.Relic<RingOfTheSnake>().ToMutable(),
                "CRACKED_CORE" => ModelDb.Relic<CrackedCore>().ToMutable(),
                "BOUND_PHYLACTERY" => ModelDb.Relic<BoundPhylactery>().ToMutable(),
                "DIVINE_RIGHT" => ModelDb.Relic<DivineRight>().ToMutable(),
                _ => throw new ArgumentException(id)
            };
            foreach (var spec in new [] {
                ("replace_first", "BURNING_BLOOD", 0),
                ("replace_middle", "BURNING_BLOOD", 1),
                ("replace_last", "BURNING_BLOOD", 3),
                ("black_blood_fallback", "BLACK_BLOOD", 1),
                ("snake_mapping", "RING_OF_THE_SNAKE", 1),
                ("core_mapping", "CRACKED_CORE", 1),
                ("phylactery_mapping", "BOUND_PHYLACTERY", 1),
                ("divine_mapping", "DIVINE_RIGHT", 1)
            }) {
                var p=await Reset();
                var nib=await RelicCmd.Obtain<PenNib>(p);
                for (int i=0;i<7;++i) nib.NotifyAttackPlayed();
                var flower=await RelicCmd.Obtain<HappyFlower>(p); flower.TurnsSeen=2;
                var tail=await RelicCmd.Obtain<LizardTail>(p); tail.WasUsed=true;
                var original=await RelicCmd.Obtain(Starter(spec.Item2), p, spec.Item3);
                original.FloorAddedToDeck=77;
                original.IsWax=true;
                var before=Snapshot(p);
                var events=new List<object>();
                p.RelicRemoved += r=>events.Add(new {action="remove",id=r.Id.Entry,order=p.Relics.Select(x=>x.Id.Entry).ToArray()});
                p.RelicObtained += r=>events.Add(new {action="obtain",id=r.Id.Entry,order=p.Relics.Select(x=>x.Id.Entry).ToArray()});
                var touch=(TouchOfOrobas)ModelDb.Relic<TouchOfOrobas>().ToMutable();
                bool setup=touch.SetupForPlayer(p);
                await RelicCmd.Obtain(touch,p);
                results.Add(new {test=spec.Item1,setup,starter=touch.StarterRelic?.Entry,upgraded=touch.UpgradedRelic?.Entry,
                    before,after=Snapshot(p),events,originalRemoved=original.HasBeenRemovedFromState,
                    replacementIsFresh=!ReferenceEquals(original,p.Relics[spec.Item3]),
                    siblingIdentityPreserved=p.GetRelic<PenNib>()==nib && p.GetRelic<HappyFlower>()==flower && p.GetRelic<LizardTail>()==tail,
                    nicheCounter=p.RunState.Rng.Niche.ToSerializable().counter});
            }
            {
                var p=await Reset();
                await RelicCmd.Obtain<PenNib>(p);
                await RelicCmd.Obtain<BlackBlood>(p);
                await RelicCmd.Obtain<BurningBlood>(p);
                var touch=(TouchOfOrobas)ModelDb.Relic<TouchOfOrobas>().ToMutable();
                bool setup=touch.SetupForPlayer(p);
                await RelicCmd.Obtain(touch,p);
                results.Add(new {test="first_starter_wins",setup,starter=touch.StarterRelic?.Entry,
                    upgraded=touch.UpgradedRelic?.Entry,after=Snapshot(p)});
            }
            {
                var p=await Reset();
                await RelicCmd.Obtain<PenNib>(p);
                var original=await RelicCmd.Obtain<BurningBlood>(p);
                await RelicCmd.Obtain<HappyFlower>(p);
                p.Creature.SetCurrentHpInternal(30);
                int hpBefore=p.Creature.CurrentHp,maxHpBefore=p.Creature.MaxHp;
                var touch=(TouchOfOrobas)ModelDb.Relic<TouchOfOrobas>().ToMutable();
                touch.SetupForTests(ModelDb.Relic<BurningBlood>().Id,ModelDb.Relic<Strawberry>().Id);
                await RelicCmd.Obtain(touch,p);
                results.Add(new {test="replacement_after_obtained_hook",hpBefore,maxHpBefore,
                    hp=p.Creature.CurrentHp,maxHp=p.Creature.MaxHp,after=Snapshot(p),
                    originalRemoved=original.HasBeenRemovedFromState});
            }
            {
                var p=await Reset();
                await RelicCmd.Obtain<PenNib>(p);
                var touch=(TouchOfOrobas)ModelDb.Relic<TouchOfOrobas>().ToMutable();
                bool setup=touch.SetupForPlayer(p);
                var before=Snapshot(p);
                string? error=null;
                try { await RelicCmd.Obtain(touch,p); }
                catch (Exception e) { error=e.GetType().FullName; }
                results.Add(new {test="no_starter",setup,before,after=Snapshot(p),error,
                    note="Normal Orobas pool omits this option when SetupForPlayer returns false; forced invalid Obtain leaves Touch inserted before throwing."});
            }
            File.WriteAllText(output, JsonSerializer.Serialize(new {status="completed",
                gameAssemblySha256=Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(typeof(ModelDb).Assembly.Location))).ToLowerInvariant(),
                gameSceneLoaded=MegaCrit.Sts2.Core.Nodes.NGame.Instance!=null,userDirectory=OS.GetUserDataDir(),
                scope="Controlled target-DLL TouchOfOrobas/RelicCmd.Replace fixtures, not natural runs or full parity. No relic-rule patches.",results},
                new JsonSerializerOptions {WriteIndented=true}));
            GD.Print("SIM_AUDIT_COMPLETED "+output);
            GetTree().Quit();
        }
        catch(Exception e)
        {
            File.WriteAllText(output,JsonSerializer.Serialize(new {status="error",error=e.ToString(),results},new JsonSerializerOptions {WriteIndented=true}));
            GD.PrintErr(e); GetTree().Quit(1);
        }
    }
}
