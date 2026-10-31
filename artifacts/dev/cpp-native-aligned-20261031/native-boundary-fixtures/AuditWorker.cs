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
            foreach(var fixture in new[]{(Hp:34,Max:80),(Hp:35,Max:80),(Hp:40,Max:80),(Hp:41,Max:80),(Hp:79,Max:80),(Hp:40,Max:81),(Hp:41,Max:81)}) {
                session.ChoiceFixtureCards=["STRIKE_IRONCLAD","DEFEND_IRONCLAD"];
                session.InitialHp=80;await session.ResetAsync("NATIVE-BOUNDARY-HEAL",timeout.Token);
                var combat=session.CombatStateForSimulation;var player=combat.Players[0];
                if(player.GetRelic<BurningBlood>() is null)throw new InvalidOperationException("Expected native starting BurningBlood");
                await RelicCmd.Obtain<MeatOnTheBone>(player);
                player.Creature.SetMaxHpInternal(fixture.Max);player.Creature.SetCurrentHpInternal(fixture.Hp);
                await MegaCrit.Sts2.Core.Hooks.Hook.AfterCombatVictory(player.RunState,combat,null!);
                results.Add(new{test="meat_before_burning_blood",before=fixture.Hp,max=fixture.Max,after=player.Creature.CurrentHp});
            }
            foreach(bool upgraded in new[]{false,true}) {
                session.ChoiceFixtureCards=["SETUP_STRIKE","STRIKE_IRONCLAD","DEFEND_IRONCLAD"];
                session.ChoiceFixtureUpgradedCards=upgraded?new HashSet<string>{"SETUP_STRIKE"}:[];
                session.InitialHp=80;await session.ResetAsync("NATIVE-BOUNDARY-SETUP",timeout.Token);
                var combat=session.CombatStateForSimulation;var player=combat.Players[0];var enemy=combat.Enemies.First();
                enemy.SetMaxHpInternal(1000);enemy.SetCurrentHpInternal(1000);
                await session.StepAsync(session.ActionForCard("SETUP_STRIKE"),timeout.Token);
                int first=1000-enemy.CurrentHp;var strength=player.Creature.GetPowerAmount<StrengthPower>();
                var temporary=player.Creature.GetPowerAmount<SetupStrikePower>();
                await session.StepAsync(session.ActionForCard("STRIKE_IRONCLAD"),timeout.Token);
                int second=1000-first-enemy.CurrentHp;
                await session.StepAsync(session.Actions().Single(a=>a.Combat?.Kind==SlayTheModel.Sts2.Protocol.CombatActionKind.EndTurn),timeout.Token);
                results.Add(new{test="setup_strike",upgraded,damage=first,strength,temporary,followingStrikeDamage=second,strengthNextTurn=player.Creature.GetPowerAmount<StrengthPower>()});
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
