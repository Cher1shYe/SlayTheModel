using System.Security.Cryptography;
using System.Text.Json;
using Godot;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Commands;
using MegaCrit.Sts2.Core.Entities.CardRewardAlternatives;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.Helpers;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Characters;
using MegaCrit.Sts2.Core.Models.Encounters;
using MegaCrit.Sts2.Core.Multiplayer;
using MegaCrit.Sts2.Core.Rewards;
using MegaCrit.Sts2.Core.Rooms;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves;
using MegaCrit.Sts2.Core.TestSupport;
using MegaCrit.Sts2.Core.Timeline;
using MegaCrit.Sts2.Core.Unlocks;
using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;
using SlayTheModel.Search;

/// <summary>
/// Replays one deliberately simple Spire Codex combat through the pinned native
/// game. This is the correctness pilot for recovering legal actions; it does
/// not emit training tensors and never exposes replay-only RNG data to a model.
/// </summary>
public static class SpireCodexCombatReplayPilot
{
    public static async Task RunAsync(
        NativeSession session,
        string planPath,
        string outputPath,
        CancellationToken cancellation)
    {
        using var document = JsonDocument.Parse(File.ReadAllText(planPath));
        JsonElement root = document.RootElement;
        if (String(root, "format_version") != "stm-spire-codex-native-combat-plan-v1"
            || !root.GetProperty("replay_only_hidden_state").GetBoolean())
            throw new InvalidDataException("Unsupported or non-internal Spire Codex combat plan.");
        JsonElement run = root.GetProperty("run");
        JsonElement combat = root.GetProperty("combat");
        session.Seed = String(run, "seed");
        session.CharacterId = String(run, "character");
        session.AscensionLevel = Integer(run, "ascension");
        session.EncounterId = String(combat, "encounter");
        JsonElement runSnapshot = combat.GetProperty("run_snapshot");
        session.InitialHp = Integer(runSnapshot, "current_hp");
        session.InitialMaxHp = Integer(runSnapshot, "max_hp");
        session.InitialGold = Integer(runSnapshot, "gold");
        session.InitialActFloor = Integer(runSnapshot, "floor");
        session.InitialDeck = combat.TryGetProperty("replay_deck", out JsonElement replayDeck)
            ? replayDeck.EnumerateArray().Select(card =>
                {
                    if (card.TryGetProperty("enchantment", out _)
                        || card.TryGetProperty("state", out _))
                        throw new NotSupportedException(
                            "Native replay deck restoration does not yet support enchantments or persistent card state.");
                    return new NativeReplayDeckCard(String(card, "model_id"), Integer(card, "upgrade"));
                }).ToArray()
            : [];
        session.InitialRelicIds = runSnapshot.GetProperty("relics").EnumerateArray()
            .Select(relic => String(relic, "model_id")).Where(id => id.Length > 0).ToArray();
        session.InitialPotions = runSnapshot.GetProperty("potions").EnumerateArray()
            .Select(potion => (Integer(potion, "slot"), String(potion, "model_id")))
            .Where(potion => potion.Item2.Length > 0).ToArray();
        await session.ResetAsync(session.Seed, cancellation);
        VerifyRunSnapshot(session.CombatStateForSimulation, runSnapshot);
        CombatReplayResult replay = await ReplayCurrentCombatAsync(session, combat, 0, cancellation);

        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, JsonSerializer.Serialize(new
        {
            formatVersion = "stm-spire-codex-native-combat-replay-report-v1",
            planPath,
            planSha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(planPath))).ToLowerInvariant(),
            source = root.GetProperty("source"),
            matchedDecisions = replay.Matched,
            nativeVictory = session.Won,
            finalHp = session.Hp,
            decisions = replay.Decisions,
            replayOnlyStateExcludedFromDecisions = true,
            error = (string?)null,
        }, new JsonSerializerOptions { WriteIndented = true }));
        GD.Print($"SPIRE_CODEX_NATIVE_REPLAY_MATCH decisions={replay.Matched} output={outputPath}");
    }

    public static async Task RunSequentialAsync(
        Node host,
        NativeSession session,
        string firstPlanPath,
        string nextPlanPath,
        string outputPath,
        CancellationToken cancellation)
    {
        using var firstDocument = JsonDocument.Parse(File.ReadAllText(firstPlanPath));
        using var nextDocument = JsonDocument.Parse(File.ReadAllText(nextPlanPath));
        JsonElement firstRoot = firstDocument.RootElement;
        JsonElement nextRoot = nextDocument.RootElement;
        ValidatePlan(firstRoot);
        ValidatePlan(nextRoot);
        JsonElement firstRun = firstRoot.GetProperty("run");
        JsonElement nextRun = nextRoot.GetProperty("run");
        foreach (string field in new[] { "seed", "character" })
            if (String(firstRun, field) != String(nextRun, field))
                throw new InvalidDataException($"Sequential plans disagree on {field}.");
        if (Integer(firstRun, "ascension") != Integer(nextRun, "ascension"))
            throw new InvalidDataException("Sequential plans disagree on ascension.");

        string seed = SeedHelper.CanonicalizeSeed(String(firstRun, "seed"));
        foreach (string epoch in EpochModel.AllEpochIds)
            SaveManager.Instance.ObtainEpochOverride(epoch, EpochState.Revealed);
        UnlockState unlockState = SaveManager.Instance.GenerateUnlockStateFromProgress();
        Player player = CreatePlayer(String(firstRun, "character"), unlockState);
        var actRng = new MegaCrit.Sts2.Core.Random.Rng(
            StringHelper.GetDeterministicHashCode(seed), "act_selection");
        var acts = ActModel.GetRandomList(actRng, unlockState, false)
            .Select(act => act.ToMutable()).ToList();
        var nativeRun = RunState.CreateForNewRun(
            [player], acts, [], GameMode.Standard, Integer(firstRun, "ascension"), seed);
        RunManager.Instance.ForceDiscoveryOrderModifications = true;
        RunManager.Instance.SetUpNewSingleplayer(nativeRun, false, null);

        var selector = new AutoProbeCardSelector();
        using var selectorScope = CardSelectCmd.PushSelector(selector);
        await RunManager.Instance.EnterAct(0, false).WaitAsync(TimeSpan.FromSeconds(10), cancellation);
        JsonElement firstCombat = firstRoot.GetProperty("combat");
        JsonElement firstSnapshot = firstCombat.GetProperty("run_snapshot");
        var neow = (nativeRun.CurrentRoom as EventRoom)?.LocalMutableEvent
            ?? throw new InvalidOperationException("Sequential native run did not enter Neow.");
        string[] addedRelics = MultisetDifference(
            firstSnapshot.GetProperty("relics").EnumerateArray().Select(relic => String(relic, "model_id")),
            player.Relics.Where(relic => !relic.IsMelted).Select(relic => relic.Id.Entry));
        string[] addedCards = MultisetDifference(
            firstSnapshot.GetProperty("deck").EnumerateArray().Select(CardKey),
            player.Deck.Cards.Select(CardKey));
        if (addedRelics.Length != 1 || addedCards.Length != 1)
            throw new NotSupportedException(
                "Sequential pilot currently requires Neow to add exactly one relic and one card.");
        string forcedRewardCard = addedCards[0].Split('+', 2)[0];
        selector.ForcedCardModelSelections.Enqueue([forcedRewardCard]);
        selector.ForcedRewardCardModelSelections.Enqueue(forcedRewardCard);
        var neowOption = neow.CurrentOptions.Where(option => !option.IsLocked && !option.WasChosen)
            .SingleOrDefault(option => option.Relic?.Id.Entry == addedRelics[0])
            ?? throw new InvalidDataException("Recorded Neow relic option is not available natively: " + addedRelics[0]);
        await neowOption.Chosen().WaitAsync(TimeSpan.FromSeconds(10), cancellation);
        if (!neow.IsFinished)
            throw new InvalidOperationException("Recorded Neow option did not complete natively.");

        await EnterRecordedCombatAsync(nativeRun, firstCombat, firstSnapshot, cancellation);
        RequireEncounter(nativeRun, String(firstCombat, "encounter"));
        await session.AttachCurrentCombatAsync(cancellation);
        VerifyRunSnapshot(session.CombatStateForSimulation, firstSnapshot);
        CombatReplayResult firstReplay = await ReplayCurrentCombatAsync(session, firstCombat, 0, cancellation);

        JsonElement nextCombat = nextRoot.GetProperty("combat");
        JsonElement nextSnapshot = nextCombat.GetProperty("run_snapshot");
        object rewardTransition = await ReplayRewardsAsync(
            host, nativeRun, player, nextSnapshot, cancellation);
        await EnterRecordedCombatAsync(nativeRun, nextCombat, nextSnapshot, cancellation);
        RequireEncounter(nativeRun, String(nextCombat, "encounter"));
        await session.AttachCurrentCombatAsync(cancellation);
        VerifyRunSnapshot(session.CombatStateForSimulation, nextSnapshot);
        CombatReplayResult nextReplay = await ReplayCurrentCombatAsync(
            session, nextCombat, firstReplay.Matched, cancellation);

        Directory.CreateDirectory(Path.GetDirectoryName(Path.GetFullPath(outputPath))!);
        File.WriteAllText(outputPath, JsonSerializer.Serialize(new
        {
            formatVersion = "stm-spire-codex-native-sequential-replay-report-v1",
            firstPlanPath,
            nextPlanPath,
            firstPlanSha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(firstPlanPath)))
                .ToLowerInvariant(),
            nextPlanSha256 = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(nextPlanPath)))
                .ToLowerInvariant(),
            sources = new[] { firstRoot.GetProperty("source"), nextRoot.GetProperty("source") },
            seed,
            character = String(firstRun, "character"),
            ascension = Integer(firstRun, "ascension"),
            neowRelic = addedRelics[0],
            neowCard = forcedRewardCard,
            encounterSelection = "recorded-native-model",
            encounterSelectionReason = "source unlock state is not present in the replay header",
            firstEncounter = String(firstCombat, "encounter"),
            nextEncounter = String(nextCombat, "encounter"),
            firstMatchedDecisions = firstReplay.Matched,
            nextMatchedDecisions = nextReplay.Matched,
            matchedDecisions = firstReplay.Matched + nextReplay.Matched,
            rewardTransition,
            nativeVictory = session.Won,
            finalHp = session.Hp,
            combats = new[]
            {
                new { encounter = String(firstCombat, "encounter"), decisions = firstReplay.Decisions },
                new { encounter = String(nextCombat, "encounter"), decisions = nextReplay.Decisions },
            },
            replayOnlyStateExcludedFromDecisions = true,
            error = (string?)null,
        }, new JsonSerializerOptions { WriteIndented = true }));
        GD.Print($"SPIRE_CODEX_NATIVE_SEQUENTIAL_REPLAY_MATCH decisions="
            + $"{firstReplay.Matched + nextReplay.Matched} output={outputPath}");
    }

    private static void ValidatePlan(JsonElement root)
    {
        if (String(root, "format_version") != "stm-spire-codex-native-combat-plan-v1"
            || !root.GetProperty("replay_only_hidden_state").GetBoolean())
            throw new InvalidDataException("Unsupported or non-internal Spire Codex combat plan.");
    }

    private static Player CreatePlayer(string character, UnlockState unlockState) =>
        character.ToUpperInvariant() switch
        {
            "IRONCLAD" => Player.CreateForNewRun<Ironclad>(unlockState, 1),
            "SILENT" => Player.CreateForNewRun<Silent>(unlockState, 1),
            "DEFECT" => Player.CreateForNewRun<Defect>(unlockState, 1),
            "NECROBINDER" => Player.CreateForNewRun<Necrobinder>(unlockState, 1),
            "REGENT" => Player.CreateForNewRun<Regent>(unlockState, 1),
            _ => throw new InvalidDataException("Unknown replay character " + character),
        };

    private static async Task EnterRecordedCombatAsync(
        RunState run,
        JsonElement combat,
        JsonElement snapshot,
        CancellationToken cancellation)
    {
        run.ActFloor = Integer(snapshot, "floor");
        string encounterId = String(combat, "encounter");
        EncounterModel encounter = ModelDb.All.OfType<EncounterModel>().Single(candidate =>
            candidate.Id.Entry.Equals(encounterId, StringComparison.OrdinalIgnoreCase)
            || candidate.GetType().Name.Equals(encounterId, StringComparison.OrdinalIgnoreCase));
        await RunManager.Instance.EnterRoomDebug(RoomType.Monster, model: encounter.ToMutable())
            .WaitAsync(TimeSpan.FromSeconds(10), cancellation);
    }

    private static void RequireEncounter(RunState run, string expected)
    {
        string actual = (run.CurrentRoom as CombatRoom)?.Encounter.Id.Entry
            ?? throw new InvalidOperationException("Recorded combat coordinate did not create a combat room.");
        if (actual != expected)
            throw new InvalidDataException($"Encounter differs: recorded={expected}, native={actual}.");
    }

    private static string[] MultisetDifference(IEnumerable<string> expected, IEnumerable<string> actual)
    {
        var remaining = actual.GroupBy(value => value).ToDictionary(
            group => group.Key, group => group.Count(), StringComparer.Ordinal);
        var difference = new List<string>();
        foreach (string value in expected)
        {
            if (remaining.TryGetValue(value, out int count) && count > 0)
                remaining[value] = count - 1;
            else
                difference.Add(value);
        }
        return difference.ToArray();
    }

    private static string CardKey(JsonElement card) =>
        String(card, "model_id") + "+" + Integer(card, "upgrade");

    private static string CardKey(CardModel card) =>
        card.Id.Entry + "+" + card.CurrentUpgradeLevel;

    private static async Task<object> ReplayRewardsAsync(
        Node host,
        RunState run,
        Player player,
        JsonElement nextSnapshot,
        CancellationToken cancellation)
    {
        var combat = run.CurrentRoom as CombatRoom
            ?? throw new InvalidOperationException("Native run left the completed combat before rewards.");
        int goldBefore = player.Gold;
        string[] potionsBefore = player.PotionSlots.Select(potion => potion?.Id.Entry ?? "").ToArray();
        bool previousTestMode = TestMode.IsOn;
        bool skippedRemaining = false;
        var selected = new List<string>();
        try
        {
            TestMode.IsOn = false;
            Task offer = combat.OfferRoomEndRewards();
            RewardsSet? rewardSet = null;
            var deadline = System.Diagnostics.Stopwatch.StartNew();
            while (rewardSet is null && !offer.IsCompleted && deadline.Elapsed < TimeSpan.FromSeconds(5))
            {
                rewardSet = TryGetOpenRewardSet();
                if (rewardSet is null)
                    await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
            }
            rewardSet ??= TryGetOpenRewardSet();
            if (rewardSet is null)
                throw new InvalidOperationException("Native rewards were not exposed for sequential replay.");

            int expectedGold = Integer(nextSnapshot, "gold");
            string[] expectedPotions = nextSnapshot.GetProperty("potions").EnumerateArray()
                .Select(potion => String(potion, "model_id")).ToArray();
            foreach (Reward reward in rewardSet.Rewards.ToArray())
            {
                bool take = reward switch
                {
                    GoldReward => player.Gold < expectedGold,
                    PotionReward potion => potion.Potion is not null
                        && expectedPotions.Contains(potion.Potion.Id.Entry, StringComparer.Ordinal),
                    _ => false,
                };
                if (!take) continue;
                if (!await RunManager.Instance.RewardsSetSynchronizer.SelectLocalReward(reward)
                        .WaitAsync(TimeSpan.FromSeconds(10), cancellation))
                    throw new InvalidOperationException("Native reward selection was rejected: " + reward.GetType().Name);
                selected.Add(reward switch
                {
                    GoldReward gold => "gold:" + gold.Amount,
                    PotionReward potion => "potion:" + potion.Potion?.Id.Entry,
                    _ => reward.GetType().Name,
                });
            }
            if (rewardSet.Rewards.Any(reward => !reward.SuccessfullySelected))
            {
                RunManager.Instance.RewardsSetSynchronizer.SkipLocalRewardsSet();
                skippedRemaining = true;
            }
            await offer.WaitAsync(TimeSpan.FromSeconds(10), cancellation);
        }
        finally
        {
            TestMode.IsOn = previousTestMode;
        }

        VerifyPlayerSnapshot(player, nextSnapshot);
        return new
        {
            goldBefore,
            goldAfter = player.Gold,
            potionsBefore,
            potionsAfter = player.PotionSlots.Select(potion => potion?.Id.Entry ?? "").ToArray(),
            selected = selected.ToArray(),
            skippedRemaining,
        };
    }

    private static RewardsSet? TryGetOpenRewardSet()
    {
        const System.Reflection.BindingFlags flags = System.Reflection.BindingFlags.Instance
            | System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.NonPublic;
        var states = RunManager.Instance.RewardsSetSynchronizer.GetType()
            .GetField("_rewardStates", flags)?.GetValue(RunManager.Instance.RewardsSetSynchronizer)
            as System.Collections.IEnumerable;
        if (states is null) return null;
        foreach (object? state in states)
        {
            var stack = state?.GetType().GetField("rewardsStack", flags)?.GetValue(state)
                as System.Collections.IList;
            if (stack is not { Count: > 0 }) continue;
            object? top = stack[stack.Count - 1];
            if (top?.GetType().GetField("set", flags)?.GetValue(top) is RewardsSet set)
                return set;
        }
        return null;
    }

    private sealed record CombatReplayResult(int Matched, List<object> Decisions);

    private static async Task<CombatReplayResult> ReplayCurrentCombatAsync(
        NativeSession session,
        JsonElement combat,
        long decisionOffset,
        CancellationToken cancellation)
    {
        uint?[] enemyIdsByRecordedSlot = session.CombatStateForSimulation.Enemies
            .Select(enemy => enemy.CombatId).ToArray();
        var decisions = new List<object>();
        int matched = 0;
        foreach (JsonElement step in combat.GetProperty("actions").EnumerateArray())
        {
            cancellation.ThrowIfCancellationRequested();
            JsonElement recordedAction = step.GetProperty("action");
            CombatState state = session.CombatStateForSimulation;
            // Spire Codex observes EndTurn after the native hand flush and
            // passive end-of-turn effects. The sequential native replay is the
            // only trustworthy pre-click observation for that action.
            string recordedKind = String(recordedAction, "kind");
            if (recordedKind is not ("end_turn" or "resolve_choice"))
                VerifyState(state, step.GetProperty("expected_combat"), Integer(step, "source_sequence"));
            IReadOnlyList<SearchAction> legal = session.Actions();
            SearchAction selected = SelectAction(
                session, state, legal, recordedAction, enemyIdsByRecordedSlot);
            CombatObservation nativeObservation;
            IReadOnlyList<CombatActionDescriptor> nativeLegalActions;
            CombatActionDescriptor nativeSelectedAction;
            if (recordedKind == "resolve_choice")
            {
                (nativeObservation, nativeLegalActions, nativeSelectedAction) =
                    BuildChoiceDecision(session, state, legal, selected, decisionOffset + matched);
            }
            else
            {
                CombatDecisionPoint nativeDecision = CombatCaptureService.BuildDecisionPoint(
                    state, decisionOffset + matched);
                nativeObservation = nativeDecision.Observation;
                nativeLegalActions = nativeDecision.LegalActions;
                nativeSelectedAction = selected.Combat
                    ?? throw new InvalidDataException("Native direct action has no combat descriptor.");
            }
            decisions.Add(new
            {
                sourceSequence = Integer(step, "source_sequence"),
                round = state.RoundNumber,
                legalActionCount = legal.Count,
                legalActions = ProjectLegalActions(state, legal, enemyIdsByRecordedSlot),
                selected = ProjectAction(state, selected, enemyIdsByRecordedSlot),
                nativeObservation = JsonSerializer.SerializeToElement(nativeObservation, ProtocolJson.Options),
                nativeLegalActions = JsonSerializer.SerializeToElement(nativeLegalActions, ProtocolJson.Options),
                nativeSelectedAction = JsonSerializer.SerializeToElement(
                    nativeSelectedAction, ProtocolJson.Options),
                reconstructionReplayEligible = step.GetProperty("reconstruction_replay_eligible").GetBoolean(),
            });
            await session.StepAsync(selected, cancellation);
            matched++;
        }

        if (!session.Terminal || !session.Won)
            throw new InvalidOperationException(
                $"Recorded combat actions did not reach a native victory: terminal={session.Terminal} won={session.Won}.");
        return new CombatReplayResult(matched, decisions);
    }

    private static SearchAction SelectAction(
        NativeSession session,
        CombatState state,
        IReadOnlyList<SearchAction> legal,
        JsonElement action,
        IReadOnlyList<uint?> enemyIdsByRecordedSlot)
    {
        string kind = String(action, "kind");
        if (kind == "resolve_choice")
        {
            string[] selectedCards = action.GetProperty("selected_cards").EnumerateArray()
                .Select(card => String(card, "model_id") + "+" + Integer(card, "upgrade"))
                .Order(StringComparer.Ordinal).ToArray();
            var choiceMatches = legal.Where(candidate => candidate.Selection is { } selection
                && selection.Select(index => session.PendingChoiceOptions[index].Id.Entry + "+"
                        + session.PendingChoiceOptions[index].CurrentUpgradeLevel)
                    .Order(StringComparer.Ordinal).SequenceEqual(selectedCards, StringComparer.Ordinal)).ToArray();
            if (choiceMatches.Length == 0)
                throw new InvalidDataException(
                    $"Recorded combat choice [{string.Join(',', selectedCards)}] has no native selection.");
            return choiceMatches[0];
        }
        if (kind == "end_turn")
            return legal.Single(candidate => candidate.Combat?.Kind == CombatActionKind.EndTurn);
        if (kind != "play_card")
            throw new NotSupportedException("Pilot action is not yet supported: " + kind);

        string cardId = String(action, "card_model_id");
        int upgrade = Integer(action, "upgrade");
        uint? targetId = null;
        if (action.TryGetProperty("target_slot", out JsonElement targetSlot)
            && targetSlot.ValueKind == JsonValueKind.Number)
        {
            int slot = targetSlot.GetInt32();
            if (slot < 0 || slot >= enemyIdsByRecordedSlot.Count)
                throw new InvalidDataException("Recorded target slot is out of range: " + slot);
            targetId = enemyIdsByRecordedSlot[slot];
            var target = state.Creatures.Single(creature => creature.CombatId == targetId);
            string expectedTarget = String(action, "target_model_id");
            if (!string.Equals(target.ModelId.Entry, expectedTarget, StringComparison.Ordinal))
                throw new InvalidDataException($"Recorded target slot {slot} is {expectedTarget}, native is {target.ModelId}.");
        }
        var hand = state.Players.Single().PlayerCombatState!.Hand.Cards;
        var matches = legal.Where(candidate =>
        {
            if (candidate.Combat is not { Kind: CombatActionKind.PlayCard, CombatCardIndex: { } cardIndex }
                || candidate.Combat.TargetCreatureId != targetId)
                return false;
            CardModel card = hand.Single(value => NetCombatCard.FromModel(value).CombatCardIndex == cardIndex);
            return card.Id.Entry == cardId && card.CurrentUpgradeLevel == upgrade;
        }).ToArray();
        if (matches.Length == 0)
            throw new InvalidDataException($"Recorded play {cardId}+{upgrade} target={targetId} is not natively legal.");
        return matches[0];
    }

    private static (CombatObservation Observation,
        IReadOnlyList<CombatActionDescriptor> LegalActions,
        CombatActionDescriptor SelectedAction) BuildChoiceDecision(
            NativeSession session,
            CombatState state,
            IReadOnlyList<SearchAction> legal,
            SearchAction selected,
            long decisionIndex)
    {
        const uint choiceId = 1;
        var player = state.Players.Single();
        CombatChoiceCardObservation[] cards = session.PendingChoiceOptions.Select(card =>
            new CombatChoiceCardObservation(
                NetCombatCard.FromModel(card).CombatCardIndex,
                card.Id.Entry,
                card.CurrentUpgradeLevel)).ToArray();
        var choice = new CombatChoiceObservation(
            choiceId,
            "native_replay",
            Math.Min(session.PendingChoiceMin, cards.Length),
            Math.Min(session.PendingChoiceMax, cards.Length),
            session.PendingChoiceMin == 0,
            cards);
        CombatObservation observation = CombatCaptureService.BuildObservation(state, decisionIndex)
            with { ActiveChoice = choice };
        IReadOnlyList<CombatActionDescriptor> protocolLegal;
        if (choice.MaxSelections > 1)
        {
            var values = new List<CombatActionDescriptor>
            {
                new(CombatActionKind.ResolveChoice, player.NetId, ChoiceId: choiceId,
                    IsSelectionTemplate: true),
            };
            if (choice.CanCancel && choice.MinSelections > 0)
                values.Add(new CombatActionDescriptor(
                    CombatActionKind.ResolveChoice, player.NetId, ChoiceId: choiceId,
                    SelectedCombatCardIds: []));
            protocolLegal = values;
        }
        else
        {
            protocolLegal = legal.Select(action => new CombatActionDescriptor(
                CombatActionKind.ResolveChoice,
                player.NetId,
                ChoiceId: choiceId,
                SelectedCombatCardIds: (action.Selection ?? [])
                    .Select(index => cards[index].CombatCardIndex!.Value).ToArray())).ToArray();
        }
        var selectedAction = new CombatActionDescriptor(
            CombatActionKind.ResolveChoice,
            player.NetId,
            ChoiceId: choiceId,
            SelectedCombatCardIds: (selected.Selection ?? [])
                .Select(index => cards[index].CombatCardIndex!.Value).ToArray());
        observation.Validate();
        foreach (CombatActionDescriptor action in protocolLegal) action.Validate();
        selectedAction.Validate();
        return (observation, protocolLegal, selectedAction);
    }

    private static object[] ProjectLegalActions(CombatState state, IReadOnlyList<SearchAction> legal,
        IReadOnlyList<uint?> enemyIdsByRecordedSlot) =>
        legal.Select(action => ProjectAction(state, action, enemyIdsByRecordedSlot)).ToArray();

    private static object ProjectAction(CombatState state, SearchAction action,
        IReadOnlyList<uint?> enemyIdsByRecordedSlot)
    {
        if (action.Combat is not { } combat)
            return new { kind = "choice", selection = action.Selection };
        if (combat.Kind == CombatActionKind.EndTurn)
            return new { kind = "end_turn", cardModelId = (string?)null, upgrade = (int?)null, targetSlot = (int?)null };
        if (combat.Kind != CombatActionKind.PlayCard || combat.CombatCardIndex is not { } cardIndex)
            return new { kind = combat.Kind.ToString(), cardModelId = (string?)null, upgrade = (int?)null, targetSlot = (int?)null };
        CardModel card = state.Players.Single().PlayerCombatState!.Hand.Cards.Single(
            value => NetCombatCard.FromModel(value).CombatCardIndex == cardIndex);
        int? slot = combat.TargetCreatureId is { } target
            ? enemyIdsByRecordedSlot.ToList().FindIndex(enemyId => enemyId == target)
            : null;
        return new { kind = "play_card", cardModelId = card.Id.Entry, upgrade = (int?)card.CurrentUpgradeLevel, targetSlot = slot };
    }

    private static void VerifyState(CombatState state, JsonElement expected, int sourceSequence)
    {
        var player = state.Players.Single();
        var combat = player.PlayerCombatState
            ?? throw new InvalidDataException("Native player has no combat state.");
        JsonElement expectedPlayer = expected.GetProperty("player");
        RequireEqual("round", Integer(expected, "round"), state.RoundNumber, sourceSequence);
        RequireEqual("energy", Integer(expected, "energy"), combat.Energy, sourceSequence);
        RequireEqual("player hp", Integer(expectedPlayer, "current_hp"), player.Creature.CurrentHp, sourceSequence);
        RequireEqual("player max hp", Integer(expectedPlayer, "max_hp"), player.Creature.MaxHp, sourceSequence);
        RequireEqual("player block", Integer(expectedPlayer, "block"), player.Creature.Block, sourceSequence);

        JsonElement[] expectedEnemies = expected.GetProperty("enemies").EnumerateArray()
            .Where(enemy => enemy.GetProperty("alive").GetBoolean()).ToArray();
        RequireEqual("enemy count", expectedEnemies.Length, state.Enemies.Count, sourceSequence);
        for (int index = 0; index < expectedEnemies.Length; index++)
        {
            JsonElement recorded = expectedEnemies[index];
            var native = state.Enemies[index];
            RequireEqual($"enemy {index} model", String(recorded, "model_id"), native.ModelId.Entry, sourceSequence);
            RequireEqual($"enemy {index} hp", Integer(recorded, "current_hp"), native.CurrentHp, sourceSequence);
            RequireEqual($"enemy {index} max hp", Integer(recorded, "max_hp"), native.MaxHp, sourceSequence);
            RequireEqual($"enemy {index} block", Integer(recorded, "block"), native.Block, sourceSequence);
            RequireEqual($"enemy {index} alive", recorded.GetProperty("alive").GetBoolean(), native.IsAlive, sourceSequence);
        }

        JsonElement piles = expected.GetProperty("piles");
        VerifyPile("hand", piles.GetProperty("hand"), combat.Hand.Cards, sourceSequence);
        VerifyPile("draw", piles.GetProperty("draw"), combat.DrawPile.Cards, sourceSequence);
        VerifyPile("discard", piles.GetProperty("discard"), combat.DiscardPile.Cards, sourceSequence);
        VerifyPile("exhaust", piles.GetProperty("exhaust"), combat.ExhaustPile.Cards, sourceSequence);
    }

    private static void VerifyRunSnapshot(CombatState state, JsonElement expected)
    {
        var player = state.Players.Single();
        VerifyPlayerSnapshot(player, expected);
    }

    private static void VerifyPlayerSnapshot(Player player, JsonElement expected)
    {
        RequireEqual("run gold", Integer(expected, "gold"), player.Gold, -1);
        RequireEqual("run hp", Integer(expected, "current_hp"), player.Creature.CurrentHp, -1);
        RequireEqual("run max hp", Integer(expected, "max_hp"), player.Creature.MaxHp, -1);
        string[] expectedDeck = expected.GetProperty("deck").EnumerateArray()
            .Select(CardKey).Order(StringComparer.Ordinal).ToArray();
        string[] actualDeck = player.Deck.Cards.Select(CardKey).Order(StringComparer.Ordinal).ToArray();
        if (!expectedDeck.SequenceEqual(actualDeck, StringComparer.Ordinal))
            throw new InvalidDataException(
                $"Run deck differs: recorded=[{string.Join(',', expectedDeck)}] native=[{string.Join(',', actualDeck)}].");
        string[] expectedRelics = expected.GetProperty("relics").EnumerateArray()
            .Select(relic => String(relic, "model_id")).Order(StringComparer.Ordinal).ToArray();
        string[] actualRelics = player.Relics.Where(relic => !relic.IsMelted)
            .Select(relic => relic.Id.Entry).Order(StringComparer.Ordinal).ToArray();
        if (!expectedRelics.SequenceEqual(actualRelics, StringComparer.Ordinal))
            throw new InvalidDataException(
                $"Run relics differ: recorded=[{string.Join(',', expectedRelics)}] native=[{string.Join(',', actualRelics)}].");
        string[] expectedPotions = expected.GetProperty("potions").EnumerateArray()
            .Select(potion => Integer(potion, "slot") + ":" + String(potion, "model_id")).ToArray();
        string[] actualPotions = player.PotionSlots.Select((potion, slot) => (potion, slot))
            .Where(value => value.potion is not null)
            .Select(value => value.slot + ":" + value.potion!.Id.Entry).ToArray();
        if (!expectedPotions.SequenceEqual(actualPotions, StringComparer.Ordinal))
            throw new InvalidDataException(
                $"Run potions differ: recorded=[{string.Join(',', expectedPotions)}] native=[{string.Join(',', actualPotions)}].");
    }

    private static void VerifyPile(string name, JsonElement expected, IReadOnlyList<CardModel> native, int sequence)
    {
        string[] recorded = expected.EnumerateArray().Select(card =>
            String(card, "model_id") + "+" + Integer(card, "upgrade")).Order(StringComparer.Ordinal).ToArray();
        string[] actual = native.Select(card => card.Id.Entry + "+" + card.CurrentUpgradeLevel)
            .Order(StringComparer.Ordinal).ToArray();
        if (!recorded.SequenceEqual(actual, StringComparer.Ordinal))
            throw new InvalidDataException(
                $"Combat {name} differs at source sequence {sequence}: recorded=[{string.Join(',', recorded)}] native=[{string.Join(',', actual)}].");
    }

    private static void RequireEqual<T>(string field, T expected, T actual, int sequence)
    {
        if (!EqualityComparer<T>.Default.Equals(expected, actual))
            throw new InvalidDataException($"Combat {field} differs at source sequence {sequence}: recorded={expected}, native={actual}.");
    }

    private static string String(JsonElement value, string property) =>
        value.TryGetProperty(property, out JsonElement child) && child.ValueKind == JsonValueKind.String
            ? child.GetString() ?? ""
            : "";

    private static int Integer(JsonElement value, string property) =>
        value.TryGetProperty(property, out JsonElement child) && child.ValueKind == JsonValueKind.Number
            ? child.GetInt32()
            : 0;
}
