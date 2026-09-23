using System.Security.Cryptography;
using System.Text.Json;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.Entities.Players;
using MegaCrit.Sts2.Core.GameActions.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Runs;
using MegaCrit.Sts2.Core.Saves;
using SlayTheModel.Sts2.Protocol;
using ProtocolCombatSide = SlayTheModel.Sts2.Protocol.CombatSide;

namespace SlayTheModel.Sts2.ModAdapter;

public static class CombatCaptureService
{
    private const string GameVersion = "v0.111.0";
    private static readonly object Gate = new();
    private static readonly BuildIdentity Build = CreateBuildIdentity();
    private static readonly JsonSerializerOptions NativeJsonOptions = new()
    {
        IncludeFields = true,
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower,
    };
    private static string? _lastFingerprint;
    private static long _decisionIndex;
    private static bool _capturing;

    public static void Reset()
    {
        lock (Gate)
        {
            _lastFingerprint = null;
            _decisionIndex = 0;
            _capturing = false;
        }
    }

    public static void TryCapture(CombatState state)
    {
        lock (Gate)
        {
            if (_capturing)
            {
                return;
            }

            _capturing = true;
            try
            {
                CaptureIfDecisionPoint(state);
            }
            catch (Exception exception)
            {
                Console.Error.WriteLine($"[SlayTheModel] capture failed: {exception}");
            }
            finally
            {
                _capturing = false;
            }
        }
    }

    private static void CaptureIfDecisionPoint(CombatState state)
    {
        var manager = CombatManager.Instance;
        if (!manager.IsInProgress
            || manager.IsOverOrEnding
            || manager.PlayerActionsDisabled
            || state.CurrentSide != MegaCrit.Sts2.Core.Combat.CombatSide.Player)
        {
            return;
        }

        if (GetLegalActions(state).Count == 0)
        {
            return;
        }

        var searchPoint = BuildSearchPoint(state, _decisionIndex);
        var fingerprint = searchPoint.Decision.StateFingerprint;
        if (string.Equals(fingerprint, _lastFingerprint, StringComparison.Ordinal))
        {
            return;
        }

        WriteDecisionPoint(searchPoint);
        _lastFingerprint = fingerprint;
        _decisionIndex++;
    }

    /// <summary>
    /// Builds the filtered request consumed by a combat-only policy. This request contains
    /// no run economy, hidden RNG, native payload, or simulator bookkeeping.
    /// </summary>
    public static CombatDecisionPoint BuildDecisionPoint(CombatState state, long decisionIndex)
        => BuildSearchPoint(state, decisionIndex).Decision;

    /// <summary>
    /// Builds both sides of the policy boundary. Headless search owns SimulatorState,
    /// combat policies receive Decision, and the future run controller receives
    /// RunObservation.
    /// </summary>
    public static CombatSearchPoint BuildSearchPoint(CombatState state, long decisionIndex)
    {
        ArgumentNullException.ThrowIfNull(state);
        var legalActions = GetLegalActions(state);
        if (legalActions.Count == 0)
        {
            throw new InvalidOperationException("Combat state has no player decision to expose.");
        }

        var runState = RunManager.Instance.DebugOnlyGetState()
            ?? throw new InvalidOperationException("Run state is unavailable during combat capture.");
        var nativeState = NetFullCombatState.FromRun(runState, null);
        var nativeChecksum = RunManager.Instance.ChecksumTracker.GenerateChecksum(nativeState);
        var snapshot = MapSnapshot(state, nativeState, nativeChecksum, decisionIndex);
        var fingerprint = ProtocolJson.ComputeStateFingerprint(snapshot);
        var decision = new CombatDecisionPoint(
            CombatDecisionPoint.CurrentSchemaVersion,
            decisionIndex,
            fingerprint,
            DecisionObservationProjector.ToCombat(snapshot),
            legalActions);
        var searchPoint = new CombatSearchPoint(
            snapshot,
            DecisionObservationProjector.ToRun(snapshot),
            decision);
        searchPoint.Validate();
        return searchPoint;
    }

    public static IReadOnlyList<CombatActionDescriptor> GetLegalActions(CombatState state)
    {
        ArgumentNullException.ThrowIfNull(state);
        var actions = new List<CombatActionDescriptor>();
        var isMultiplayer = state.Players.Count > 1;

        foreach (var player in state.Players.OrderBy(player => player.NetId))
        {
            var combatState = player.PlayerCombatState
                ?? throw new InvalidDataException($"Player {player.NetId} has no combat state.");
            if (combatState.Phase != PlayerTurnPhase.Play)
            {
                continue;
            }

            foreach (var card in combatState.Hand.Cards)
            {
                if (!card.CanPlay())
                {
                    continue;
                }

                var cardId = NetCombatCard.FromModel(card).CombatCardIndex;
                if (RequiresCreatureSelection(card.TargetType, isMultiplayer))
                {
                    foreach (var target in state.Creatures)
                    {
                        if (target.CombatId is { } targetId && card.CanPlayTargeting(target))
                        {
                            actions.Add(new CombatActionDescriptor(
                                CombatActionKind.PlayCard,
                                player.NetId,
                                cardId,
                                TargetCreatureId: targetId));
                        }
                    }
                }
                else
                {
                    actions.Add(new CombatActionDescriptor(
                        CombatActionKind.PlayCard,
                        player.NetId,
                        cardId));
                }
            }

            actions.Add(new CombatActionDescriptor(CombatActionKind.EndTurn, player.NetId));
        }

        return actions
            .OrderBy(action => action.ActorPlayerId)
            .ThenBy(action => action.Kind)
            .ThenBy(action => action.CombatCardIndex)
            .ThenBy(action => action.TargetCreatureId)
            .ToArray();
    }

    private static bool RequiresCreatureSelection(TargetType targetType, bool isMultiplayer) =>
        targetType is TargetType.AnyEnemy or TargetType.AnyAlly
        || (isMultiplayer && targetType == TargetType.AnyPlayer);

    private static CombatSnapshot MapSnapshot(
        CombatState state,
        NetFullCombatState nativeState,
        uint nativeChecksum,
        long decisionIndex)
    {
        var nativePlayers = nativeState.Players.ToDictionary(player => player.playerId);
        var players = state.Players
            .OrderBy(player => player.NetId)
            .Select(player => MapPlayer(player, nativePlayers[player.NetId]))
            .ToArray();

        if (state.Creatures.Count != nativeState.Creatures.Count)
        {
            throw new InvalidDataException("Live and native combat creature counts differ.");
        }

        var creatures = state.Creatures
            .Zip(nativeState.Creatures, MapCreature)
            .OrderBy(creature => creature.CombatId)
            .ToArray();

        return new CombatSnapshot(
            CombatSnapshot.CurrentSchemaVersion,
            Build,
            decisionIndex,
            state.RoundNumber,
            state.CurrentSide switch
            {
                MegaCrit.Sts2.Core.Combat.CombatSide.Player => ProtocolCombatSide.Player,
                MegaCrit.Sts2.Core.Combat.CombatSide.Enemy => ProtocolCombatSide.Enemy,
                _ => ProtocolCombatSide.Unknown,
            },
            players,
            creatures,
            MapRunRng(nativeState.Rng),
            new DeterminismCounters(
                nativeState.lastExecutedActionId,
                nativeState.lastExecutedHookId,
                nativeState.nextChoiceIds.ToArray(),
                nativeState.nextRewardIds.ToArray()),
            nativeChecksum);
    }

    private static PlayerCombatSnapshot MapPlayer(
        Player player,
        NetFullCombatState.PlayerState nativePlayer)
    {
        var nativePiles = nativePlayer.piles.ToDictionary(pile => pile.pileType);
        var combatState = player.PlayerCombatState
            ?? throw new InvalidDataException($"Player {player.NetId} has no combat state.");
        var piles = combatState.AllPiles
            .Select(pile => MapPile(pile, nativePiles[pile.Type]))
            .ToArray();

        return new PlayerCombatSnapshot(
            player.NetId,
            nativePlayer.characterId.ToString(),
            nativePlayer.energy,
            nativePlayer.stars,
            nativePlayer.gold,
            nativePlayer.turnNumber,
            nativePlayer.phase.ToString(),
            piles,
            nativePlayer.relics
                .Select(relic => new RelicSnapshot(
                    ModelIdString(relic.relic?.Id, "native relic"),
                    JsonSerializer.Serialize(relic.relic, NativeJsonOptions)))
                .ToArray(),
            nativePlayer.potions.Select(potion => potion.id.ToString()).ToArray(),
            nativePlayer.orbs
                .Select(orb => new OrbSnapshot(orb.id.ToString(), orb.passive, orb.evoke))
                .ToArray(),
            MapPlayerRng(nativePlayer.rngSet));
    }

    private static CombatPileSnapshot MapPile(
        CardPile pile,
        NetFullCombatState.CombatPileState nativePile)
    {
        if (pile.Cards.Count != nativePile.cards.Count)
        {
            throw new InvalidDataException($"Live and native {pile.Type} pile counts differ.");
        }

        var cards = pile.Cards.Zip(nativePile.cards, (card, nativeCard) =>
            new CardSnapshot(
                NetCombatCard.FromModel(card).CombatCardIndex,
                ModelIdString(nativeCard.card?.Id, "native card"),
                nativeCard.energyCost,
                nativeCard.affliction?.ToString(),
                nativeCard.afflictionCount,
                (nativeCard.keywords ?? [])
                    .Select(keyword => keyword.ToString())
                    .Order(StringComparer.Ordinal)
                    .ToArray(),
                JsonSerializer.Serialize(nativeCard.card, NativeJsonOptions)))
            .ToArray();

        return new CombatPileSnapshot(pile.Type.ToString(), cards);
    }

    private static CreatureSnapshot MapCreature(
        MegaCrit.Sts2.Core.Entities.Creatures.Creature creature,
        NetFullCombatState.CreatureState nativeCreature)
    {
        var combatId = creature.CombatId
            ?? throw new InvalidDataException("Combat creature has no combat ID.");

        return new CreatureSnapshot(
            combatId,
            nativeCreature.playerId,
            nativeCreature.playerId is null ? nativeCreature.monsterId?.ToString() : null,
            nativeCreature.currentHp,
            nativeCreature.maxHp,
            nativeCreature.block,
            nativeCreature.powers
                .Select(power => new ModelAmountSnapshot(power.id.ToString(), power.amount))
                .ToArray());
    }

    private static RunRngSnapshot MapRunRng(MegaCrit.Sts2.Core.Saves.Runs.SerializableRunRngSet rng) =>
        new(
            rng.Seed ?? throw new InvalidDataException("Run RNG state has no seed."),
            rng.Rngs
                .OrderBy(pair => pair.Key.ToString(), StringComparer.Ordinal)
                .Select(pair => new NamedRngSnapshot(pair.Key.ToString(), MapRng(pair.Value)))
                .ToArray());

    private static PlayerRngSnapshot MapPlayerRng(SerializablePlayerRngSet rng) =>
        new(
            rng.Seed,
            rng.Rngs
                .OrderBy(pair => pair.Key.ToString(), StringComparer.Ordinal)
                .Select(pair => new NamedRngSnapshot(pair.Key.ToString(), MapRng(pair.Value)))
                .ToArray());

    private static RngSnapshot MapRng(SerializableRng rng) =>
        new(rng.counter, rng.state0, rng.state1, rng.state2, rng.state3);

    private static string ModelIdString(ModelId? modelId, string source) =>
        modelId?.ToString()
        ?? throw new InvalidDataException($"{source} has no model ID.");

    private static void WriteDecisionPoint(CombatSearchPoint searchPoint)
    {
        var decision = searchPoint.Decision;
        var fingerprint = decision.StateFingerprint;
        var outputDirectory = GetOutputDirectory();
        Directory.CreateDirectory(outputDirectory);
        var json = ProtocolJson.Serialize(decision);
        var latestPath = Path.Combine(outputDirectory, "latest-combat-decision.json");
        var temporaryPath = latestPath + ".tmp";
        File.WriteAllText(temporaryPath, json);
        File.Move(temporaryPath, latestPath, overwrite: true);

        if (string.Equals(
                RuntimeConfiguration.Get("SLAY_THE_MODEL_CAPTURE_HISTORY"),
                "1",
                StringComparison.Ordinal))
        {
            var historyPath = Path.Combine(
                outputDirectory,
                $"decision-{decision.DecisionIndex:D8}-{fingerprint[..12]}.json");
            File.WriteAllText(historyPath, json);
        }

        Console.WriteLine(
            $"[SlayTheModel] captured decision {decision.DecisionIndex} "
            + $"actions={decision.LegalActions.Count} "
            + $"checksum={searchPoint.SimulatorState.NativeChecksum} "
            + $"fingerprint={fingerprint[..12]}");
    }

    public static string GetOutputDirectory()
    {
        var configured = RuntimeConfiguration.Get("SLAY_THE_MODEL_EXPORT_DIR");
        return string.IsNullOrWhiteSpace(configured)
            ? Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
                "SlayTheModel",
                "capture")
            : Path.GetFullPath(configured);
    }

    private static BuildIdentity CreateBuildIdentity()
    {
        var assembly = typeof(RunState).Assembly;
        using var stream = File.OpenRead(assembly.Location);
        var sha256 = Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
        return new BuildIdentity(
            GameVersion,
            sha256,
            assembly.ManifestModule.ModuleVersionId.ToString("D"));
    }
}
