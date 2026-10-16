using System.Diagnostics;
using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Characters;
using MegaCrit.Sts2.Core.Multiplayer.Game;
using MegaCrit.Sts2.Core.Multiplayer.Serialization;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Rewards;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves;
using MegaCrit.Sts2.Core.TestSupport;
using MegaCrit.Sts2.Core.Timeline;
using MegaCrit.Sts2.Core.Unlocks;
using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;

public static partial class WholeRunSpeedProbe
{
    private sealed record RecordedStep(int Sequence, JsonElement State, JsonElement Action);

    private static async Task RunRecordedTraceAsync(Node host, string output, string tracePath)
    {
        var entries = File.ReadLines(tracePath).Select(line =>
        {
            using var document = JsonDocument.Parse(line);
            return document.RootElement.Clone();
        }).ToArray();
        var steps = entries.Where(entry => String(entry, "type") == "decision")
            .Select((entry, sequence) => new RecordedStep(sequence,
                entry.GetProperty("state"), entry.GetProperty("action"))).ToArray();
        if (steps.Length == 0)
            throw new InvalidOperationException("Recorded terminal trace contains no accepted decisions.");
        var terminal = entries.Where(entry => String(entry, "type") == "terminal")
            .Select(entry => entry.GetProperty("state")).SingleOrDefault();
        if (terminal.ValueKind != JsonValueKind.Object)
            throw new InvalidOperationException("Recorded terminal trace has no unique terminal state.");
        var stages = new List<object>();
        string? error = null;
        var timer = Stopwatch.StartNew();
        int matchedCombatDecisions = 0;
        int matchedMapMoves = 0;
        try
        {
            if (MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null)
                throw new InvalidOperationException("Recorded replay must not load NGame.");
            const string inputSeed = "STM-WHOLE-RUN-SPEED-1";
            string seed = SeedHelper.CanonicalizeSeed(inputSeed);
            foreach (string epoch in EpochModel.AllEpochIds)
                SaveManager.Instance.ObtainEpochOverride(epoch, EpochState.Revealed);
            var player = Player.CreateForNewRun<Ironclad>(
                SaveManager.Instance.GenerateUnlockStateFromProgress(), 1);
            var actRng = new MegaCrit.Sts2.Core.Random.Rng(
                StringHelper.GetDeterministicHashCode(seed), "act_selection");
            var acts = ActModel.GetRandomList(actRng,
                SaveManager.Instance.GenerateUnlockStateFromProgress(), false)
                .Select(act => act.ToMutable()).ToList();
            var run = RunState.CreateForNewRun([player], acts, [], GameMode.Standard, 0, seed);
            // Normal Standard runs apply native discovery-order adjustments.
            // TestMode suppresses them unless this built-in flag is set.
            RunManager.Instance.ForceDiscoveryOrderModifications = true;
            RunManager.Instance.SetUpNewSingleplayer(run, false, null);
            var selector = new AutoProbeCardSelector();
            using var selectorScope = CardSelectCmd.PushSelector(selector);
            await RunManager.Instance.EnterAct(0, false).WaitAsync(TimeSpan.FromSeconds(5));

            int firstMap = Array.FindIndex(steps, step => String(step.Action, "kind") == "map");
            if (firstMap < 0)
                throw new InvalidOperationException("Recorded terminal trace never entered its first map room.");
            await ReplayRecordedEventAsync(run.CurrentRoom as EventRoom, steps[..firstMap], run, player,
                selector);
            stages.Add(new { stage = "recorded-neow", hp = player.Creature.CurrentHp,
                deck = player.Deck.Cards.Select(card => card.Id.ToString()).Order().ToArray(),
                relics = player.Relics.Select(relic => relic.Id.ToString()).Order().ToArray() });

            int index = firstMap;
            for (; index < steps.Length;)
            {
                var map = steps[index];
                if (String(map.Action, "kind") != "map")
                    throw new InvalidOperationException("Recorded room has an action after its terminal/map boundary: "
                        + map.Sequence);
                VerifyRecordedPlayer(map.State, run, player, "before map " + map.Sequence);
                int x = Integer(map.Action, "x");
                int y = Integer(map.Action, "y");
                var point = run.CurrentMapPoint?.Children.SingleOrDefault(child =>
                    child.coord.col == x && child.coord.row == y)
                    ?? throw new InvalidOperationException("Recorded map target is not a native child: " + x + "," + y);
                await RunManager.Instance.EnterMapCoord(point.coord).WaitAsync(TimeSpan.FromSeconds(10));
                matchedMapMoves++;
                index++;
                int nextMap = index;
                while (nextMap < steps.Length && String(steps[nextMap].Action, "kind") != "map")
                    nextMap++;
                var roomSteps = steps[index..nextMap];
                var room = run.CurrentRoom ?? throw new InvalidOperationException("Native replay has no room after map move.");
                int floor = run.TotalFloor;
                switch (room)
                {
                    case CombatRoom combat:
                        matchedCombatDecisions += await ReplayRecordedCombatAsync(host, combat, run, player,
                            roomSteps, selector);
                        if (!player.Creature.IsDead)
                        {
                            if (!combat.IsPreFinished)
                                throw new InvalidOperationException("Recorded combat ended before native victory at floor " + floor);
                            await ReplayRecordedRewardsAsync(host, combat, player, roomSteps);
                        }
                        break;
                    case EventRoom nativeEvent:
                        await ReplayRecordedEventAsync(nativeEvent, roomSteps, run, player, selector);
                        break;
                    case RestSiteRoom rest:
                        var restAction = roomSteps.FirstOrDefault(step =>
                            String(step.State, "screen").Contains("RestSite", StringComparison.OrdinalIgnoreCase)
                            && String(step.Action, "kind") == "button"
                            && String(step.Action, "label") != "继续");
                        if (restAction is null)
                            throw new InvalidOperationException("Recorded rest site has no chosen native option.");
                        int optionIndex = String(restAction.Action, "label") == "Rest"
                            ? rest.Options.ToList().FindIndex(option => option.GetType().Name == "HealRestSiteOption")
                            : rest.Options.ToList().FindIndex(option => option.OptionId.ToString()
                                .Contains(String(restAction.Action, "label"), StringComparison.OrdinalIgnoreCase));
                        if (optionIndex < 0 || !await RunManager.Instance.RestSiteSynchronizer
                                .ChooseLocalOption(optionIndex).WaitAsync(TimeSpan.FromSeconds(10)))
                            throw new InvalidOperationException("Recorded rest-site option was rejected.");
                        for (int discardIndex = 0; discardIndex < roomSteps.Length; discardIndex++)
                        {
                            if (String(roomSteps[discardIndex].State, "screen") != "NPotionPopup"
                                || String(roomSteps[discardIndex].Action, "label") != "Discard")
                                continue;
                            var openPopup = roomSteps.Take(discardIndex).LastOrDefault(step =>
                                String(step.Action, "kind") == "potion")
                                ?? throw new InvalidOperationException("Recorded discard has no potion menu action.");
                            string hostPotionId = String(openPopup.Action, "entityId");
                            string potionModel = openPopup.State.GetProperty("entities").EnumerateArray()
                                .Where(entity => String(entity, "id") == hostPotionId)
                                .Select(entity => String(entity, "modelId")).Single();
                            int slot = player.PotionSlots.ToList().FindIndex(potion =>
                                potion?.Id.ToString() == potionModel);
                            if (slot < 0)
                                throw new InvalidOperationException("Recorded discard potion is absent natively: "
                                    + potionModel);
                            RunManager.Instance.ActionQueueSet.EnqueueWithoutSynchronizing(
                                new DiscardPotionGameAction(player, (uint)slot, false));
                            var discardTimer = Stopwatch.StartNew();
                            while (player.PotionSlots[slot] is not null
                                && discardTimer.Elapsed < TimeSpan.FromSeconds(5))
                                await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
                            if (player.PotionSlots[slot] is not null)
                                throw new TimeoutException("Recorded native potion discard did not clear its slot.");
                        }
                        break;
                    case TreasureRoom treasure:
                        await InvokeNativeTaskAsync(treasure, "DoNormalRewards");
                        await InvokeNativeTaskAsync(treasure, "DoExtraRewardsIfNeeded");
                        var treasureSynchronizer = RunManager.Instance.TreasureRoomRelicSynchronizer;
                        object? awardResult = null;
                        treasureSynchronizer.RelicsAwarded += result => awardResult = result;
                        treasureSynchronizer.PickRelicLocally(0);
                        var awardTimer = Stopwatch.StartNew();
                        while (awardResult is null && awardTimer.Elapsed < TimeSpan.FromSeconds(2))
                            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
                        if (awardResult is not System.Collections.IEnumerable awards)
                            throw new InvalidOperationException("Recorded treasure produced no relic award.");
                        var award = awards.Cast<object>().Single();
                        const System.Reflection.BindingFlags flags = System.Reflection.BindingFlags.Instance
                            | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic;
                        var relic = award.GetType().GetField("relic", flags)?.GetValue(award) as RelicModel
                            ?? throw new InvalidOperationException("Recorded treasure has no awarded relic.");
                        await RelicCmd.Obtain(relic.ToMutable(), player, 0).WaitAsync(TimeSpan.FromSeconds(10));
                        break;
                    case MerchantRoom:
                        if (roomSteps.Any(step => String(step.Action, "kind") == "buy"))
                            throw new NotSupportedException("Recorded replay does not yet execute merchant purchases.");
                        break;
                    default:
                        throw new NotSupportedException("Recorded replay has no native room handler for "
                            + room.GetType().Name);
                }
                stages.Add(new { stage = "recorded-room", floor, room = room.GetType().Name,
                    traceStart = index, traceEnd = nextMap, hp = player.Creature.CurrentHp,
                    gold = player.Gold, deckCount = player.Deck.Cards.Count,
                    gameOver = RunManager.Instance.IsGameOver });
                index = nextMap;
                if (RunManager.Instance.IsGameOver) break;
            }
            if (index != steps.Length || !RunManager.Instance.IsGameOver
                || Integer(terminal.GetProperty("player"), "floor") != run.TotalFloor
                || Integer(terminal.GetProperty("player"), "hp") != player.Creature.CurrentHp
                || String(terminal, "screen") != "defeat")
                throw new InvalidOperationException("Recorded and native terminal states do not match.");
            stages.Add(new { stage = "recorded-terminal", nativeGameOver = RunManager.Instance.IsGameOver,
                finalHp = player.Creature.CurrentHp, floor = run.TotalFloor,
                gameSceneLoaded = MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null });
        }
        catch (Exception exception)
        {
            error = exception.ToString();
            stages.Add(new { stage = "recorded-mismatch", message = exception.Message });
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
        File.WriteAllText(output, JsonSerializer.Serialize(new
        {
            tracePath, traceDecisions = steps.Length, matchedCombatDecisions, matchedMapMoves,
            forcedDiscoveryOrder = true,
            duplicateDefendOrdinal = System.Environment.GetEnvironmentVariable("STS2_PROBE_REPLAY_DEFEND_ORDINAL"),
            elapsedMs = timer.Elapsed.TotalMilliseconds, stages, error,
            gameSceneLoaded = MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null,
        }, new JsonSerializerOptions { WriteIndented = true }));
        GD.Print("WHOLE_RUN_RECORDED_REPLAY " + (error is null ? "complete" : "mismatch")
            + " output=" + output);
        if (error is not null)
            throw new InvalidOperationException("Recorded terminal replay diverged: " + error);
    }

    private static async Task ReplayRecordedEventAsync(EventRoom? room,
        IReadOnlyList<RecordedStep> steps, RunState run, Player player,
        AutoProbeCardSelector selector)
    {
        var nativeEvent = room?.LocalMutableEvent
            ?? throw new InvalidOperationException("Recorded native event room is unavailable.");
        for (int stepIndex = 0; stepIndex < steps.Count; stepIndex++)
        {
            var step = steps[stepIndex];
            if (String(step.Action, "kind") != "event"
                || String(step.Action, "label").Equals("Proceed", StringComparison.OrdinalIgnoreCase))
                continue;
            VerifyRecordedPlayer(step.State, run, player,
                "before event " + step.Sequence);
            var candidates = nativeEvent.CurrentOptions.Where(option => !option.IsLocked && !option.WasChosen)
                .ToArray();
            var hostActions = step.State.GetProperty("actions").EnumerateArray()
                .Where(action => String(action, "kind") == "event"
                    && !String(action, "label").Equals("Proceed", StringComparison.OrdinalIgnoreCase)).ToArray();
            int index = Array.FindIndex(hostActions, action => String(action, "id") == String(step.Action, "id"));
            if (index < 0 || index >= candidates.Length)
                throw new InvalidOperationException("Recorded event option is not available natively: "
                    + String(step.Action, "label"));
            var selectedModels = new List<string>();
            for (int choiceIndex = stepIndex + 1; choiceIndex < steps.Count; choiceIndex++)
            {
                var choice = steps[choiceIndex];
                if (String(choice.Action, "kind") == "event") break;
                if (String(choice.Action, "kind") != "select_card") continue;
                var buttons = choice.State.GetProperty("actions").EnumerateArray()
                    .Where(action => String(action, "kind") == "select_card").ToArray();
                int cardIndex = Array.FindIndex(buttons, action =>
                    String(action, "id") == String(choice.Action, "id"));
                var cards = choice.State.GetProperty("choices").EnumerateArray().ToArray();
                if (cardIndex < 0 || cardIndex >= cards.Length)
                    throw new InvalidOperationException("Recorded event card choice has no native candidate.");
                selectedModels.Add(String(cards[cardIndex].GetProperty("card"), "modelId"));
            }
            if (selectedModels.Count > 0)
                selector.ForcedCardModelSelections.Enqueue(selectedModels.ToArray());
            await candidates[index].Chosen().WaitAsync(TimeSpan.FromSeconds(10));
        }
        if (!nativeEvent.IsFinished)
            throw new InvalidOperationException("Recorded event did not reach its native completed state: "
                + nativeEvent.Id.Entry);
    }

    private static async Task ReplayRecordedRewardsAsync(Node host, CombatRoom combat,
        Player player, IReadOnlyList<RecordedStep> roomSteps)
    {
        bool skipAll = roomSteps.Any(step => String(step.Action, "label") == "跳过")
            && !roomSteps.Any(step => String(step.Action, "kind") == "reward");
        if (!skipAll)
        {
            await combat.OfferRoomEndRewards().WaitAsync(TimeSpan.FromSeconds(10));
            CompletePendingPotionOverflow(player);
            return;
        }
        // A recorded Proceed/Skip before taking any reward must not be replaced
        // with TestMode's automatic take-all policy.
        bool previousTestMode = TestMode.IsOn;
        try
        {
            TestMode.IsOn = false;
            var offer = combat.OfferRoomEndRewards();
            var deadline = Stopwatch.StartNew();
            while (!HasOpenRecordedRewardSet() && !offer.IsCompleted
                && deadline.Elapsed < TimeSpan.FromSeconds(5))
                await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
            if (!HasOpenRecordedRewardSet())
                throw new InvalidOperationException("Native rewards were not exposed for recorded Skip; "
                    + "Offer task status=" + offer.Status);
            RunManager.Instance.RewardsSetSynchronizer.SkipLocalRewardsSet();
            await offer.WaitAsync(TimeSpan.FromSeconds(10));
        }
        finally
        {
            TestMode.IsOn = previousTestMode;
        }
    }

    private static bool HasOpenRecordedRewardSet()
    {
        var synchronizer = RunManager.Instance.RewardsSetSynchronizer;
        const System.Reflection.BindingFlags flags = System.Reflection.BindingFlags.Instance
            | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic;
        var states = synchronizer.GetType().GetField("_rewardStates", flags)?.GetValue(synchronizer)
            as System.Collections.IEnumerable;
        if (states is null) return false;
        foreach (var state in states)
        {
            var stack = state?.GetType().GetField("rewardsStack", flags)?.GetValue(state)
                as System.Collections.IList;
            if (stack is { Count: > 0 }) return true;
        }
        return false;
    }

    private static async Task<int> ReplayRecordedCombatAsync(Node host, CombatRoom room,
        RunState run, Player player, IReadOnlyList<RecordedStep> roomSteps,
        AutoProbeCardSelector selector)
    {
        await WaitForCombatDecisionAsync(host, room, player, null);
        int matched = 0;
        for (int roomIndex = 0; roomIndex < roomSteps.Count; roomIndex++)
        {
            var step = roomSteps[roomIndex];
            if (String(step.Action, "kind") is not ("play" or "endTurn" or "potion"))
                continue;
            if (room.IsPreFinished || player.Creature.IsDead)
                throw new InvalidOperationException("Recorded combat has an action after native terminal: " + step.Sequence);
            VerifyRecordedCombat(step.State, room, run, player, step.Sequence);
            var state = room.CombatState;
            if (String(step.Action, "kind") == "potion")
            {
                for (int choiceIndex = roomIndex + 1; choiceIndex < roomSteps.Count; choiceIndex++)
                {
                    var choice = roomSteps[choiceIndex];
                    string kind = String(choice.Action, "kind");
                    if (kind is "play" or "endTurn" or "potion") break;
                    if (kind != "choose_card") continue;
                    var buttons = choice.State.GetProperty("actions").EnumerateArray()
                        .Where(action => String(action, "kind") == "choose_card").ToArray();
                    int selectedIndex = Array.FindIndex(buttons, action =>
                        String(action, "id") == String(choice.Action, "id"));
                    var cards = choice.State.GetProperty("choices").EnumerateArray().ToArray();
                    if (selectedIndex < 0 || selectedIndex >= cards.Length)
                        throw new InvalidOperationException("Recorded potion card choice has no native candidate.");
                    selector.ForcedCardModelSelections.Enqueue([
                        String(cards[selectedIndex].GetProperty("card"), "modelId")]);
                }
                string hostPotionId = String(step.Action, "entityId");
                string potionModel = step.State.GetProperty("entities").EnumerateArray()
                    .Where(entity => String(entity, "id") == hostPotionId)
                    .Select(entity => String(entity, "modelId")).Single();
                int slot = player.PotionSlots.ToList().FindIndex(potion =>
                    potion?.Id.ToString() == potionModel);
                if (slot < 0)
                    throw new InvalidOperationException("Recorded combat potion is absent natively: "
                        + potionModel);
                var potionAction = new UsePotionAction(player, (uint)slot, null, null, true);
                RunManager.Instance.ActionQueueSet.EnqueueWithoutSynchronizing(potionAction);
                matched++;
                await WaitForCombatDecisionAsync(host, room, player, potionAction);
                continue;
            }
            var actions = CombatCaptureService.GetLegalActions(state);
            CombatActionDescriptor action;
            if (String(step.Action, "kind") == "endTurn")
                action = actions.Single(candidate => candidate.Kind == CombatActionKind.EndTurn);
            else
            {
                var hand = player.PlayerCombatState!.Hand.Cards.ToArray();
                var hostHand = step.State.GetProperty("entities").EnumerateArray()
                    .Where(entity => String(entity, "kind") == "card" && String(entity, "pile") == "hand")
                    .ToArray();
                string hostId = String(step.Action, "entityId");
                int hostHandIndex = Array.FindIndex(hostHand, card => String(card, "id") == hostId);
                if (hostHandIndex < 0)
                    throw new InvalidOperationException("Recorded play card is not in the native hand at step "
                        + step.Sequence);
                string selectedModel = String(hostHand[hostHandIndex], "modelId");
                int selectedUpgrade = Integer(hostHand[hostHandIndex], "upgradeLevel");
                string selectedEnchantment = String(hostHand[hostHandIndex], "enchantmentId");
                int sameCardOrdinal = hostHand.Take(hostHandIndex).Count(hostCard =>
                    String(hostCard, "modelId") == selectedModel
                    && Integer(hostCard, "upgradeLevel") == selectedUpgrade
                    && String(hostCard, "enchantmentId") == selectedEnchantment);
                var matchingCards = hand.Where(candidate => candidate.Id.ToString() == selectedModel
                    && candidate.CurrentUpgradeLevel == selectedUpgrade
                    && (candidate.Enchantment?.Id.ToString() ?? "") == selectedEnchantment).ToArray();
                if (sameCardOrdinal >= matchingCards.Length)
                    throw new InvalidOperationException("Recorded play card identity differs at step "
                        + step.Sequence);
                var card = matchingCards[sameCardOrdinal];
                uint? targetId = null;
                string hostTarget = String(step.Action, "targetId");
                if (hostTarget.Length > 0)
                {
                    var hostEnemies = step.State.GetProperty("entities").EnumerateArray()
                        .Where(entity => String(entity, "kind") == "enemy" && Integer(entity, "hp") > 0)
                        .ToArray();
                    var nativeEnemies = state.Enemies.Where(enemy => enemy.IsAlive).ToArray();
                    int enemyIndex = Array.FindIndex(hostEnemies, enemy => String(enemy, "id") == hostTarget);
                    if (enemyIndex < 0 || enemyIndex >= nativeEnemies.Length)
                        throw new InvalidOperationException("Recorded target enemy is not available at step "
                            + step.Sequence);
                    targetId = nativeEnemies[enemyIndex].CombatId;
                }
                uint cardIndex = NetCombatCard.FromModel(card).CombatCardIndex;
                action = actions.Single(candidate => candidate.Kind == CombatActionKind.PlayCard
                    && candidate.CombatCardIndex == cardIndex && candidate.TargetCreatureId == targetId);
            }
            var nativeAction = CombatActionExecutor.CreateGameAction(state, action);
            RunManager.Instance.ActionQueueSet.EnqueueWithoutSynchronizing(nativeAction);
            matched++;
            await WaitForCombatDecisionAsync(host, room, player, nativeAction);
        }
        return matched;
    }

    private static void VerifyRecordedCombat(JsonElement hostState, CombatRoom room,
        RunState run, Player player, int step)
    {
        VerifyRecordedPlayer(hostState, run, player, "combat " + step);
        int hostEnergy = Integer(hostState.GetProperty("player"), "energy");
        if (hostEnergy != player.PlayerCombatState!.Energy)
            throw new InvalidOperationException("Combat energy differs at step " + step + ": host "
                + hostEnergy + ", probe " + player.PlayerCombatState.Energy);
        int hostBlock = Integer(hostState.GetProperty("player"), "block");
        if (hostBlock != player.Creature.Block)
            throw new InvalidOperationException("Combat player block differs at step " + step + ": host "
                + hostBlock + ", probe " + player.Creature.Block);
        var hostHand = hostState.GetProperty("entities").EnumerateArray()
            .Where(entity => String(entity, "kind") == "card" && String(entity, "pile") == "hand")
            .Select(entity => String(entity, "modelId")).Order().ToArray();
        var nativeHand = player.PlayerCombatState.Hand.Cards.Select(card => card.Id.ToString())
            .Order().ToArray();
        if (!hostHand.SequenceEqual(nativeHand))
            throw new InvalidOperationException("Combat hand differs at step " + step + ": host "
                + string.Join(',', hostHand) + ", probe " + string.Join(',', nativeHand));
        var hostHandDetails = hostState.GetProperty("entities").EnumerateArray()
            .Where(entity => String(entity, "kind") == "card" && String(entity, "pile") == "hand")
            .Select(entity => String(entity, "modelId") + ":" + Integer(entity, "upgradeLevel"))
            .Order().ToArray();
        var nativeHandDetails = player.PlayerCombatState.Hand.Cards.Select(card => card.Id.ToString()
            + ":" + card.CurrentUpgradeLevel)
            .Order().ToArray();
        if (!hostHandDetails.SequenceEqual(nativeHandDetails))
            throw new InvalidOperationException("Combat hand card details differ at step " + step + ": host "
                + string.Join(',', hostHandDetails) + ", probe " + string.Join(',', nativeHandDetails));
        var hostPiles = hostState.GetProperty("entities").EnumerateArray()
            .Where(entity => String(entity, "kind") == "card"
                && String(entity, "pile") is not ("deck" or "choice"))
            .GroupBy(entity => String(entity, "pile"))
            .ToDictionary(group => group.Key, group => group.Select(entity =>
                String(entity, "modelId") + ":" + Integer(entity, "upgradeLevel"))
                .Order().ToArray());
        var nativePiles = player.PlayerCombatState.AllPiles.ToDictionary(
            pile => pile.Type.ToString().ToLowerInvariant(),
            pile => pile.Cards.Select(card => card.Id.ToString() + ":" + card.CurrentUpgradeLevel)
                .Order().ToArray());
        foreach (var pile in nativePiles)
        {
            var hostCards = hostPiles.GetValueOrDefault(pile.Key) ?? [];
            if (!hostCards.SequenceEqual(pile.Value))
                throw new InvalidOperationException("Combat " + pile.Key + " pile differs at step " + step);
        }
        var hostEnemies = hostState.GetProperty("entities").EnumerateArray()
            .Where(entity => String(entity, "kind") == "enemy" && Integer(entity, "hp") > 0)
            .Select(entity => (String(entity, "modelId"), Integer(entity, "hp"),
                Integer(entity, "block"))).ToArray();
        var nativeEnemies = room.CombatState.Enemies.Where(enemy => enemy.IsAlive)
            .Select(enemy => (enemy.ModelId.ToString(), enemy.CurrentHp, enemy.Block)).ToArray();
        if (!hostEnemies.SequenceEqual(nativeEnemies))
            throw new InvalidOperationException("Combat enemies differ at step " + step + ": host "
                + string.Join(',', hostEnemies) + ", probe " + string.Join(',', nativeEnemies));
    }

    private static void VerifyRecordedPlayer(JsonElement hostState, RunState run, Player player, string where)
    {
        var host = hostState.GetProperty("player");
        if (Integer(host, "hp") != player.Creature.CurrentHp
            || Integer(host, "gold") != player.Gold
            || Integer(host, "floor") != run.TotalFloor)
            throw new InvalidOperationException("Player state differs " + where + ": host hp/gold/floor "
                + Integer(host, "hp") + "/" + Integer(host, "gold") + "/" + Integer(host, "floor")
                + ", probe " + player.Creature.CurrentHp + "/" + player.Gold + "/" + run.TotalFloor);
        var hostDeck = hostState.GetProperty("entities").EnumerateArray()
            .Where(entity => String(entity, "kind") == "card" && String(entity, "pile") == "deck")
            .Select(entity => String(entity, "modelId")).Order().ToArray();
        if (hostDeck.Length > 0)
        {
            var nativeDeck = player.Deck.Cards.Select(card => card.Id.ToString()).Order().ToArray();
            if (!hostDeck.SequenceEqual(nativeDeck))
                throw new InvalidOperationException("Deck differs " + where + ": host "
                    + string.Join(',', hostDeck) + ", probe " + string.Join(',', nativeDeck));
            var hostDetails = hostState.GetProperty("entities").EnumerateArray()
                .Where(entity => String(entity, "kind") == "card" && String(entity, "pile") == "deck")
                .Select(entity => String(entity, "modelId") + ":" + Integer(entity, "upgradeLevel")
                    + ":" + String(entity, "enchantmentId")).Order().ToArray();
            var nativeDetails = player.Deck.Cards.Select(card => card.Id.ToString() + ":"
                + card.CurrentUpgradeLevel + ":" + (card.Enchantment?.Id.ToString() ?? ""))
                .Order().ToArray();
            if (!hostDetails.SequenceEqual(nativeDetails))
                throw new InvalidOperationException("Deck upgrade/enchantment differs " + where + ": host "
                    + string.Join(',', hostDetails) + ", probe " + string.Join(',', nativeDetails));
        }
        var hostRelics = hostState.GetProperty("entities").EnumerateArray()
            .Where(entity => String(entity, "kind") == "relic")
            .Select(entity => String(entity, "modelId")).Order().ToArray();
        var nativeRelics = player.Relics.Select(relic => relic.Id.ToString()).Order().ToArray();
        if (!hostRelics.SequenceEqual(nativeRelics))
            throw new InvalidOperationException("Relics differ " + where + ": host "
                + string.Join(',', hostRelics) + ", probe " + string.Join(',', nativeRelics));
        var hostPotions = hostState.GetProperty("entities").EnumerateArray()
            .Where(entity => String(entity, "kind") == "potion")
            .Select(entity => String(entity, "modelId")).Order().ToArray();
        var nativePotions = player.PotionSlots.Where(potion => potion is not null)
            .Select(potion => potion!.Id.ToString()).Order().ToArray();
        if (!hostPotions.SequenceEqual(nativePotions))
            throw new InvalidOperationException("Potions differ " + where + ": host "
                + string.Join(',', hostPotions) + ", probe " + string.Join(',', nativePotions));
    }

    private static string String(JsonElement value, string name)
        => value.TryGetProperty(name, out var property) && property.ValueKind == JsonValueKind.String
            ? property.GetString() ?? "" : "";

    private static int Integer(JsonElement value, string name)
        => value.TryGetProperty(name, out var property) && property.TryGetInt32(out int result)
            ? result : -1;
}
