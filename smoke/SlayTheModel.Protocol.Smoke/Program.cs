using SlayTheModel.Sts2.Protocol;

var card = new CardSnapshot(11, "Strike", 1, null, 0, [], "{\"id\":\"Strike\"}");
var player = new PlayerCombatSnapshot(
    7,
    "Ironclad",
    3,
    0,
    99,
    1,
    "play",
    [new CombatPileSnapshot("hand", [card])],
    [],
    [],
    [],
    new PlayerRngSnapshot(7, []));
var playerCreature = new CreatureSnapshot(7, 7, null, 70, 80, 0, []);
var enemy = new CreatureSnapshot(42, null, "JawWorm", 40, 40, 0, []);
var state = new CombatSnapshot(
    CombatSnapshot.CurrentSchemaVersion,
    new BuildIdentity("v0.111.0", new string('a', 64), Guid.Empty.ToString("D")),
    0,
    1,
    CombatSide.Player,
    [player],
    [playerCreature, enemy],
    new RunRngSnapshot("smoke", [new NamedRngSnapshot("shuffle", new RngSnapshot(0, 1, 2, 3, 4))]),
    new DeterminismCounters(null, null, [0], [0]),
    1234);
var fingerprint = ProtocolJson.ComputeStateFingerprint(state);
var decision = new CombatDecisionPoint(
    CombatDecisionPoint.CurrentSchemaVersion,
    state.DecisionIndex,
    fingerprint,
    DecisionObservationProjector.ToCombat(state),
    [
        new CombatActionDescriptor(CombatActionKind.PlayCard, 7, 11, TargetCreatureId: 42),
        new CombatActionDescriptor(CombatActionKind.EndTurn, 7),
    ]);
var searchPoint = new CombatSearchPoint(
    state,
    DecisionObservationProjector.ToRun(state),
    decision);

searchPoint.Validate();
var before = decision.StateFingerprint;
var json = ProtocolJson.Serialize(decision);
var roundTripped = ProtocolJson.Deserialize<CombatDecisionPoint>(json);
roundTripped.Validate();
var after = roundTripped.StateFingerprint;

if (!string.Equals(before, after, StringComparison.Ordinal))
{
    throw new InvalidOperationException("Protocol fingerprint changed after JSON round-trip.");
}

var recaptured = ProtocolJson.ComputeStateFingerprint(state with { DecisionIndex = 999 });
if (!string.Equals(before, recaptured, StringComparison.Ordinal))
{
    throw new InvalidOperationException("Capture sequence number changed the semantic state fingerprint.");
}

var changedPlayer = state.Players[0] with { Energy = 2 };
var changedState = state with { Players = [changedPlayer] };
if (string.Equals(before, ProtocolJson.ComputeStateFingerprint(changedState), StringComparison.Ordinal))
{
    throw new InvalidOperationException("A semantic state change did not change the fingerprint.");
}

var step = new CombatStepRequest(Guid.NewGuid(), before, decision.LegalActions[0]);
CombatStepGuard.RequireExpectedState(step, state);
var staleWasRejected = false;
try
{
    CombatStepGuard.RequireExpectedState(step, changedState);
}
catch (StaleCombatStateException)
{
    staleWasRejected = true;
}

if (!staleWasRejected)
{
    throw new InvalidOperationException("A stale combat action was not rejected.");
}

if (!json.Contains("\"gold\":99", StringComparison.Ordinal)
    || json.Contains("run_rng", StringComparison.Ordinal)
    || json.Contains("native_card_json", StringComparison.Ordinal))
{
    throw new InvalidOperationException("Combat policy payload lost visible gold or leaked simulator state.");
}

var legacyObservation = decision.Observation with
{
    SchemaVersion = 1,
    Players = decision.Observation.Players
        .Select(combatPlayer => combatPlayer with { Gold = null })
        .ToArray(),
};
ProtocolJson.Deserialize<CombatObservation>(
    ProtocolJson.Serialize(legacyObservation)).Validate();

// Previously published v4 episodes keep their UI-derived hand display.
// The v5 reader must continue accepting that historical observation.
var legacyVisibleHand = decision.Observation with
{
    SchemaVersion = 4,
    Players = decision.Observation.Players.Select(combatPlayer => combatPlayer with
    {
        Piles = combatPlayer.Piles.Select(pile => pile with
        {
            Cards = pile.Cards.Select(oldCard => oldCard with
            {
                Display = new CombatCardDisplayObservation(
                    "Deal 6 damage.", 1, 0, false, []),
            }).ToArray(),
        }).ToArray(),
    }).ToArray(),
};
ProtocolJson.Deserialize<CombatObservation>(
    ProtocolJson.Serialize(legacyVisibleHand)).Validate();

var visibleRelicObservation = decision.Observation with
{
    Players = decision.Observation.Players.Select(combatPlayer => combatPlayer with
    {
        Relics = [new RelicObservation("PEN_NIB")
        {
            Display = new RelicDisplayObservation(
                "Active", IsMelted: false, IsWax: false,
                VisibleCounter: 0, HoverDescription: "Next attack deals double damage."),
        }],
    }).ToArray(),
};
visibleRelicObservation.Validate();
var visibleRelicJson = ProtocolJson.Serialize(visibleRelicObservation);
if (!visibleRelicJson.Contains("\"visible_counter\":0", StringComparison.Ordinal)
    || visibleRelicJson.Contains("stack_count", StringComparison.Ordinal)
    || visibleRelicJson.Contains("display_amount", StringComparison.Ordinal))
{
    throw new InvalidOperationException("Combat v3 lost a visible relic zero or exposed native relic state.");
}
ProtocolJson.Deserialize<CombatObservation>(visibleRelicJson).Validate();

var enchantedCard = decision.Observation.Players[0].Piles[0].Cards[0] with
{
    EnchantmentId = "SHARP",
    EnchantmentDisplay = new CardEnchantmentDisplayObservation(
        "Sharp", "Increases damage.", VisibleAmount: 2, "normal"),
};
var enchantedObservation = decision.Observation with
{
    Players = decision.Observation.Players.Select(combatPlayer => combatPlayer with
    {
        Piles = combatPlayer.Piles.Select(pile => pile with
        {
            Cards = [enchantedCard],
        }).ToArray(),
    }).ToArray(),
};
enchantedObservation.Validate();
var enchantedJson = ProtocolJson.Serialize(enchantedObservation);
if (!enchantedJson.Contains("\"visible_amount\":2", StringComparison.Ordinal)
    || !enchantedJson.Contains("\"enchantment_amount\":null", StringComparison.Ordinal))
{
    throw new InvalidOperationException("Combat v4 lost a visible enchantment amount or exposed raw amount.");
}
ProtocolJson.Deserialize<CombatObservation>(enchantedJson).Validate();
var rawEnchantmentRejected = false;
try
{
    (enchantedObservation with
    {
        Players = enchantedObservation.Players.Select(combatPlayer => combatPlayer with
        {
            Piles = combatPlayer.Piles.Select(pile => pile with
            {
                Cards = [enchantedCard with { EnchantmentAmount = 2 }],
            }).ToArray(),
        }).ToArray(),
    }).Validate();
}
catch (InvalidDataException)
{
    rawEnchantmentRejected = true;
}
if (!rawEnchantmentRejected)
{
    throw new InvalidOperationException("Combat v4 accepted a native enchantment amount.");
}
var legacyEnchantmentObservation = enchantedObservation with
{
    SchemaVersion = 3,
    Players = enchantedObservation.Players.Select(combatPlayer => combatPlayer with
    {
        Piles = combatPlayer.Piles.Select(pile => pile with
        {
            Cards = [enchantedCard with
            {
                EnchantmentAmount = 2,
                EnchantmentDisplay = null,
            }],
        }).ToArray(),
    }).ToArray(),
};
var legacyEnchantmentJson = ProtocolJson.Serialize(legacyEnchantmentObservation);
var parsedLegacyEnchantment = ProtocolJson.Deserialize<CombatObservation>(
    legacyEnchantmentJson);
parsedLegacyEnchantment.Validate();
if (ProtocolJson.Serialize(parsedLegacyEnchantment) != legacyEnchantmentJson)
{
    throw new InvalidOperationException("Legacy v3 enchantment observation did not round-trip byte-stably.");
}
ProtocolJson.Deserialize<CombatObservation>(ProtocolJson.Serialize(
    visibleRelicObservation with
    {
        SchemaVersion = 2,
        Players = visibleRelicObservation.Players.Select(combatPlayer => combatPlayer with
        {
            Relics = [new RelicObservation("PEN_NIB")],
        }).ToArray(),
    })).Validate();

var runJson = ProtocolJson.Serialize(searchPoint.RunObservation);
if (!runJson.Contains("\"gold\":99", StringComparison.Ordinal))
{
    throw new InvalidOperationException("Run observation did not retain player gold.");
}

var sparsePlayer = player with
{
    Potions = ["BLOCK_POTION", "FIRE_POTION"],
    PotionSlotIndexes = [0, 2],
};
var sparseState = state with { Players = [sparsePlayer] };
var sparseCombat = DecisionObservationProjector.ToCombat(sparseState);
var sparseRun = DecisionObservationProjector.ToRun(sparseState);
var expectedPotionSlots = new[] { 0, 2 };
if (!sparseCombat.Players[0].Potions.Select(potion => potion.SlotIndex)
        .SequenceEqual(expectedPotionSlots)
    || !sparseRun.Players[0].Potions.Select(potion => potion.SlotIndex)
        .SequenceEqual(expectedPotionSlots)
    || sparseCombat.Players[0].Potions[1].ModelId != "FIRE_POTION")
{
    throw new InvalidOperationException("A sparse potion slot was compacted in a policy observation.");
}

var sparseDecision = new CombatDecisionPoint(
    CombatDecisionPoint.CurrentSchemaVersion,
    sparseState.DecisionIndex,
    ProtocolJson.ComputeStateFingerprint(sparseState),
    sparseCombat,
    [new CombatActionDescriptor(CombatActionKind.UsePotion, 7, PotionIndex: 2)]);
sparseDecision.Validate();
if (ProtocolJson.ComputeStateFingerprint(
        sparseState with
        {
            Players = [sparsePlayer with { PotionSlotIndexes = [0, 1] }],
        }) == sparseDecision.StateFingerprint)
{
    throw new InvalidOperationException("A physical potion slot change did not change the fingerprint.");
}

var legacyMisalignedDecision = sparseDecision with
{
    LegalActions = [new CombatActionDescriptor(CombatActionKind.UsePotion, 7, PotionIndex: 1)],
};
legacyMisalignedDecision.Validate();
try
{
    legacyMisalignedDecision.ValidatePotionActionReferences();
    throw new InvalidOperationException("New capture accepted an absent potion slot.");
}
catch (InvalidDataException)
{
    // Old decisions remain readable, but no new writer may publish this mismatch.
}

if (ProtocolJson.Serialize(player).Contains("potion_slot_indexes", StringComparison.Ordinal))
{
    throw new InvalidOperationException("Legacy snapshots changed their serialized fingerprint input.");
}

Console.WriteLine($"schema={roundTripped.SchemaVersion}");
Console.WriteLine($"actions={roundTripped.LegalActions.Count}");
Console.WriteLine($"fingerprint={after}");
