using System.Diagnostics;
using System.Reflection;
using System.Reflection.Emit;
using System.Runtime.CompilerServices;
using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Context;
using MegaCrit.Sts2.Core.Entities.CardRewardAlternatives;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Merchant;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Characters;
using MegaCrit.Sts2.Core.Models.Encounters;
using MegaCrit.Sts2.Core.Multiplayer.Game;
using MegaCrit.Sts2.Core.Nodes.Screens.Shops;
using MegaCrit.Sts2.Core.Nodes.Screens.TreasureRoomRelic;
using MegaCrit.Sts2.Core.Nodes.RestSite;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Nodes.TreasureRooms;
using MegaCrit.Sts2.Core.Multiplayer;
using MegaCrit.Sts2.Core.Multiplayer.Serialization;
using MegaCrit.Sts2.Core.Rewards;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Saves;
using MegaCrit.Sts2.Core.TestSupport;
using MegaCrit.Sts2.Core.Timeline;
using MegaCrit.Sts2.Core.Unlocks;
using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;

/// <summary>First speed gate for native whole-run setup without NGame or scene UI.</summary>
public static partial class WholeRunSpeedProbe
{
    public static async Task RunAsync(Node host, string output, bool legacyRawSeed = false)
    {
        var collectorReplay = System.Environment.GetEnvironmentVariable("STS2_PROBE_COLLECTOR_REPLAY");
        if (!string.IsNullOrWhiteSpace(collectorReplay))
        {
            if (legacyRawSeed)
                throw new InvalidOperationException("Collector replay requires the canonical seed mode.");
            await RunCollectorReplayAsync(host, output, collectorReplay);
            return;
        }
        var recordedTrace = System.Environment.GetEnvironmentVariable("STS2_PROBE_REPLAY_TRACE");
        if (!string.IsNullOrWhiteSpace(recordedTrace))
        {
            if (legacyRawSeed)
                throw new InvalidOperationException("Recorded terminal replay requires the canonical seed mode.");
            await RunRecordedTraceAsync(host, output, recordedTrace);
            return;
        }
        var stages = new List<object>();
        var warnings = new List<string>();
        string? error = null;
        Exception? failure = null;
        const string defaultInputSeed = "STM-WHOLE-RUN-SPEED-1";
        string configuredInputSeed = System.Environment.GetEnvironmentVariable("STS2_PROBE_SEED") ?? "";
        string inputSeed = string.IsNullOrWhiteSpace(configuredInputSeed)
            ? defaultInputSeed
            : configuredInputSeed.Trim();
        bool genericRun = System.Environment.GetEnvironmentVariable("STS2_PROBE_GENERIC") == "1";
        bool genericUsePotions = genericRun
            && System.Environment.GetEnvironmentVariable("STS2_PROBE_USE_POTIONS") == "1";
        if (genericRun && legacyRawSeed)
            throw new InvalidOperationException("The generic runner requires canonical seed handling.");
        string normalGameSeed = SeedHelper.CanonicalizeSeed(inputSeed);
        // The old raw-seed route is available only as an explicit historical
        // performance fixture. The default uses the game's new-run seed rule.
        string seed = legacyRawSeed ? inputSeed : normalGameSeed;
        try
        {
            if (MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null)
                throw new InvalidOperationException("Whole-run speed probe must not load NGame.");
            var wholeTimer = Stopwatch.StartNew();
            var timer = Stopwatch.StartNew();
            // The scene-backed host reveals epochs in its isolated profile and
            // NGame derives the player's unlock state from that profile.
            // Keep the raw-seed fixture's historical all-unlocked behavior.
            if (!legacyRawSeed)
                foreach (string epoch in EpochModel.AllEpochIds)
                    SaveManager.Instance.ObtainEpochOverride(epoch, EpochState.Revealed);
            var unlockState = legacyRawSeed
                ? UnlockState.all : SaveManager.Instance.GenerateUnlockStateFromProgress();
            var player = Player.CreateForNewRun<Ironclad>(unlockState, 1);
            var actRng = new MegaCrit.Sts2.Core.Random.Rng(
                StringHelper.GetDeterministicHashCode(seed), "act_selection");
            var acts = ActModel.GetRandomList(actRng,
                SaveManager.Instance.GenerateUnlockStateFromProgress(), false)
                .Select(act => act.ToMutable()).ToList();
            var run = RunState.CreateForNewRun([player], acts, [], GameMode.Standard, 0, seed);
            stages.Add(new { stage = "create-run", elapsedMs = timer.Elapsed.TotalMilliseconds,
                acts = acts.Select(act => act.Id.Entry).ToArray() });

            timer.Restart();
            if (!legacyRawSeed)
                RunManager.Instance.ForceDiscoveryOrderModifications = true;
            RunManager.Instance.SetUpNewSingleplayer(run, false, null);
            stages.Add(new { stage = "setup-run", elapsedMs = timer.Elapsed.TotalMilliseconds,
                state = DescribeRun(run) });

            var selector = new AutoProbeCardSelector();
            using var selectorScope = CardSelectCmd.PushSelector(selector);

            timer.Restart();
            await RunManager.Instance.EnterAct(0, false).WaitAsync(TimeSpan.FromSeconds(5));
            var currentEvent = (run.CurrentRoom as EventRoom)?.LocalMutableEvent;
            stages.Add(new { stage = "enter-act", elapsedMs = timer.Elapsed.TotalMilliseconds,
                state = DescribeRun(run), roomMembers = DescribeMembers(run.CurrentRoom),
                eventMembers = DescribeMembers(currentEvent),
                optionCount = currentEvent?.CurrentOptions.Count,
                optionMembers = DescribeMembers(currentEvent?.CurrentOptions.FirstOrDefault()) });

            if (currentEvent is null) throw new InvalidOperationException("Native act did not open the Neow event.");
            var options = currentEvent.CurrentOptions.Where(option => !option.IsLocked && !option.WasChosen).ToArray();
            if (options.Length == 0) throw new InvalidOperationException("Neow has no available native option.");
            stages.Add(new { stage = "neow-options", choices = options.Select(option => option.TextKey).ToArray() });
            var chosen = options[0];
            int deckBeforeNeow = player.Deck.Cards.Count;
            timer.Restart();
            await chosen.Chosen().WaitAsync(TimeSpan.FromSeconds(5));
            if (!currentEvent.IsFinished || !chosen.WasChosen)
                throw new InvalidOperationException("Native Neow option did not finish through Chosen().");
            if (chosen.Relic is not null && !player.Relics.Any(relic => relic.Id == chosen.Relic.Id))
                throw new InvalidOperationException("Native Neow relic was not added to the player.");
            if (chosen.Relic?.Id.Entry == "PRECISE_SCISSORS"
                && player.Deck.Cards.Count != deckBeforeNeow - 1)
                throw new InvalidOperationException("Precise Scissors did not remove exactly one deck card.");
            stages.Add(new { stage = "choose-neow", elapsedMs = timer.Elapsed.TotalMilliseconds,
                selected = chosen.TextKey, eventFinished = currentEvent.IsFinished,
                remainingOptions = currentEvent.CurrentOptions.Select(option => option.TextKey).ToArray(),
                cardSelections = selector.SelectedCardIds.ToArray(), deckBeforeNeow,
                deckAfterNeow = player.Deck.Cards.Count,
                relics = player.Relics.Select(relic => relic.Id.Entry).ToArray(),
                state = DescribeRun(run) });
            stages.Add(new { stage = "generated-map", points = DescribeFutureMap(run.CurrentMapPoint) });

            var route = System.Environment.GetEnvironmentVariable("STS2_PROBE_ROUTE");
            if (genericRun && !string.IsNullOrWhiteSpace(route))
                throw new InvalidOperationException("The generic runner chooses its own route; STS2_PROBE_ROUTE must be empty.");
            if (!legacyRawSeed && route is ("shop" or "rest"))
                throw new NotSupportedException("The shop/rest fixture requires the explicit legacy raw-seed mode.");
            if (legacyRawSeed && route == "event")
                throw new NotSupportedException("The first-unknown event comparison requires the canonical seed mode.");
            if (genericRun)
            {
                await ProbeGenericRunAsync(host, run, player, selector, stages, warnings, wholeTimer,
                    genericUsePotions);
            }
            else if (route is "shop" or "rest")
            {
                await ProbeOutsideRouteAsync(host, run, player, selector, stages, wholeTimer, route);
            }
            else
            {

            var nextPoint = run.CurrentMapPoint?.Children.OrderBy(point => point.coord.col).FirstOrDefault()
                ?? throw new InvalidOperationException("Native map has no reachable next point.");
            timer.Restart();
            await RunManager.Instance.EnterMapCoord(nextPoint.coord).WaitAsync(TimeSpan.FromSeconds(5));
            stages.Add(new { stage = "enter-map-child", elapsedMs = timer.Elapsed.TotalMilliseconds,
                pointType = nextPoint.PointType.ToString(), state = DescribeRun(run),
                roomMembers = DescribeMembers(run.CurrentRoom) });

            var combatRoom = run.CurrentRoom as CombatRoom
                ?? throw new InvalidOperationException("First map child did not create a native combat room.");
            stages.Add(new { stage = "first-combat-enter", encounter = combatRoom.Encounter.Id.Entry,
                enemies = combatRoom.CombatState.Enemies.Select(enemy => new {
                    modelId = enemy.Monster?.Id.ToString(), hp = enemy.CurrentHp }).ToArray(),
                deck = player.Deck.Cards.Select(card => card.Id.ToString())
                    .OrderBy(id => id, StringComparer.Ordinal).ToArray(),
                playerHp = player.Creature.CurrentHp,
                testMode = TestMode.IsOn });
            timer.Restart();
            // Keep per-decision projection out of ordinary throughput timings.
            List<object>? firstCombatTrace = System.Environment.GetEnvironmentVariable("STS2_PROBE_TRACE_DRAWS") == "1"
                ? new List<object>() : null;
            int combatDecisions = await PlayCombatAsync(host, combatRoom, player, firstCombatTrace);
            if (firstCombatTrace is not null)
                stages.Add(new { stage = "first-combat-decision-trace", decisions = firstCombatTrace });
            if (!combatRoom.IsPreFinished || player.Creature.IsDead)
                throw new InvalidOperationException("Native first combat did not end in victory.");
            stages.Add(new { stage = "combat-victory", elapsedMs = timer.Elapsed.TotalMilliseconds,
                combatDecisions, encounter = combatRoom.Encounter.Id.Entry,
                hp = player.Creature.CurrentHp, roomPreFinished = combatRoom.IsPreFinished,
                state = DescribeRun(run) });

            // In the normal game NCombatUi invokes this after its victory animation.
            // There is no NCombatUi in this worker, so advance at that same native boundary.
            timer.Restart();
            int deckBeforeRewards = player.Deck.Cards.Count;
            int goldBeforeRewards = player.Gold;
            int potionsBeforeRewards = player.PotionSlots.Count(potion => potion is not null);
            await combatRoom.OfferRoomEndRewards().WaitAsync(TimeSpan.FromSeconds(10));
            if (selector.SelectedRewardCardIds.Count > 0
                && player.Deck.Cards.Count != deckBeforeRewards + selector.SelectedRewardCardIds.Count)
                throw new InvalidOperationException("Native reward card selection did not update the deck.");
            stages.Add(new { stage = "combat-rewards", elapsedMs = timer.Elapsed.TotalMilliseconds,
                deckBeforeRewards, deckAfterRewards = player.Deck.Cards.Count,
                goldBeforeRewards, goldAfterRewards = player.Gold,
                potionsBeforeRewards, potionsAfterRewards = player.PotionSlots.Count(potion => potion is not null),
                rewardCardCandidates = selector.RewardCandidateIds.LastOrDefault(),
                rewardCardSelections = selector.SelectedRewardCardIds.ToArray(),
                state = DescribeRun(run) });

            var followingPoint = (route == "event"
                    ? run.CurrentMapPoint?.Children.Where(point => point.PointType.ToString() == "Unknown")
                        .OrderBy(point => point.coord.col).FirstOrDefault()
                    : run.CurrentMapPoint?.Children.OrderBy(point => point.coord.col).FirstOrDefault())
                ?? throw new InvalidOperationException("Native map has no reachable point after combat rewards.");
            timer.Restart();
            await RunManager.Instance.EnterMapCoord(followingPoint.coord).WaitAsync(TimeSpan.FromSeconds(10));
            stages.Add(new { stage = "enter-next-map-child", elapsedMs = timer.Elapsed.TotalMilliseconds,
                pointType = followingPoint.PointType.ToString(), state = DescribeRun(run),
                roomMembers = DescribeMembers(run.CurrentRoom) });
            if (route == "event")
            {
                var eventRoom = run.CurrentRoom as EventRoom
                    ?? throw new InvalidOperationException("First unknown map point did not open a native event room.");
                var nativeEvent = eventRoom.LocalMutableEvent
                    ?? throw new InvalidOperationException("First unknown room has no native event model.");
                var eventOptions = nativeEvent.CurrentOptions.Where(option => !option.IsLocked && !option.WasChosen)
                    .ToArray();
                stages.Add(new { stage = "first-unknown-event-options", eventId = nativeEvent.Id.Entry,
                    options = eventOptions.Select(option => new { option.TextKey,
                        title = option.Title.GetFormattedText(),
                        descriptionKey = option.Description.ToString() }).ToArray(),
                    playerHp = player.Creature.CurrentHp, gold = player.Gold,
                    deck = player.Deck.Cards.Select(card => card.Id.ToString())
                        .OrderBy(id => id, StringComparer.Ordinal).ToArray() });
                if (eventOptions.Length == 0)
                    throw new InvalidOperationException("First unknown event has no available native option.");
                int eventOptionIndex = int.TryParse(System.Environment.GetEnvironmentVariable("STS2_PROBE_EVENT_OPTION"),
                    out int configuredEventOption) ? configuredEventOption : 0;
                if (eventOptionIndex < 0 || eventOptionIndex >= eventOptions.Length)
                    throw new ArgumentOutOfRangeException(nameof(eventOptionIndex), "Unavailable native event option.");
                var eventChoice = eventOptions[eventOptionIndex];
                int selectedBeforeEvent = selector.SelectedCardModels.Count;
                int offersBeforeEvent = selector.SelectionOffers.Count;
                await eventChoice.Chosen().WaitAsync(TimeSpan.FromSeconds(10));
                stages.Add(new { stage = "first-unknown-event-choice", eventId = nativeEvent.Id.Entry,
                    selected = eventChoice.TextKey, eventOptionIndex, eventFinished = nativeEvent.IsFinished,
                    remainingOptions = nativeEvent.CurrentOptions.Select(option => option.TextKey).ToArray(),
                    selectedCards = selector.SelectedCardModels.Skip(selectedBeforeEvent)
                        .Select(card => new { modelId = card.Id.ToString(),
                            enchantmentId = card.Enchantment?.Id.ToString() }).ToArray(),
                    selectionOffers = selector.SelectionOffers.Skip(offersBeforeEvent).ToArray(),
                    playerHp = player.Creature.CurrentHp, gold = player.Gold,
                    deck = player.Deck.Cards.Select(card => card.Id.ToString())
                        .OrderBy(id => id, StringComparer.Ordinal).ToArray(),
                    deckDetails = player.Deck.Cards.Select(card => new { modelId = card.Id.ToString(),
                            upgradeLevel = card.CurrentUpgradeLevel,
                            enchantmentId = card.Enchantment?.Id.ToString() })
                        .OrderBy(card => card.modelId, StringComparer.Ordinal)
                        .ThenBy(card => card.upgradeLevel)
                        .ThenBy(card => card.enchantmentId, StringComparer.Ordinal).ToArray(),
                    relics = player.Relics.Select(relic => relic.Id.ToString())
                        .OrderBy(id => id, StringComparer.Ordinal).ToArray(),
                    potions = player.PotionSlots.Where(potion => potion is not null)
                        .Select(potion => potion!.Id.ToString()).OrderBy(id => id, StringComparer.Ordinal).ToArray() });
                var afterEventPoint = run.CurrentMapPoint?.Children.OrderBy(point => point.coord.col).FirstOrDefault()
                    ?? throw new InvalidOperationException("First unknown event has no reachable map child.");
                timer.Restart();
                await RunManager.Instance.EnterMapCoord(afterEventPoint.coord).WaitAsync(TimeSpan.FromSeconds(10));
                var afterEventCombat = run.CurrentRoom as CombatRoom;
                stages.Add(new { stage = "enter-after-first-unknown-event",
                    elapsedMs = timer.Elapsed.TotalMilliseconds,
                    col = afterEventPoint.coord.col, row = afterEventPoint.coord.row,
                    pointType = afterEventPoint.PointType.ToString(),
                    roomType = run.CurrentRoom?.GetType().Name,
                    encounter = afterEventCombat?.Encounter.Id.ToString(),
                    enemies = afterEventCombat?.CombatState.Enemies.Select(enemy => new {
                        modelId = enemy.Monster?.Id.ToString(), hp = enemy.CurrentHp }).ToArray(),
                    playerHp = player.Creature.CurrentHp, gold = player.Gold,
                    deckDetails = player.Deck.Cards.Select(card => new { modelId = card.Id.ToString(),
                            upgradeLevel = card.CurrentUpgradeLevel,
                            enchantmentId = card.Enchantment?.Id.ToString() })
                        .OrderBy(card => card.modelId, StringComparer.Ordinal)
                        .ThenBy(card => card.upgradeLevel)
                        .ThenBy(card => card.enchantmentId, StringComparer.Ordinal).ToArray() });
            }
            stages.Add(new { stage = "minimal-sequence-complete", elapsedMs = wholeTimer.Elapsed.TotalMilliseconds,
                gameSceneLoaded = MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null });

            if (!legacyRawSeed)
            {
                stages.Add(new { stage = "canonical-prefix-complete", elapsedMs = wholeTimer.Elapsed.TotalMilliseconds,
                    currentRoom = run.CurrentRoom?.GetType().Name,
                    playerHp = player.Creature.CurrentHp });
                if (System.Environment.GetEnvironmentVariable("STS2_PROBE_LONG_PATH") == "1")
                    await ProbeGenericRunAsync(host, run, player, selector, stages, warnings, wholeTimer,
                        usePotions: false);
            }
            else
            {

            // The next naturally generated room for this pinned seed is Aroma of Chaos.
            // Its Let Go option verifies the transformation selector without a test room.
            var transformEvent = (run.CurrentRoom as EventRoom)?.LocalMutableEvent
                ?? throw new InvalidOperationException("Next map child did not open a native event.");
            if (transformEvent.Id.Entry != "AROMA_OF_CHAOS")
                throw new InvalidOperationException("Pinned next event changed; transform probe needs a new seed.");
            var transformOption = transformEvent.CurrentOptions.Single(option =>
                option.TextKey == "AROMA_OF_CHAOS.pages.INITIAL.options.LET_GO");
            int deckBeforeTransform = player.Deck.Cards.Count;
            int previousSelections = selector.SelectedCardModels.Count;
            timer.Restart();
            await transformOption.Chosen().WaitAsync(TimeSpan.FromSeconds(10));
            var transformed = selector.SelectedCardModels.Skip(previousSelections).ToArray();
            if (!transformEvent.IsFinished || !transformOption.WasChosen || transformed.Length != 1
                || player.Deck.Cards.Count != deckBeforeTransform
                || transformed.Any(selected => player.Deck.Cards.Any(card => ReferenceEquals(card, selected))))
                throw new InvalidOperationException("Native transform choice did not replace the selected deck card.");
            stages.Add(new { stage = "natural-event-transform", elapsedMs = timer.Elapsed.TotalMilliseconds,
                eventId = transformEvent.Id.Entry,
                selectedCards = transformed.Select(card => card.Id.Entry).ToArray(),
                deckBeforeTransform, deckAfterTransform = player.Deck.Cards.Count,
                deckAfterIds = player.Deck.Cards.Select(card => card.Id.Entry).ToArray(),
                eventFinished = transformEvent.IsFinished });

            var postTransformPoint = run.CurrentMapPoint?.Children.OrderBy(point => point.coord.col).FirstOrDefault()
                ?? throw new InvalidOperationException("Native map has no reachable point after the transform event.");
            timer.Restart();
            await RunManager.Instance.EnterMapCoord(postTransformPoint.coord).WaitAsync(TimeSpan.FromSeconds(10));
            stages.Add(new { stage = "enter-post-transform-map-child", elapsedMs = timer.Elapsed.TotalMilliseconds,
                pointType = postTransformPoint.PointType.ToString(), state = DescribeRun(run),
                roomMembers = DescribeMembers(run.CurrentRoom) });

            var secondCombatRoom = run.CurrentRoom as CombatRoom
                ?? throw new InvalidOperationException("Post-transform map child did not create a native combat room.");
            timer.Restart();
            int secondCombatDecisions = await PlayCombatAsync(host, secondCombatRoom, player);
            if (!secondCombatRoom.IsPreFinished || player.Creature.IsDead)
                throw new InvalidOperationException("Pinned second native combat did not end in victory.");
            stages.Add(new { stage = "second-combat-terminal", elapsedMs = timer.Elapsed.TotalMilliseconds,
                combatDecisions = secondCombatDecisions, encounter = secondCombatRoom.Encounter.Id.Entry,
                hp = player.Creature.CurrentHp, victory = secondCombatRoom.IsPreFinished && !player.Creature.IsDead,
                state = DescribeRun(run) });

            if (!player.Creature.IsDead)
            {
                timer.Restart();
                int deckBeforeSecondRewards = player.Deck.Cards.Count;
                int goldBeforeSecondRewards = player.Gold;
                int potionsBeforeSecondRewards = player.PotionSlots.Count(potion => potion is not null);
                int rewardChoicesBefore = selector.SelectedRewardCardIds.Count;
                await secondCombatRoom.OfferRoomEndRewards().WaitAsync(TimeSpan.FromSeconds(10));
                int rewardChoicesAdded = selector.SelectedRewardCardIds.Count - rewardChoicesBefore;
                if (player.Deck.Cards.Count != deckBeforeSecondRewards + rewardChoicesAdded)
                    throw new InvalidOperationException("Second native reward card selection did not update the deck.");
                stages.Add(new { stage = "second-combat-rewards", elapsedMs = timer.Elapsed.TotalMilliseconds,
                    deckBeforeSecondRewards, deckAfterRewards = player.Deck.Cards.Count,
                    goldBeforeSecondRewards, goldAfterRewards = player.Gold,
                    potionsBeforeSecondRewards,
                    potionsAfterRewards = player.PotionSlots.Count(potion => potion is not null),
                    rewardCardSelections = selector.SelectedRewardCardIds.Skip(rewardChoicesBefore).ToArray(),
                    state = DescribeRun(run) });

                var afterSecondCombatPoint = run.CurrentMapPoint?.Children.OrderBy(point => point.coord.col).FirstOrDefault()
                    ?? throw new InvalidOperationException("Native map has no reachable point after the second combat.");
                timer.Restart();
                await RunManager.Instance.EnterMapCoord(afterSecondCombatPoint.coord).WaitAsync(TimeSpan.FromSeconds(10));
                stages.Add(new { stage = "enter-after-second-combat", elapsedMs = timer.Elapsed.TotalMilliseconds,
                    pointType = afterSecondCombatPoint.PointType.ToString(), state = DescribeRun(run),
                    roomMembers = DescribeMembers(run.CurrentRoom) });

                var nextEvent = (run.CurrentRoom as EventRoom)?.LocalMutableEvent
                    ?? throw new InvalidOperationException("Second combat's next map child did not open a native event.");
                var nextEventOptions = nextEvent.CurrentOptions
                    .Where(option => !option.IsLocked && !option.WasChosen).ToArray();
                stages.Add(new { stage = "next-event-options", eventId = nextEvent.Id.Entry,
                    choices = nextEventOptions.Select(option => option.TextKey).ToArray() });
                var nextEventChoice = nextEventOptions.FirstOrDefault()
                    ?? throw new InvalidOperationException("Next event has no available native option.");
                int choicesBeforeNextEvent = selector.SelectedCardModels.Count;
                var deckBeforeNextEvent = player.Deck.Cards.ToArray();
                int goldBeforeNextEvent = player.Gold;
                timer.Restart();
                await nextEventChoice.Chosen().WaitAsync(TimeSpan.FromSeconds(10));
                if (!nextEventChoice.WasChosen)
                    throw new InvalidOperationException("Next native event option was not marked chosen.");
                var selectedNextEventCards = selector.SelectedCardModels.Skip(choicesBeforeNextEvent).ToArray();
                if (nextEvent.Id.Entry == "MORPHIC_GROVE"
                    && nextEventChoice.TextKey == "MORPHIC_GROVE.pages.INITIAL.options.GROUP"
                    && (!nextEvent.IsFinished || selectedNextEventCards.Length != 2
                        || ReferenceEquals(selectedNextEventCards.ElementAtOrDefault(0),
                            selectedNextEventCards.ElementAtOrDefault(1))
                        || selectedNextEventCards.Any(selected => !deckBeforeNextEvent.Any(card => ReferenceEquals(card, selected)))
                        || player.Gold != 0 || player.Deck.Cards.Count != deckBeforeNextEvent.Length
                        || selectedNextEventCards.Any(selected => player.Deck.Cards.Any(card => ReferenceEquals(card, selected)))
                        || player.Deck.Cards.Count(card => !deckBeforeNextEvent.Any(before => ReferenceEquals(card, before))) != 2))
                    throw new InvalidOperationException("Morphic Grove did not spend gold and replace both selected deck cards.");
                stages.Add(new { stage = "choose-next-event", elapsedMs = timer.Elapsed.TotalMilliseconds,
                    eventId = nextEvent.Id.Entry, selected = nextEventChoice.TextKey,
                    eventFinished = nextEvent.IsFinished,
                    remainingOptions = nextEvent.CurrentOptions.Select(option => option.TextKey).ToArray(),
                    cardSelections = selector.SelectedCardIds.Skip(choicesBeforeNextEvent).ToArray(),
                    deckBeforeIds = deckBeforeNextEvent.Select(card => card.Id.Entry).ToArray(),
                    deckAfterIds = player.Deck.Cards.Select(card => card.Id.Entry).ToArray(),
                    goldBeforeNextEvent, goldAfterNextEvent = player.Gold,
                    state = DescribeRun(run) });

                if (nextEvent.IsFinished)
                {
                    var afterSecondEventPoint = run.CurrentMapPoint?.Children
                        .OrderBy(point => point.coord.col).FirstOrDefault()
                        ?? throw new InvalidOperationException("Native map has no reachable point after the second event.");
                    timer.Restart();
                    await RunManager.Instance.EnterMapCoord(afterSecondEventPoint.coord)
                        .WaitAsync(TimeSpan.FromSeconds(10));
                    stages.Add(new { stage = "enter-after-second-event", elapsedMs = timer.Elapsed.TotalMilliseconds,
                        pointType = afterSecondEventPoint.PointType.ToString(), state = DescribeRun(run),
                        roomMembers = DescribeMembers(run.CurrentRoom) });

                    var thirdEvent = (run.CurrentRoom as EventRoom)?.LocalMutableEvent
                        ?? throw new InvalidOperationException("Second event's next map child did not open a native event.");
                    var thirdEventOptions = thirdEvent.CurrentOptions
                        .Where(option => !option.IsLocked && !option.WasChosen).ToArray();
                    stages.Add(new { stage = "third-event-options", eventId = thirdEvent.Id.Entry,
                        choices = thirdEventOptions.Select(option => option.TextKey).ToArray() });
                    var thirdEventChoice = thirdEventOptions.FirstOrDefault()
                        ?? throw new InvalidOperationException("Third event has no available native option.");
                    int choicesBeforeThirdEvent = selector.SelectedCardModels.Count;
                    int enchantedBeforeThirdEvent = player.Deck.Cards.Count(card => card.Enchantment is not null);
                    timer.Restart();
                    await thirdEventChoice.Chosen().WaitAsync(TimeSpan.FromSeconds(10));
                    if (!thirdEventChoice.WasChosen)
                        throw new InvalidOperationException("Third native event option was not marked chosen.");
                    var selectedThirdEventCards = selector.SelectedCardModels.Skip(choicesBeforeThirdEvent).ToArray();
                    if (thirdEvent.Id.Entry == "SELF_HELP_BOOK"
                        && thirdEventChoice.TextKey == "SELF_HELP_BOOK.pages.INITIAL.options.READ_THE_BACK"
                        && (!thirdEvent.IsFinished || selectedThirdEventCards.Length != 1
                            || selectedThirdEventCards[0].Enchantment is null
                            || !player.Deck.Cards.Any(card => ReferenceEquals(card, selectedThirdEventCards[0]))
                            || player.Deck.Cards.Count(card => card.Enchantment is not null) != enchantedBeforeThirdEvent + 1))
                        throw new InvalidOperationException("Self Help Book did not enchant the selected attack.");
                    stages.Add(new { stage = "choose-third-event", elapsedMs = timer.Elapsed.TotalMilliseconds,
                        eventId = thirdEvent.Id.Entry, selected = thirdEventChoice.TextKey,
                        eventFinished = thirdEvent.IsFinished,
                        remainingOptions = thirdEvent.CurrentOptions.Select(option => option.TextKey).ToArray(),
                        cardSelections = selector.SelectedCardIds.Skip(choicesBeforeThirdEvent).ToArray(),
                        enchantedBeforeThirdEvent,
                        enchantedAfterThirdEvent = player.Deck.Cards.Count(card => card.Enchantment is not null),
                        selectedEnchantmentIds = selectedThirdEventCards.Select(card => card.Enchantment?.Id.Entry).ToArray(),
                        state = DescribeRun(run) });

                    if (thirdEvent.IsFinished)
                    {
                        var afterThirdEventPoint = run.CurrentMapPoint?.Children
                            .OrderBy(point => point.coord.col).FirstOrDefault()
                            ?? throw new InvalidOperationException("Native map has no reachable point after the third event.");
                        timer.Restart();
                        await RunManager.Instance.EnterMapCoord(afterThirdEventPoint.coord)
                            .WaitAsync(TimeSpan.FromSeconds(10));
                        stages.Add(new { stage = "enter-after-third-event", elapsedMs = timer.Elapsed.TotalMilliseconds,
                            pointType = afterThirdEventPoint.PointType.ToString(), state = DescribeRun(run),
                            roomMembers = DescribeMembers(run.CurrentRoom) });

                        var eliteRoom = run.CurrentRoom as CombatRoom
                            ?? throw new InvalidOperationException("Third event's next map child did not create a native combat room.");
                        timer.Restart();
                        int eliteCombatDecisions = await PlayCombatAsync(host, eliteRoom, player);
                        if (!eliteRoom.IsPreFinished && !player.Creature.IsDead)
                            throw new InvalidOperationException("Native elite combat stopped without a terminal outcome.");
                        stages.Add(new { stage = "elite-combat-terminal", elapsedMs = timer.Elapsed.TotalMilliseconds,
                            encounter = eliteRoom.Encounter.Id.Entry, combatDecisions = eliteCombatDecisions,
                            hp = player.Creature.CurrentHp, victory = eliteRoom.IsPreFinished && !player.Creature.IsDead,
                            runManagerGameOver = RunManager.Instance.IsGameOver,
                            runManagerInProgress = RunManager.Instance.IsInProgress,
                            combatInProgress = CombatManager.Instance.IsInProgress,
                            state = DescribeRun(run) });
                        if (!player.Creature.IsDead)
                        {
                            timer.Restart();
                            int deckBeforeEliteRewards = player.Deck.Cards.Count;
                            int goldBeforeEliteRewards = player.Gold;
                            int relicsBeforeEliteRewards = player.Relics.Count;
                            int rewardsBeforeElite = selector.SelectedRewardCardIds.Count;
                            await eliteRoom.OfferRoomEndRewards().WaitAsync(TimeSpan.FromSeconds(10));
                            int eliteRewardChoices = selector.SelectedRewardCardIds.Count - rewardsBeforeElite;
                            if (player.Deck.Cards.Count != deckBeforeEliteRewards + eliteRewardChoices)
                                throw new InvalidOperationException("Native elite card reward did not update the deck.");
                            stages.Add(new { stage = "elite-combat-rewards", elapsedMs = timer.Elapsed.TotalMilliseconds,
                                deckBeforeEliteRewards, deckAfterRewards = player.Deck.Cards.Count,
                                goldBeforeEliteRewards, goldAfterRewards = player.Gold,
                                relicsBeforeEliteRewards, relicsAfterRewards = player.Relics.Count,
                                rewardCardSelections = selector.SelectedRewardCardIds.Skip(rewardsBeforeElite).ToArray(),
                                state = DescribeRun(run) });
                        }
                    }
                }
            }

            if (!player.Creature.IsDead || !RunManager.Instance.IsGameOver)
                throw new InvalidOperationException("Pinned natural run did not reach a native defeat terminal state.");
            stages.Add(new { stage = "natural-run-defeat", elapsedMs = wholeTimer.Elapsed.TotalMilliseconds,
                actIndex = run.CurrentActIndex, actFloor = run.ActFloor, totalFloor = run.TotalFloor,
                finalHp = player.Creature.CurrentHp, gameSceneLoaded = MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null });
            }
            }
        }
        catch (Exception exception)
        {
            failure = exception;
            error = exception.ToString();
            Godot.GD.PrintErr("WHOLE_RUN_SPEED_PROBE_FAILED " + exception);
        }
        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(output))!);
        File.WriteAllText(output, JsonSerializer.Serialize(new
        {
            generatedAtUtc = DateTimeOffset.UtcNow,
            gameSceneLoaded = MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null,
            inputSeed,
            seed,
            normalGameSeed,
            genericRun,
            genericUsePotions,
            seedHandling = legacyRawSeed ? "legacy-raw-internal-performance-fixture" : "native-canonicalized",
            testMode = TestMode.IsOn,
            stages,
            warnings,
            error,
        }, new JsonSerializerOptions { WriteIndented = true }));
        Godot.GD.Print("WHOLE_RUN_SPEED_PROBE "
            + (error is not null ? "blocked" : warnings.Count > 0 ? "complete-with-warnings" : "complete")
            + " output=" + output);
        if (failure is not null)
            throw new InvalidOperationException("Whole-run speed probe failed; see its JSON output.", failure);
    }

    private static async Task ProbeGenericRunAsync(Node host, RunState run, Player player,
        AutoProbeCardSelector selector, List<object> stages, List<string> warnings, Stopwatch wholeTimer,
        bool usePotions)
    {
        int maxRooms = int.TryParse(System.Environment.GetEnvironmentVariable("STS2_PROBE_MAX_ROOMS"),
            out int configuredMaxRooms) && configuredMaxRooms > 0
            ? configuredMaxRooms
            : 200;
        for (int roomNumber = 0; roomNumber < maxRooms && !RunManager.Instance.IsGameOver; roomNumber++)
        {
            if (MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null)
                throw new InvalidOperationException("Long-path probe unexpectedly loaded NGame.");
            var room = run.CurrentRoom ?? throw new InvalidOperationException("Long-path probe has no current room.");
            int floor = run.TotalFloor;
            int hpBefore = player.Creature.CurrentHp;
            int goldBefore = player.Gold;
            int deckBefore = player.Deck.Cards.Count;
            int relicsBefore = player.Relics.Count;
            var potionSlotsBefore = player.PotionSlots
                .Select(potion => potion?.Id.ToString()).ToArray();
            int rewardChoicesBefore = selector.SelectedRewardCardIds.Count;
            int selectorChoicesBefore = selector.SelectedCardModels.Count;
            string? encounter = null;
            string? eventId = null;
            int combatDecisions = 0;
            string[] eventOptions = [];
            string? restOption = null;
            string? treasureRelic = null;
            string[] skippedRewards = [];
            var timer = Stopwatch.StartNew();

            switch (room)
            {
                case CombatRoom combat:
                    encounter = combat.Encounter.Id.Entry;
                    combatDecisions = await PlayCombatAsync(host, combat, player, usePotions: usePotions);
                    if (!combat.IsPreFinished && !player.Creature.IsDead)
                        throw new InvalidOperationException("Long-path combat ended without a terminal outcome.");
                    if (!player.Creature.IsDead)
                    {
                        await combat.OfferRoomEndRewards().WaitAsync(TimeSpan.FromSeconds(10));
                        skippedRewards = CompletePendingPotionOverflow(player);
                        if (skippedRewards.Length > 0)
                        {
                            if (!potionSlotsBefore.SequenceEqual(player.PotionSlots
                                    .Select(potion => potion?.Id.ToString())))
                                throw new InvalidOperationException(
                                    "Skipped full-slot potion reward unexpectedly changed the potion inventory.");
                            warnings.Add("Floor " + floor + ": TestMode automatic reward selection left a potion "
                                + "unclaimed with full slots; native SkipLocalRewardsSet closed the set. "
                                + "The game's TaskHelper logs its completion assertion before this skip.");
                        }
                    }
                    break;
                case EventRoom eventRoom:
                    var nativeEvent = eventRoom.LocalMutableEvent
                        ?? throw new InvalidOperationException("Long-path event room has no event model.");
                    eventId = nativeEvent.Id.Entry;
                    var chosenKeys = new List<string>();
                    for (int choice = 0; choice < 32 && !nativeEvent.IsFinished; choice++)
                    {
                        var option = nativeEvent.CurrentOptions
                            .Select((candidate, index) => new { candidate, index })
                            .Where(item => !item.candidate.IsLocked && !item.candidate.WasChosen)
                            .OrderBy(item => chosenKeys.Count(key => key == item.candidate.TextKey))
                            .ThenBy(item => item.index)
                            .Select(item => item.candidate)
                            .FirstOrDefault()
                            ?? throw new InvalidOperationException("Long-path event has no available option: " + eventId);
                        chosenKeys.Add(option.TextKey);
                        await option.Chosen().WaitAsync(TimeSpan.FromSeconds(10));
                        if (!option.WasChosen)
                            throw new InvalidOperationException("Long-path event option was not marked chosen.");
                    }
                    if (!nativeEvent.IsFinished)
                        throw new InvalidOperationException("Long-path event exceeded 32 option pages: " + eventId
                            + "; chosen=" + string.Join(" > ", chosenKeys)
                            + "; remaining=" + string.Join(", ", nativeEvent.CurrentOptions
                                .Where(option => !option.IsLocked && !option.WasChosen)
                                .Select(option => option.TextKey)));
                    eventOptions = chosenKeys.ToArray();
                    break;
                case RestSiteRoom rest:
                    var heal = rest.Options.FirstOrDefault(option => option.GetType().Name == "HealRestSiteOption"
                        && option.IsEnabled && player.Creature.CurrentHp < player.Creature.MaxHp);
                    var selected = heal ?? rest.Options.FirstOrDefault(option => option.IsEnabled)
                        ?? throw new InvalidOperationException("Long-path rest site has no enabled option.");
                    restOption = selected.OptionId.ToString();
                    int optionIndex = rest.Options.ToList().IndexOf(selected);
                    bool applied = await RunManager.Instance.RestSiteSynchronizer
                        .ChooseLocalOption(optionIndex).WaitAsync(TimeSpan.FromSeconds(10));
                    if (!applied) throw new InvalidOperationException("Native rest site rejected its selected option.");
                    break;
                case TreasureRoom treasure:
                    await InvokeNativeTaskAsync(treasure, "DoNormalRewards");
                    await InvokeNativeTaskAsync(treasure, "DoExtraRewardsIfNeeded");
                    var synchronizer = RunManager.Instance.TreasureRoomRelicSynchronizer;
                    var offered = synchronizer.CurrentRelics?.ToArray()
                        ?? throw new InvalidOperationException("Long-path treasure has no offered relics.");
                    if (offered.Length == 0) throw new InvalidOperationException("Long-path treasure has empty relic offer.");
                    object? awardResult = null;
                    synchronizer.RelicsAwarded += result => awardResult = result;
                    synchronizer.PickRelicLocally(0);
                    var awardWait = Stopwatch.StartNew();
                    while (awardResult is null && awardWait.Elapsed < TimeSpan.FromSeconds(2))
                        await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
                    if (awardResult is not System.Collections.IEnumerable results)
                        throw new InvalidOperationException("Long-path treasure emitted no relic award.");
                    var award = results.Cast<object>().Single();
                    const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
                    var awardedRelic = award.GetType().GetField("relic", flags)?.GetValue(award) as RelicModel
                        ?? throw new InvalidOperationException("Long-path treasure award has no relic.");
                    var awardedPlayer = award.GetType().GetField("player", flags)?.GetValue(award) as Player
                        ?? throw new InvalidOperationException("Long-path treasure award has no player.");
                    if (!ReferenceEquals(awardedPlayer, player) || !offered.Any(relic => relic.Id == awardedRelic.Id))
                        throw new InvalidOperationException("Long-path treasure award does not match its offer.");
                    await RelicCmd.Obtain(awardedRelic.ToMutable(), player, 0).WaitAsync(TimeSpan.FromSeconds(10));
                    treasureRelic = awardedRelic.Id.Entry;
                    break;
                case MerchantRoom:
                    // Leaving a merchant without buying is a legal native room decision.
                    break;
                case MapRoom:
                    // EnterNextAct lands on the new act's native map room. It has
                    // no separate policy action; the next decision is the map child.
                    break;
                default:
                    throw new NotSupportedException("Long-path probe has no native handler for "
                        + room.GetType().FullName);
            }

            stages.Add(new { stage = "long-path-room", elapsedMs = timer.Elapsed.TotalMilliseconds,
                roomNumber, actIndex = run.CurrentActIndex, floor, roomType = room.GetType().Name,
                encounter, eventId, eventOptions, restOption, treasureRelic, combatDecisions,
                skippedRewards,
                hpBefore, hpAfter = player.Creature.CurrentHp, goldBefore, goldAfter = player.Gold,
                deckBefore, deckAfter = player.Deck.Cards.Count,
                relicsBefore, relicsAfter = player.Relics.Count,
                potionSlotsBefore,
                potionSlotsAfter = player.PotionSlots.Select(potion => potion?.Id.ToString()).ToArray(),
                rewardCards = selector.SelectedRewardCardIds.Skip(rewardChoicesBefore).ToArray(),
                selectedCards = selector.SelectedCardIds.Skip(selectorChoicesBefore)
                    .ToArray(), gameOver = RunManager.Instance.IsGameOver,
                gameSceneLoaded = MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null });
            if (RunManager.Instance.IsGameOver || player.Creature.IsDead)
                break;

            var navigationPoint = run.CurrentMapPoint;
            if (navigationPoint is null && room is MapRoom)
                navigationPoint = run.Map.StartingMapPoint;
            var children = navigationPoint?.Children.ToArray()
                ?? throw new InvalidOperationException("Long-path probe lost its current map point.");
            if (children.Length == 0)
            {
                int completedAct = run.CurrentActIndex;
                if (completedAct + 1 < run.Acts.Count)
                {
                    var transitionTimer = Stopwatch.StartNew();
                    await RunManager.Instance.EnterNextAct().WaitAsync(TimeSpan.FromSeconds(15));
                    if (run.CurrentActIndex != completedAct + 1 || run.CurrentRoom is null)
                        throw new InvalidOperationException("Native act transition did not enter the next act.");
                    stages.Add(new { stage = "long-path-enter-next-act",
                        elapsedMs = transitionTimer.Elapsed.TotalMilliseconds,
                        fromActIndex = completedAct, toActIndex = run.CurrentActIndex,
                        floor = run.TotalFloor, roomType = run.CurrentRoom.GetType().Name,
                        gameSceneLoaded = MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null });
                    continue;
                }

                var victoryTimer = Stopwatch.StartNew();
                await RunManager.Instance.WinRun().WaitAsync(TimeSpan.FromSeconds(15));
                if (!RunManager.Instance.IsGameOver || player.Creature.IsDead)
                    throw new InvalidOperationException("Native final-act completion did not produce a victory terminal.");
                stages.Add(new { stage = "long-path-native-victory",
                    elapsedMs = victoryTimer.Elapsed.TotalMilliseconds,
                    actIndex = run.CurrentActIndex, floor = run.TotalFloor,
                    finalHp = player.Creature.CurrentHp,
                    gameSceneLoaded = MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null });
                break;
            }
            int Priority(MapPoint point) => point.PointType.ToString() switch
            {
                "RestSite" => 0, "Treasure" => 1, "Shop" or "Merchant" => 2,
                "Unknown" => 3, "Monster" => 4, "Elite" => 5, "Boss" => 6, _ => 7,
            };
            var next = children.OrderBy(Priority).ThenBy(point => point.coord.col).First();
            int beforeMoveFloor = run.TotalFloor;
            var moveTimer = Stopwatch.StartNew();
            await RunManager.Instance.EnterMapCoord(next.coord).WaitAsync(TimeSpan.FromSeconds(10));
            if (run.CurrentMapPoint != next || run.TotalFloor <= beforeMoveFloor)
                throw new InvalidOperationException("Long-path native map move did not advance exactly to its child.");
            stages.Add(new { stage = "long-path-move", elapsedMs = moveTimer.Elapsed.TotalMilliseconds,
                fromFloor = beforeMoveFloor, toFloor = run.TotalFloor,
                col = next.coord.col, row = next.coord.row,
                pointType = next.PointType.ToString(), roomType = run.CurrentRoom?.GetType().Name,
                hp = player.Creature.CurrentHp });
        }
        if (!RunManager.Instance.IsGameOver)
            throw new InvalidOperationException("Long-path probe did not reach a native terminal within "
                + maxRooms + " rooms.");
        string outcome = player.Creature.IsDead ? "defeat" : "victory";
        stages.Add(new { stage = "long-path-native-terminal", elapsedMs = wholeTimer.Elapsed.TotalMilliseconds,
            outcome,
            actIndex = run.CurrentActIndex, actFloor = run.ActFloor, totalFloor = run.TotalFloor,
            finalHp = player.Creature.CurrentHp, gameSceneLoaded = MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null });
    }

    private static string[] CompletePendingPotionOverflow(Player player)
    {
        var synchronizer = RunManager.Instance.RewardsSetSynchronizer;
        const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
        var states = synchronizer.GetType().GetField("_rewardStates", flags)?.GetValue(synchronizer)
            as System.Collections.IEnumerable;
        if (states is null) throw new InvalidOperationException("Native reward state is unavailable.");
        var playerState = states.Cast<object>().Single();
        var stack = playerState.GetType().GetField("rewardsStack", flags)?.GetValue(playerState)
            as System.Collections.IList;
        if (stack is null) throw new InvalidOperationException("Native reward stack is unavailable.");
        if (stack.Count == 0) return [];
        var top = stack[stack.Count - 1]
            ?? throw new InvalidOperationException("Native reward stack has a null entry.");
        var rewardSet = top.GetType().GetField("set", flags)?.GetValue(top) as RewardsSet
            ?? throw new InvalidOperationException("Native reward stack has no reward set.");
        var pending = rewardSet.Rewards.Where(reward => !reward.SuccessfullySelected).ToArray();
        if (pending.Length == 0)
            throw new InvalidOperationException("Native reward stack is still open with no pending reward.");
        if (pending.Any(reward => reward is not PotionReward)
            || player.PotionSlots.Any(slot => slot is null))
            throw new InvalidOperationException("Native reward set is incomplete for a reason other than full potion slots: "
                + string.Join(", ", pending.Select(reward => reward.GetType().Name)));
        // The ordinary reward Proceed button skips the remaining reward set.
        // TestMode's automatic Offer path cannot claim a potion with full slots.
        synchronizer.SkipLocalRewardsSet();
        if (!synchronizer.IsRewardsSetCompleted(rewardSet))
            throw new InvalidOperationException("Native potion reward skip did not close the reward set.");
        return pending.Select(reward => reward.GetType().Name).ToArray();
    }

    private static async Task<int> PlayCombatAsync(Node host, CombatRoom room, Player player,
        List<object>? decisionTrace = null, bool usePotions = false)
    {
        await WaitForCombatDecisionAsync(host, room, player, null);
        int decisions = 0;
        var usedPotionSlots = new HashSet<uint>();
        while (!room.IsPreFinished && !player.Creature.IsDead && decisions < 250)
        {
            var state = room.CombatState;
            var actions = CombatCaptureService.GetLegalActions(state);
            if (actions.Count == 0)
                throw new InvalidOperationException("Native combat reached a decision without legal actions.");
            bool shouldUsePotion = usePotions
                && player.Creature.CurrentHp * 2 <= player.Creature.MaxHp;
            var action = shouldUsePotion
                ? GetNativePotionActions(state, player)
                    .FirstOrDefault(candidate => candidate.PotionIndex is { } slot
                        && !usedPotionSlots.Contains(slot))
                : null;
            action ??= actions.FirstOrDefault(candidate => candidate.Kind == CombatActionKind.PlayCard
                && player.PlayerCombatState!.Hand.Cards.Any(card =>
                    NetCombatCard.FromModel(card).CombatCardIndex == candidate.CombatCardIndex
                    && card.Type == CardType.Attack))
                ?? actions.FirstOrDefault(candidate => candidate.Kind == CombatActionKind.PlayCard)
                ?? actions.First(candidate => candidate.Kind == CombatActionKind.EndTurn);
            if (action.Kind == CombatActionKind.UsePotion && action.PotionIndex is { } usedSlot)
                usedPotionSlots.Add(usedSlot);
            if (decisionTrace is not null)
            {
                var combat = player.PlayerCombatState!;
                var selectedCard = action.CombatCardIndex is { } cardIndex
                    ? combat.Hand.Cards.Single(card => NetCombatCard.FromModel(card).CombatCardIndex == cardIndex)
                    : null;
                int? targetEnemyIndex = action.TargetCreatureId is { } targetId
                    ? state.Enemies.ToList().FindIndex(enemy => enemy.CombatId == targetId)
                    : null;
                decisionTrace.Add(new
                {
                    decision = decisions,
                    round = state.RoundNumber,
                    playerHp = player.Creature.CurrentHp,
                    energy = combat.Energy,
                    piles = combat.AllPiles.Select(pile => new
                    {
                        pile = pile.Type.ToString().ToLowerInvariant(),
                        cards = pile.Cards.Select(card => card.Id.ToString())
                            .OrderBy(id => id, StringComparer.Ordinal).ToArray(),
                    }).OrderBy(pile => pile.pile, StringComparer.Ordinal).ToArray(),
                    enemies = state.Enemies.Select(enemy => new
                    {
                        modelId = enemy.ModelId.ToString(), hp = enemy.CurrentHp,
                        block = enemy.Block, alive = enemy.IsAlive,
                    }).ToArray(),
                    action = new
                    {
                        kind = action.Kind.ToString(),
                        cardModelId = selectedCard?.Id.ToString(),
                        potionIndex = action.PotionIndex,
                        targetEnemyIndex,
                    },
                });
            }
            var nativeAction = CombatActionExecutor.CreateGameAction(state, action);
            RunManager.Instance.ActionQueueSet.EnqueueWithoutSynchronizing(nativeAction);
            decisions++;
            await WaitForCombatDecisionAsync(host, room, player, nativeAction);
        }
        if (decisions >= 250)
            throw new TimeoutException("Native combat exceeded 250 decisions.");
        return decisions;
    }

    private static IReadOnlyList<CombatActionDescriptor> GetNativePotionActions(
        CombatState state, Player player)
    {
        if (player.PlayerCombatState?.Phase != PlayerTurnPhase.Play
            || !player.CanUseOrRemovePotions)
            return [];

        var actions = new List<CombatActionDescriptor>();
        for (int slot = 0; slot < player.PotionSlots.Count; slot++)
        {
            var potion = player.PotionSlots[slot];
            if (potion is null || potion.IsQueued || !potion.PassesCustomUsabilityCheck)
                continue;

            bool requiresTarget = potion.TargetType is
                TargetType.AnyEnemy or TargetType.AnyAlly or TargetType.AnyPlayer;
            if (!requiresTarget)
            {
                actions.Add(new CombatActionDescriptor(
                    CombatActionKind.UsePotion, player.NetId,
                    PotionIndex: checked((uint)slot)));
                continue;
            }

            foreach (var target in state.Creatures
                         .Where(target => target.IsAlive)
                         .OrderBy(target => target.CombatId))
            {
                bool isValid;
                try { isValid = potion.IsValidTarget(target); }
                catch { isValid = false; }
                if (isValid && target.CombatId is { } combatId)
                {
                    actions.Add(new CombatActionDescriptor(
                        CombatActionKind.UsePotion, player.NetId,
                        PotionIndex: checked((uint)slot), TargetCreatureId: combatId));
                }
            }
        }
        return actions;
    }

    private static async Task ProbeOutsideRouteAsync(Node host, RunState run, Player player,
        AutoProbeCardSelector selector, List<object> stages, Stopwatch wholeTimer, string route)
    {
        var start = run.CurrentMapPoint
            ?? throw new InvalidOperationException("Native run has no starting map point.");
        var queue = new Queue<MapPoint>();
        var parents = new Dictionary<MapPoint, MapPoint?> { [start] = null };
        queue.Enqueue(start);
        while (queue.Count > 0)
        {
            var point = queue.Dequeue();
            foreach (var child in point.Children)
                if (parents.TryAdd(child, point)) queue.Enqueue(child);
        }
        var targetType = route == "shop" ? "Shop" : "RestSite";
        var target = parents.Keys.Where(point => point.PointType.ToString() == targetType)
            .OrderBy(point => point.coord.row).ThenBy(point => point.coord.col).FirstOrDefault()
            ?? throw new InvalidOperationException("Generated map has no reachable " + targetType + ".");
        var path = new List<MapPoint>();
        for (MapPoint? point = target; point is not null; point = parents[point]) path.Add(point);
        path.Reverse();
        stages.Add(new { stage = route + "-route", path = path.Select(point => new
            { col = point.coord.col, row = point.coord.row, type = point.PointType.ToString() }).ToArray() });

        foreach (var next in path.Skip(1))
        {
            var timer = Stopwatch.StartNew();
            await RunManager.Instance.EnterMapCoord(next.coord).WaitAsync(TimeSpan.FromSeconds(10));
            stages.Add(new { stage = route + "-route-enter", elapsedMs = timer.Elapsed.TotalMilliseconds,
                col = next.coord.col, row = next.coord.row, type = next.PointType.ToString(),
                roomType = run.CurrentRoom?.GetType().Name, hp = player.Creature.CurrentHp,
                state = DescribeRun(run), roomMembers = DescribeMembers(run.CurrentRoom) });
            if (run.CurrentRoom is not CombatRoom combatRoom) continue;

            timer.Restart();
            int decisions = await PlayCombatAsync(host, combatRoom, player);
            stages.Add(new { stage = route + "-route-combat", elapsedMs = timer.Elapsed.TotalMilliseconds,
                encounter = combatRoom.Encounter.Id.Entry, decisions,
                hp = player.Creature.CurrentHp, victory = combatRoom.IsPreFinished && !player.Creature.IsDead });
            if (player.Creature.IsDead)
                throw new InvalidOperationException("Pinned " + route + " route ended in native defeat before the target.");
            if (!combatRoom.IsPreFinished)
                throw new InvalidOperationException("Pinned " + route + " route combat did not finish.");
            timer.Restart();
            int deckBefore = player.Deck.Cards.Count;
            int rewardChoicesBefore = selector.SelectedRewardCardIds.Count;
            await combatRoom.OfferRoomEndRewards().WaitAsync(TimeSpan.FromSeconds(10));
            int rewardChoices = selector.SelectedRewardCardIds.Count - rewardChoicesBefore;
            if (player.Deck.Cards.Count != deckBefore + rewardChoices)
                throw new InvalidOperationException(route + " route native combat reward did not update the deck.");
            stages.Add(new { stage = route + "-route-rewards", elapsedMs = timer.Elapsed.TotalMilliseconds,
                deckBefore, deckAfter = player.Deck.Cards.Count,
                gold = player.Gold, hp = player.Creature.CurrentHp,
                rewardCardSelections = selector.SelectedRewardCardIds.Skip(rewardChoicesBefore).ToArray() });
        }
        if (route == "rest")
        {
            if (run.CurrentMapPoint != target || run.CurrentRoom is not RestSiteRoom restRoom)
                throw new InvalidOperationException("Pinned route did not reach the native rest site room.");
            stages.Add(new { stage = "rest-arrived", elapsedMs = wholeTimer.Elapsed.TotalMilliseconds,
                hp = player.Creature.CurrentHp, maxHp = player.Creature.MaxHp,
                gameSceneLoaded = MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null,
                roomMembers = DescribeMembers(restRoom),
                synchronizerMembers = DescribeMembers(RunManager.Instance.RestSiteSynchronizer),
                roomUiMethods = typeof(NRestSiteRoom).GetMethods(BindingFlags.Instance
                    | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly)
                    .Where(method => !method.IsSpecialName).Select(method => method.Name).ToArray(),
                buttonUiMethods = typeof(NRestSiteButton).GetMethods(BindingFlags.Instance
                    | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly)
                    .Where(method => !method.IsSpecialName).Select(method => method.Name).ToArray(),
                buttonSelectionCalls = DescribeAsyncCalls(typeof(NRestSiteButton), "SelectOption"),
                afterSelectionCalls = DescribeAsyncCalls(typeof(NRestSiteRoom), "AfterSelectingOptionAsync"),
                proceedCalls = DescribeAsyncCalls(typeof(NRestSiteRoom), "OnProceedButtonReleased"),
                options = restRoom.Options.Select(option => new
                {
                    type = option.GetType().Name, members = DescribeMembers(option),
                }).ToArray() });
            var healOption = restRoom.Options.FirstOrDefault(option =>
                option.GetType().Name == "HealRestSiteOption" && option.IsEnabled)
                ?? throw new InvalidOperationException("Native rest site has no enabled heal option.");
            int healOptionIndex = restRoom.Options.ToList().IndexOf(healOption);
            int hpBeforeRest = player.Creature.CurrentHp;
            var restTimer = Stopwatch.StartNew();
            bool rested = await RunManager.Instance.RestSiteSynchronizer
                .ChooseLocalOption(healOptionIndex).WaitAsync(TimeSpan.FromSeconds(10));
            stages.Add(new { stage = "rest-heal", elapsedMs = restTimer.Elapsed.TotalMilliseconds,
                rested, healOptionIndex, hpBeforeRest, hpAfterRest = player.Creature.CurrentHp,
                roomPreFinished = restRoom.IsPreFinished,
                chosenOptionIndex = RunManager.Instance.RestSiteSynchronizer.GetChosenOptionIndex(1UL),
                optionsAfter = restRoom.Options.Select(option => new
                    { option.OptionId, option.IsEnabled }).ToArray() });
            if (!rested || player.Creature.CurrentHp <= hpBeforeRest
                || player.Creature.CurrentHp > player.Creature.MaxHp)
                throw new InvalidOperationException("Native rest site heal did not update HP.");
            var afterRestPoint = run.CurrentMapPoint?.Children
                .OrderBy(point => point.coord.col).FirstOrDefault()
                ?? throw new InvalidOperationException("Native rest site has no next map point.");
            var moveTimer = Stopwatch.StartNew();
            await RunManager.Instance.EnterMapCoord(afterRestPoint.coord)
                .WaitAsync(TimeSpan.FromSeconds(10));
            stages.Add(new { stage = "after-rest-map-enter", elapsedMs = moveTimer.Elapsed.TotalMilliseconds,
                col = afterRestPoint.coord.col, row = afterRestPoint.coord.row,
                pointType = afterRestPoint.PointType.ToString(),
                roomType = run.CurrentRoom?.GetType().Name, hp = player.Creature.CurrentHp,
                state = DescribeRun(run) });
            if (run.CurrentMapPoint != afterRestPoint)
                throw new InvalidOperationException("Native rest site did not advance to its next map point.");
            var afterRestCombat = run.CurrentRoom as CombatRoom
                ?? throw new InvalidOperationException("Pinned post-rest point is not a native combat room.");
            var nextCombatTimer = Stopwatch.StartNew();
            int postRestDecisions = await PlayCombatAsync(host, afterRestCombat, player);
            stages.Add(new { stage = "after-rest-combat", elapsedMs = nextCombatTimer.Elapsed.TotalMilliseconds,
                encounter = afterRestCombat.Encounter.Id.Entry, postRestDecisions,
                hp = player.Creature.CurrentHp, victory = afterRestCombat.IsPreFinished && !player.Creature.IsDead });
            if (!afterRestCombat.IsPreFinished || player.Creature.IsDead)
                throw new InvalidOperationException("Pinned post-rest combat did not end in victory.");
            int deckBeforePostRestRewards = player.Deck.Cards.Count;
            int rewardChoicesBeforePostRest = selector.SelectedRewardCardIds.Count;
            await afterRestCombat.OfferRoomEndRewards().WaitAsync(TimeSpan.FromSeconds(10));
            int addedPostRestCards = selector.SelectedRewardCardIds.Count - rewardChoicesBeforePostRest;
            if (player.Deck.Cards.Count != deckBeforePostRestRewards + addedPostRestCards)
                throw new InvalidOperationException("Post-rest combat rewards did not update the deck.");
            stages.Add(new { stage = "after-rest-rewards", deckBeforePostRestRewards,
                deckAfterRewards = player.Deck.Cards.Count, gold = player.Gold,
                rewardCardSelections = selector.SelectedRewardCardIds.Skip(rewardChoicesBeforePostRest).ToArray() });

            var secondRestPoint = run.CurrentMapPoint?.Children
                .FirstOrDefault(point => point.PointType.ToString() == "RestSite")
                ?? throw new InvalidOperationException("Pinned post-rest combat has no rest site child.");
            await RunManager.Instance.EnterMapCoord(secondRestPoint.coord).WaitAsync(TimeSpan.FromSeconds(10));
            var secondRestRoom = run.CurrentRoom as RestSiteRoom
                ?? throw new InvalidOperationException("Pinned second rest site did not open a native room.");
            stages.Add(new { stage = "second-rest-arrived", hp = player.Creature.CurrentHp,
                col = secondRestPoint.coord.col, row = secondRestPoint.coord.row,
                options = secondRestRoom.Options.Select(option => new
                    { option.OptionId, option.IsEnabled }).ToArray() });
            var secondHeal = secondRestRoom.Options.FirstOrDefault(option =>
                option.GetType().Name == "HealRestSiteOption" && option.IsEnabled)
                ?? throw new InvalidOperationException("Second rest site has no enabled heal option.");
            int secondRestHpBefore = player.Creature.CurrentHp;
            int secondHealIndex = secondRestRoom.Options.ToList().IndexOf(secondHeal);
            bool secondRested = await RunManager.Instance.RestSiteSynchronizer
                .ChooseLocalOption(secondHealIndex).WaitAsync(TimeSpan.FromSeconds(10));
            stages.Add(new { stage = "second-rest-heal", secondRested, secondRestHpBefore,
                hpAfterRest = player.Creature.CurrentHp,
                chosenOptionIndex = RunManager.Instance.RestSiteSynchronizer.GetChosenOptionIndex(1UL) });
            if (!secondRested || player.Creature.CurrentHp <= secondRestHpBefore)
                throw new InvalidOperationException("Second native rest site heal did not update HP.");

            var treasurePoint = run.CurrentMapPoint?.Children
                .FirstOrDefault(point => point.PointType.ToString() == "Treasure")
                ?? throw new InvalidOperationException("Pinned second rest site has no treasure child.");
            var treasureTimer = Stopwatch.StartNew();
            await RunManager.Instance.EnterMapCoord(treasurePoint.coord).WaitAsync(TimeSpan.FromSeconds(10));
            stages.Add(new { stage = "treasure-arrived", elapsedMs = treasureTimer.Elapsed.TotalMilliseconds,
                col = treasurePoint.coord.col, row = treasurePoint.coord.row,
                roomType = run.CurrentRoom?.GetType().Name,
                hp = player.Creature.CurrentHp, relics = player.Relics.Select(relic => relic.Id.Entry).ToArray(),
                roomMembers = DescribeMembers(run.CurrentRoom),
                treasureUiMethods = typeof(NTreasureRoom).GetMethods(BindingFlags.Instance
                    | BindingFlags.Public | BindingFlags.NonPublic | BindingFlags.DeclaredOnly)
                    .Where(method => !method.IsSpecialName).Select(method => method.Name).ToArray(),
                chestButtonCalls = DescribeAsyncCalls(typeof(NTreasureRoom), "OnChestButtonReleased"),
                openChestCalls = DescribeAsyncCalls(typeof(NTreasureRoom), "OpenChest"),
                collectionPickingCalls = DescribeAsyncCalls(typeof(NTreasureRoomRelicCollection), "RelicPickingBegan"),
                collectionFinishedCalls = DescribeAsyncCalls(typeof(NTreasureRoomRelicCollection), "RelicPickingFinished"),
                collectionUiMethods = typeof(NTreasureRoomRelicCollection)
                    .GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic
                        | BindingFlags.DeclaredOnly)
                    .Where(method => !method.IsSpecialName).Select(method => method.Name).ToArray(),
                collectionPickCalls = DescribeAsyncCalls(typeof(NTreasureRoomRelicCollection), "PickRelic"),
                collectionAwardCalls = DescribeAsyncCalls(typeof(NTreasureRoomRelicCollection), "OnRelicsAwarded"),
                collectionAnimateAwardCalls = DescribeAsyncCalls(typeof(NTreasureRoomRelicCollection), "AnimateRelicAwards"),
                relicObtainMethods = typeof(RelicCmd).GetMethods(BindingFlags.Static
                    | BindingFlags.Public | BindingFlags.NonPublic)
                    .Where(method => method.Name == "Obtain").Select(method => method.ToString()).ToArray(),
                pickActionMethods = typeof(PickRelicAction)
                    .GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic
                        | BindingFlags.DeclaredOnly)
                    .Where(method => !method.IsSpecialName).Select(method => method.Name).ToArray(),
                pickActionCalls = DescribeAsyncCalls(typeof(PickRelicAction), "ExecuteAction"),
                synchronizerPickCalls = DescribeAsyncCalls(typeof(TreasureRoomRelicSynchronizer), "PickRelicLocally"),
                synchronizerOnPickedCalls = DescribeAsyncCalls(typeof(TreasureRoomRelicSynchronizer), "OnPicked"),
                synchronizerEndCalls = DescribeAsyncCalls(typeof(TreasureRoomRelicSynchronizer), "EndRelicVoting"),
                synchronizerAwardCalls = DescribeAsyncCalls(typeof(TreasureRoomRelicSynchronizer), "AwardRelics"),
                relicSynchronizerMembers = DescribeMembers(
                    RunManager.Instance.TreasureRoomRelicSynchronizer),
                relicSynchronizerProperties = RunManager.Instance.GetType()
                    .GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                    .Where(property => property.Name.Contains("Treasure", StringComparison.OrdinalIgnoreCase))
                    .Select(property => property.PropertyType.Name + " " + property.Name).ToArray(),
                gameSceneLoaded = MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null });
            var treasureRoom = run.CurrentRoom as TreasureRoom
                ?? throw new InvalidOperationException("Pinned treasure point did not create a native treasure room.");
            var relicSynchronizer = RunManager.Instance.TreasureRoomRelicSynchronizer;
            int relicsBeforeTreasure = player.Relics.Count;
            var chestTimer = Stopwatch.StartNew();
            var normalRewards = await InvokeNativeTaskAsync(treasureRoom, "DoNormalRewards");
            await InvokeNativeTaskAsync(treasureRoom, "DoExtraRewardsIfNeeded");
            stages.Add(new { stage = "treasure-open-native-rewards",
                elapsedMs = chestTimer.Elapsed.TotalMilliseconds,
                normalRewardType = normalRewards?.GetType().FullName,
                normalRewardText = normalRewards?.ToString(),
                relicsBeforeTreasure, relicsAfterRewards = player.Relics.Count,
                currentRelicIds = relicSynchronizer.CurrentRelics?.Select(relic => relic.Id.Entry).ToArray() });
            var offeredRelics = relicSynchronizer.CurrentRelics?.ToArray()
                ?? throw new InvalidOperationException("Native treasure produced no relic candidates.");
            if (offeredRelics.Length == 0)
                throw new InvalidOperationException("Native treasure produced an empty relic candidate list.");
            object? awardResult = null;
            relicSynchronizer.RelicsAwarded += result => awardResult = result;
            var pickTimer = Stopwatch.StartNew();
            relicSynchronizer.PickRelicLocally(0);
            while (awardResult is null
                && pickTimer.Elapsed < TimeSpan.FromSeconds(2))
                await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
            stages.Add(new { stage = "treasure-relic-picked",
                elapsedMs = pickTimer.Elapsed.TotalMilliseconds,
                offeredRelicIds = offeredRelics.Select(relic => relic.Id.Entry).ToArray(),
                relicsBeforeTreasure, relicsAfterPick = player.Relics.Count,
                ownedRelicIds = player.Relics.Select(relic => relic.Id.Entry).ToArray(),
                vote = DescribeMembers(relicSynchronizer.GetPlayerVote(player)),
                awardResult = DescribeMembers(awardResult),
                awardEntries = awardResult is System.Collections.IEnumerable awarded
                    ? awarded.Cast<object>().Select(DescribeMembers).ToArray() : null,
                actionExecutorRunning = RunManager.Instance.ActionExecutor.IsRunning,
                actionQueueIdle = RunManager.Instance.ActionExecutor.FinishedExecutingActions().IsCompleted,
                roomPreFinished = treasureRoom.IsPreFinished });
            if (awardResult is not System.Collections.IEnumerable awardedResults)
                throw new InvalidOperationException("Native treasure synchronizer did not emit an award result.");
            var award = awardedResults.Cast<object>().Single();
            const BindingFlags awardFields = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
            var awardedRelic = award.GetType().GetField("relic", awardFields)?.GetValue(award) as RelicModel
                ?? throw new InvalidOperationException("Native treasure award did not name a relic.");
            var awardedPlayer = award.GetType().GetField("player", awardFields)?.GetValue(award) as Player
                ?? throw new InvalidOperationException("Native treasure award did not name a player.");
            var awardType = award.GetType().GetField("type", awardFields)?.GetValue(award)?.ToString();
            var fight = award.GetType().GetField("fight", awardFields)?.GetValue(award);
            if (!ReferenceEquals(awardedPlayer, player) || fight is not null
                || !offeredRelics.Any(relic => relic.Id == awardedRelic.Id)
                || player.Relics.Count != relicsBeforeTreasure)
                throw new InvalidOperationException("Native treasure award did not match the pinned player and offered relic.");
            var obtainTimer = Stopwatch.StartNew();
            var obtainedRelic = await RelicCmd.Obtain(awardedRelic.ToMutable(), awardedPlayer, 0)
                .WaitAsync(TimeSpan.FromSeconds(10));
            stages.Add(new { stage = "treasure-relic-obtained",
                elapsedMs = obtainTimer.Elapsed.TotalMilliseconds, awardType,
                awardedRelicId = awardedRelic.Id.Entry,
                obtainedRelicId = obtainedRelic.Id.Entry,
                relicsBeforeTreasure, relicsAfterObtain = player.Relics.Count,
                roomPreFinished = treasureRoom.IsPreFinished });
            if (player.Relics.Count != relicsBeforeTreasure + 1
                || !player.Relics.Any(relic => relic.Id == awardedRelic.Id))
                throw new InvalidOperationException("Native treasure relic obtain did not update the player.");
            var afterTreasurePoint = run.CurrentMapPoint?.Children
                .OrderBy(point => point.coord.col).FirstOrDefault()
                ?? throw new InvalidOperationException("Pinned treasure room has no next map point.");
            var afterTreasureTimer = Stopwatch.StartNew();
            await RunManager.Instance.EnterMapCoord(afterTreasurePoint.coord)
                .WaitAsync(TimeSpan.FromSeconds(10));
            stages.Add(new { stage = "after-treasure-map-enter",
                elapsedMs = afterTreasureTimer.Elapsed.TotalMilliseconds,
                col = afterTreasurePoint.coord.col, row = afterTreasurePoint.coord.row,
                pointType = afterTreasurePoint.PointType.ToString(),
                roomType = run.CurrentRoom?.GetType().Name,
                relicIds = player.Relics.Select(relic => relic.Id.Entry).ToArray(),
                gameSceneLoaded = MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null });
            if (run.CurrentMapPoint != afterTreasurePoint)
                throw new InvalidOperationException("Native treasure room did not advance to its next map point.");
            return;
        }
        if (run.CurrentMapPoint != target || run.CurrentRoom is not MerchantRoom merchantRoom)
            throw new InvalidOperationException("Pinned route did not reach the native shop room.");
        var inventory = merchantRoom.GetLocalInventory();
        stages.Add(new { stage = "shop-arrived", elapsedMs = wholeTimer.Elapsed.TotalMilliseconds,
            hp = player.Creature.CurrentHp, gold = player.Gold,
            potionSlots = player.PotionSlots.Count,
            occupiedPotionSlots = player.PotionSlots.Count(potion => potion is not null),
            gameSceneLoaded = MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null,
            removalUiCalls = DescribeAsyncCalls(typeof(NMerchantCardRemoval), "OnSelected"),
            removalPurchaseUiCalls = DescribeAsyncCalls(typeof(NMerchantCardRemoval), "OnTryPurchase"),
            basePurchaseUiCalls = DescribeAsyncCalls(typeof(NMerchantSlot), "OnTryPurchase"),
            removalWrapperCalls = DescribeAsyncCalls(typeof(MerchantCardRemovalEntry), "OnTryPurchaseWrapper"),
            removalEntryCalls = DescribeAsyncCalls(typeof(MerchantCardRemovalEntry), "OnTryPurchase", 2),
            removalEntryCoreCalls = DescribeAsyncCalls(typeof(MerchantCardRemovalEntry), "OnTryPurchase", 3),
            cardRemovalUsedUiCalls = DescribeAsyncCalls(typeof(NMerchantInventory), "OnCardRemovalUsed"),
            removalSlotUsedUiCalls = DescribeAsyncCalls(typeof(NMerchantCardRemoval), "OnCardRemovalUsed"),
            roomMembers = DescribeMembers(merchantRoom), inventoryMembers = DescribeMembers(inventory),
            entries = inventory.AllEntries.Select(entry => new
            {
                type = entry.GetType().Name, entry.Cost, entry.IsStocked, entry.EnoughGold,
                members = DescribeMembers(entry),
            }).ToArray() });

        var cardOffer = inventory.AllEntries.OfType<MerchantCardEntry>()
            .Where(entry => entry.IsStocked && entry.EnoughGold)
            .OrderBy(entry => entry.Cost).FirstOrDefault()
            ?? throw new InvalidOperationException("Native shop has no affordable card offer.");
        int goldBeforeCard = player.Gold;
        int deckBeforeCard = player.Deck.Cards.Count;
        int cardCost = cardOffer.Cost;
        var cardTimer = Stopwatch.StartNew();
        bool cardPurchased = await cardOffer.OnTryPurchaseWrapper(inventory, ignoreCost: false)
            .WaitAsync(TimeSpan.FromSeconds(10));
        stages.Add(new { stage = "shop-card-purchase", elapsedMs = cardTimer.Elapsed.TotalMilliseconds,
            cardPurchased, cardCost, goldBeforeCard, goldAfterCard = player.Gold,
            deckBeforeCard, deckAfterCard = player.Deck.Cards.Count,
            offerStocked = cardOffer.IsStocked });
        if (!cardPurchased || player.Gold != goldBeforeCard - cardCost
            || player.Deck.Cards.Count != deckBeforeCard + 1)
            throw new InvalidOperationException("Native shop card purchase did not update gold and deck.");

        var removalOffer = inventory.AllEntries.OfType<MerchantCardRemovalEntry>()
            .SingleOrDefault(entry => entry.IsStocked && entry.EnoughGold)
            ?? throw new InvalidOperationException("Native shop has no affordable card removal service.");
        int goldBeforeRemoval = player.Gold;
        int deckBeforeRemoval = player.Deck.Cards.Count;
        int removalCost = removalOffer.Cost;
        int selectionsBeforeRemoval = selector.SelectedCardModels.Count;
        var removalTimer = Stopwatch.StartNew();
        bool removalPurchased = await removalOffer.OnTryPurchaseWrapper(
            inventory, ignoreCost: false, cancelable: true).WaitAsync(TimeSpan.FromSeconds(10));
        var removedCards = selector.SelectedCardModels.Skip(selectionsBeforeRemoval).ToArray();
        stages.Add(new { stage = "shop-card-removal", elapsedMs = removalTimer.Elapsed.TotalMilliseconds,
            removalPurchased, removalCost, goldBeforeRemoval, goldAfterRemoval = player.Gold,
            deckBeforeRemoval, deckAfterRemoval = player.Deck.Cards.Count,
            removedCardIds = removedCards.Select(card => card.Id.Entry).ToArray(),
            removedCardsStillInDeck = removedCards.Select(selected =>
                player.Deck.Cards.Any(card => ReferenceEquals(card, selected))).ToArray(),
            serviceUsed = removalOffer.Used });
        if (!removalPurchased || player.Gold != goldBeforeRemoval - removalCost
            || player.Deck.Cards.Count != deckBeforeRemoval - 1 || removedCards.Length != 1
            || player.Deck.Cards.Any(card => ReferenceEquals(card, removedCards[0])))
            throw new InvalidOperationException("Native shop card removal did not update gold and deck.");
        // Normal NMerchantCardRemoval.OnCardRemovalUsed calls this after the
        // native purchase succeeds. Without NRun, that UI callback is absent.
        if (!removalOffer.Used) removalOffer.SetUsed();
        stages.Add(new { stage = "shop-card-removal-finalized", serviceUsed = removalOffer.Used,
            removalOfferStocked = removalOffer.IsStocked });
        if (!removalOffer.Used)
            throw new InvalidOperationException("Native shop card removal service was not marked used.");

        var potionOffer = inventory.AllEntries.OfType<MerchantPotionEntry>()
            .Where(entry => entry.IsStocked && entry.EnoughGold)
            .OrderBy(entry => entry.Cost).FirstOrDefault()
            ?? throw new InvalidOperationException("Native shop has no affordable potion offer.");
        int goldBeforePotion = player.Gold;
        int potionsBeforePurchase = player.PotionSlots.Count(potion => potion is not null);
        int potionCost = potionOffer.Cost;
        var potionTimer = Stopwatch.StartNew();
        bool potionPurchased = await potionOffer.OnTryPurchaseWrapper(inventory, ignoreCost: false)
            .WaitAsync(TimeSpan.FromSeconds(10));
        stages.Add(new { stage = "shop-potion-purchase", elapsedMs = potionTimer.Elapsed.TotalMilliseconds,
            potionPurchased, potionCost, goldBeforePotion, goldAfterPotion = player.Gold,
            potionsBeforePurchase, potionsAfterPurchase = player.PotionSlots.Count(potion => potion is not null),
            offerStocked = potionOffer.IsStocked });
        int potionsAfterPurchase = player.PotionSlots.Count(potion => potion is not null);
        bool hadFreePotionSlot = potionsBeforePurchase < player.PotionSlots.Count;
        if (hadFreePotionSlot
            ? !potionPurchased || player.Gold != goldBeforePotion - potionCost
                || potionsAfterPurchase != potionsBeforePurchase + 1
            : potionPurchased || player.Gold != goldBeforePotion
                || potionsAfterPurchase != potionsBeforePurchase)
            throw new InvalidOperationException("Native shop potion purchase had an unexpected outcome.");

        var afterShopPoint = run.CurrentMapPoint?.Children
            .OrderBy(point => point.coord.col).FirstOrDefault()
            ?? throw new InvalidOperationException("Pinned shop room has no next map point.");
        var afterShopTimer = Stopwatch.StartNew();
        await RunManager.Instance.EnterMapCoord(afterShopPoint.coord)
            .WaitAsync(TimeSpan.FromSeconds(10));
        stages.Add(new { stage = "after-shop-map-enter",
            elapsedMs = afterShopTimer.Elapsed.TotalMilliseconds,
            col = afterShopPoint.coord.col, row = afterShopPoint.coord.row,
            pointType = afterShopPoint.PointType.ToString(),
            roomType = run.CurrentRoom?.GetType().Name,
            hp = player.Creature.CurrentHp, gold = player.Gold,
            deckSize = player.Deck.Cards.Count,
            gameSceneLoaded = MegaCrit.Sts2.Core.Nodes.NGame.Instance is not null });
        if (run.CurrentMapPoint != afterShopPoint)
            throw new InvalidOperationException("Native shop room did not advance to its next map point.");
    }

    private static async Task WaitForCombatDecisionAsync(
        Node host, CombatRoom room, Player player, GameAction? lastAction)
    {
        var deadline = Stopwatch.StartNew();
        while (true)
        {
            if (lastAction?.Exception is { } actionError)
                throw new InvalidOperationException("Native combat action failed.", actionError);
            var executor = RunManager.Instance.ActionExecutor;
            if (executor.FinishedExecutingActions().Exception is { } queueError)
                throw new InvalidOperationException("Native combat action queue failed.", queueError);
            if ((room.IsPreFinished || player.Creature.IsDead) && !executor.IsRunning)
                return;
            if (player.PlayerCombatState?.Phase == PlayerTurnPhase.Play
                && !CombatManager.Instance.PlayerActionsDisabled
                && !executor.IsRunning
                && (lastAction is null || lastAction.CompletionTask.IsCompleted)
                && !CombatManager.Instance.IsPlayerReadyToEndTurn(player))
                return;
            if (deadline.Elapsed > TimeSpan.FromSeconds(10))
                throw new TimeoutException("Native combat did not reach the next decision.");
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
        }
    }

    private static object DescribeRun(RunState run)
    {
        var values = new Dictionary<string, string?>();
        foreach (var property in run.GetType().GetProperties(BindingFlags.Instance | BindingFlags.Public)
                     .Where(property => property.GetIndexParameters().Length == 0
                         && new[] { "Act", "Map", "Room", "Floor" }.Any(token =>
                             property.Name.Contains(token, StringComparison.OrdinalIgnoreCase))))
        {
            try
            {
                var value = property.GetValue(run);
                values[property.Name] = value is null ? null : value.GetType().Name + ":" + value;
            }
            catch (Exception exception) { values[property.Name] = "error:" + exception.GetType().Name; }
        }
        return values;
    }

    private static object[] DescribeFutureMap(MegaCrit.Sts2.Core.Map.MapPoint? start)
    {
        if (start is null) return [];
        var queue = new Queue<MegaCrit.Sts2.Core.Map.MapPoint>();
        var seen = new HashSet<MegaCrit.Sts2.Core.Map.MapPoint>();
        queue.Enqueue(start);
        seen.Add(start);
        var points = new List<object>();
        while (queue.Count > 0)
        {
            var point = queue.Dequeue();
            points.Add(new { col = point.coord.col, row = point.coord.row,
                type = point.PointType.ToString(),
                children = point.Children.Select(child => new { col = child.coord.col,
                    row = child.coord.row, type = child.PointType.ToString() }).ToArray() });
            foreach (var child in point.Children)
                if (seen.Add(child)) queue.Enqueue(child);
        }
        return points.ToArray();
    }

    private static object? DescribeMembers(object? target)
    {
        if (target is null) return null;
        var type = target.GetType();
        return new
        {
            type = type.FullName,
            properties = type.GetProperties(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                .Select(property => property.PropertyType.Name + " " + property.Name).ToArray(),
            fields = type.GetFields(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                .Where(field => field.DeclaringType == type)
                .Select(field => new { name = field.Name, type = field.FieldType.Name,
                    value = field.FieldType.IsPrimitive || field.FieldType == typeof(string)
                        ? field.GetValue(target)?.ToString() : field.GetValue(target)?.GetType().Name })
                .ToArray(),
            methods = type.GetMethods(BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic)
                .Where(method => method.DeclaringType == type && !method.IsSpecialName)
                .Select(method => method.ReturnType.Name + " " + method.Name + "("
                    + string.Join(", ", method.GetParameters().Select(parameter => parameter.ParameterType.Name)) + ")")
                .ToArray(),
        };
    }

    internal static string[] DescribeAsyncCalls(Type type, string methodName, int? parameterCount = null)
    {
        const BindingFlags flags = BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic;
        MethodInfo? method = null;
        for (Type? current = type; current is not null && method is null; current = current.BaseType)
            method = current.GetMethods(flags | BindingFlags.DeclaredOnly)
                .FirstOrDefault(candidate => candidate.Name == methodName
                    && (parameterCount is null || candidate.GetParameters().Length == parameterCount));
        if (method is null) return ["method-not-found"];
        var stateMachine = method.GetCustomAttribute<AsyncStateMachineAttribute>()?.StateMachineType;
        var bodyMethod = stateMachine?.GetMethod("MoveNext", flags) ?? method;
        var il = bodyMethod.GetMethodBody()?.GetILAsByteArray();
        if (il is null) return ["method-body-not-found"];
        var opcodes = typeof(OpCodes).GetFields(BindingFlags.Public | BindingFlags.Static)
            .Select(field => field.GetValue(null)).OfType<OpCode>()
            .ToDictionary(opcode => unchecked((ushort)opcode.Value));
        var calls = new List<string>();
        int offset = 0;
        while (offset < il.Length)
        {
            ushort value = il[offset++];
            if (value == 0xfe && offset < il.Length) value = (ushort)(0xfe00 | il[offset++]);
            if (!opcodes.TryGetValue(value, out var opcode)) break;
            int operandOffset = offset;
            int operandLength = opcode.OperandType switch
            {
                OperandType.InlineNone => 0,
                OperandType.ShortInlineI or OperandType.ShortInlineVar
                    or OperandType.ShortInlineBrTarget => 1,
                OperandType.InlineVar => 2,
                OperandType.InlineI or OperandType.InlineBrTarget or OperandType.ShortInlineR
                    or OperandType.InlineField or OperandType.InlineMethod or OperandType.InlineSig
                    or OperandType.InlineString or OperandType.InlineTok or OperandType.InlineType => 4,
                OperandType.InlineI8 or OperandType.InlineR => 8,
                OperandType.InlineSwitch when operandOffset + 4 <= il.Length
                    => 4 + 4 * BitConverter.ToInt32(il, operandOffset),
                _ => 0,
            };
            if (operandLength < 0 || operandOffset + operandLength > il.Length) break;
            if (opcode.OperandType == OperandType.InlineMethod
                && opcode.Name is "call" or "callvirt" or "newobj")
            {
                int token = BitConverter.ToInt32(il, operandOffset);
                try
                {
                    var target = bodyMethod.Module.ResolveMethod(token,
                        bodyMethod.DeclaringType?.GetGenericArguments(), bodyMethod.GetGenericArguments());
                    calls.Add(target?.DeclaringType?.Name + "." + target?.Name);
                }
                catch { calls.Add("unresolved-token:" + token); }
            }
            offset += operandLength;
        }
        return calls.ToArray();
    }

    private static async Task<object?> InvokeNativeTaskAsync(object target, string methodName)
    {
        var method = target.GetType().GetMethod(methodName,
            BindingFlags.Instance | BindingFlags.Public | BindingFlags.NonPublic,
            binder: null, types: Type.EmptyTypes, modifiers: null)
            ?? throw new InvalidOperationException("Native method not found: " + methodName);
        if (method.Invoke(target, null) is not Task operation)
            throw new InvalidOperationException("Native method did not return Task: " + methodName);
        await operation.WaitAsync(TimeSpan.FromSeconds(10));
        return operation.GetType().GetProperty("Result")?.GetValue(operation);
    }
}

internal sealed record ProbeCardSelectionIdentity(
    string ModelId,
    int UpgradeLevel,
    string EnchantmentId,
    int Ordinal);

internal sealed class AutoProbeCardSelector : ICardSelector
{
    internal const string SkipRewardSelection = "__STM_SKIP_REWARD__";
    public Queue<string[]> ForcedCardModelSelections { get; } = new();
    public Queue<IReadOnlyList<ProbeCardSelectionIdentity>> ForcedCardIdentitySelections { get; } = new();
    public Queue<IReadOnlyList<CardModel>> ForcedExactCardSelections { get; } = new();
    public Queue<string> ForcedRewardCardModelSelections { get; } = new();
    public List<string> SelectedCardIds { get; } = [];
    public List<CardModel> SelectedCardModels { get; } = [];
    public List<string> SelectedRewardCardIds { get; } = [];
    public List<string[]> RewardCandidateIds { get; } = [];
    public List<ProbeCardSelectionOffer> SelectionOffers { get; } = [];

    public Task<IEnumerable<CardModel>> GetSelectedCards(IEnumerable<CardModel> options, int minSelect, int maxSelect)
    {
        var candidates = options.ToArray();
        if (minSelect > candidates.Length || minSelect > maxSelect)
            throw new InvalidOperationException("Native card selector has impossible bounds.");
        SelectionOffers.Add(new ProbeCardSelectionOffer(candidates.Select(card => card.Id.ToString()).ToArray(),
            minSelect, maxSelect));
        CardModel[] chosen;
        if (ForcedExactCardSelections.Count > 0)
        {
            chosen = ForcedExactCardSelections.Dequeue().ToArray();
            if (chosen.Length < minSelect || chosen.Length > maxSelect
                || chosen.Distinct(ReferenceEqualityComparer.Instance).Count() != chosen.Length
                || chosen.Any(card => !candidates.Any(candidate => ReferenceEquals(candidate, card))))
                throw new InvalidOperationException("Recorded exact card selection is absent from native candidates.");
        }
        else if (ForcedCardIdentitySelections.Count > 0)
        {
            var identities = ForcedCardIdentitySelections.Dequeue();
            if (identities.Count < minSelect || identities.Count > maxSelect)
                throw new InvalidOperationException("Recorded card identity selection violates native bounds.");
            chosen = identities.Select(identity => candidates.Where(candidate =>
                    (candidate.Id.ToString() == identity.ModelId || candidate.Id.Entry == identity.ModelId)
                    && candidate.CurrentUpgradeLevel == identity.UpgradeLevel
                    && (candidate.Enchantment?.Id.ToString() ?? "") == identity.EnchantmentId)
                .Skip(identity.Ordinal).FirstOrDefault()
                ?? throw new InvalidOperationException("Recorded card identity selection is not among native candidates: "
                    + identity.ModelId + ":" + identity.UpgradeLevel + ":" + identity.EnchantmentId
                    + ":" + identity.Ordinal)).ToArray();
            if (chosen.Distinct(ReferenceEqualityComparer.Instance).Count() != chosen.Length)
                throw new InvalidOperationException("Recorded card identity selection resolves to a duplicate native card.");
        }
        else
        {
            chosen = ForcedCardModelSelections.Count == 0
                ? candidates.Take(minSelect).ToArray()
                : ChooseRecordedCards(candidates, ForcedCardModelSelections.Dequeue(), minSelect, maxSelect);
        }
        SelectedCardIds.AddRange(chosen.Select(card => card.Id.Entry));
        SelectedCardModels.AddRange(chosen);
        return Task.FromResult<IEnumerable<CardModel>>(chosen);
    }

    private static CardModel[] ChooseRecordedCards(CardModel[] candidates, string[] modelIds,
        int minSelect, int maxSelect)
    {
        if (modelIds.Length < minSelect || modelIds.Length > maxSelect)
            throw new InvalidOperationException("Recorded card selection violates native selection bounds.");
        var available = candidates.ToList();
        var chosen = new List<CardModel>();
        foreach (string modelId in modelIds)
        {
            int ordinal = modelId == "CARD.DEFEND_IRONCLAD"
                && int.TryParse(System.Environment.GetEnvironmentVariable("STS2_PROBE_REPLAY_DEFEND_ORDINAL"),
                    out int configuredOrdinal) ? configuredOrdinal : 0;
            var card = available.Where(candidate => candidate.Id.ToString() == modelId
                    || candidate.Id.Entry == modelId)
                .Skip(ordinal).FirstOrDefault()
                ?? throw new InvalidOperationException("Recorded card selection is not among native candidates: "
                    + modelId);
            chosen.Add(card);
            available.Remove(card);
        }
        return chosen.ToArray();
    }

    public CardRewardSelection GetSelectedCardReward(
        IReadOnlyList<CardCreationResult> options,
        IReadOnlyList<CardRewardAlternative> alternatives)
    {
        RewardCandidateIds.Add(options.Select(option => option.Card.Id.ToString()).ToArray());
        string? forcedModelId = ForcedRewardCardModelSelections.Count > 0
            ? ForcedRewardCardModelSelections.Dequeue() : null;
        if (forcedModelId == SkipRewardSelection)
            return new CardRewardSelection();
        var card = forcedModelId is null
            ? options.FirstOrDefault()?.Card
            : options.Select(option => option.Card).FirstOrDefault(candidate =>
                candidate.Id.Entry == forcedModelId || candidate.Id.ToString() == forcedModelId);
        if (card is null)
            throw new InvalidOperationException(forcedModelId is null
                ? "Native card reward offered no card candidates."
                : "Forced reward card is not among native candidates: " + forcedModelId);
        SelectedRewardCardIds.Add(card.Id.Entry);
        return new CardRewardSelection { card = card };
    }
}

internal sealed record ProbeCardSelectionOffer(string[] Candidates, int MinSelect, int MaxSelect);
