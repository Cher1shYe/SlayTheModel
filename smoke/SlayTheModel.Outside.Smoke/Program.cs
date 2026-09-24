using SlayTheModel.Sts2.Protocol;

var start = new OutsideMapCoordinate(0, 0);
var next = new OutsideMapCoordinate(1, 0);
var build = new BuildIdentity(
    "v0.111.0",
    new string('a', 64),
    Guid.Empty.ToString("D"));
var choiceContext = new OutsideCombatChoiceContext(
    ContextId: "card_selection:CardSelection:Remove",
    StateToken: new string('b', 64),
    Phase: OutsideCombatChoicePhase.Selection,
    MinSelections: 1,
    MaxSelections: 1,
    SelectedCount: 0,
    Cancelable: true,
    RequiresConfirmation: true);
var observation = new OutsideCombatObservation(
    OutsideCombatObservation.CurrentSchemaVersion,
    OutsideCombatSurfaceKind.MerchantCardRemoval,
    choiceContext,
    ActIndex: 0,
    ActFloor: 4,
    TotalFloor: 4,
    AscensionLevel: 0,
    RoomType: "Merchant",
    RoomModelId: null,
    CurrentMapCoordinate: start,
    Players:
    [
        new OutsideRunPlayerObservation(
            PlayerId: 1,
            CharacterId: "IRONCLAD",
            CurrentHp: 63,
            MaxHp: 80,
            Gold: 125,
            MaxPotionCount: 3,
            Deck:
            [
                new OutsideRunCardObservation(0, "ANGER", 0, null, null),
                new OutsideRunCardObservation(1, "DEFEND", 0, null, null),
                new OutsideRunCardObservation(2, "STRIKE", 0, null, null),
            ],
            Relics:
            [
                new OutsideRunRelicObservation(
                    "BURNING_BLOOD",
                    StackCount: 1,
                    IsUsedUp: false,
                    Status: "Active",
                    DisplayAmount: 0),
            ],
            Potions: [new PotionObservation(0, "BLOCK_POTION")]),
    ],
    MapPoints:
    [
        new OutsideMapPointObservation(start, "Monster", true, [next]),
        new OutsideMapPointObservation(next, "Merchant", false, []),
    ]);

// Native discovery order is deliberately not the merchant policy order. The
// policy owns the Strike -> Defend -> model-ID special case.
var legalActions = new OutsideCombatActionDescriptor[]
{
    new("remove_card:0:ANGER", OutsideCombatActionKind.RemoveCard, 0, "ANGER", TargetDeckIndex: 0),
    new("remove_card:1:DEFEND", OutsideCombatActionKind.RemoveCard, 1, "DEFEND", TargetDeckIndex: 1),
    new("remove_card:2:STRIKE", OutsideCombatActionKind.RemoveCard, 2, "STRIKE", TargetDeckIndex: 2),
    new("cancel_selection:3:-", OutsideCombatActionKind.CancelSelection, 3),
};
var fingerprint = ProtocolJson.ComputeOutsideStateFingerprint(build, observation, legalActions);
const string expectedFingerprint =
    "0ca6fc3d7ff778af0ec4b1ce4d6335e228618ee3c1b8eb066a958baa3893412c";
if (fingerprint != expectedFingerprint)
    throw new Exception(
        $"Outside fingerprint contract changed without a schema update: {fingerprint}.");
var decision = new OutsideCombatDecisionPoint(
    OutsideCombatDecisionPoint.CurrentSchemaVersion,
    build,
    DecisionIndex: 7,
    fingerprint,
    observation,
    legalActions);
decision.Validate();

IOutsideCombatPolicy policy = new FirstLegalOutsideCombatPolicy();
var selected = policy.SelectAction(decision);
if (selected.TargetId != "STRIKE")
    throw new Exception("Merchant removal must prefer Strike over native discovery order.");

var noStrike = decision with
{
    LegalActions = legalActions[..2],
    StateFingerprint = ProtocolJson.ComputeOutsideStateFingerprint(build, observation, legalActions[..2]),
};
if (policy.SelectAction(noStrike).TargetId != "DEFEND")
    throw new Exception("Merchant removal must fall back from Strike to Defend.");

var previewActions = new OutsideCombatActionDescriptor[]
{
    new("confirm:0:-", OutsideCombatActionKind.Confirm, 0),
    new("back_to_selection:1:-", OutsideCombatActionKind.BackToSelection, 1),
};
var previewDecision = decision with
{
    LegalActions = previewActions,
    StateFingerprint = ProtocolJson.ComputeOutsideStateFingerprint(
        build,
        observation,
        previewActions),
};
previewDecision.Validate();
if (policy.SelectAction(previewDecision).Kind != OutsideCombatActionKind.Confirm)
    throw new Exception("First-legal must confirm before returning from selection preview.");

var ordinaryActions = new OutsideCombatActionDescriptor[]
{
    new("event:0", OutsideCombatActionKind.ChooseEventOption, 0, "OPTION_A"),
    new("event:1", OutsideCombatActionKind.ChooseEventOption, 1, "OPTION_B"),
};
var ordinary = decision with
{
    Observation = observation with { Surface = OutsideCombatSurfaceKind.Event },
    LegalActions = ordinaryActions,
    StateFingerprint = ProtocolJson.ComputeOutsideStateFingerprint(
        build,
        observation with { Surface = OutsideCombatSurfaceKind.Event },
        ordinaryActions),
};
if (policy.SelectAction(ordinary).Ordinal != 0)
    throw new Exception("First-legal must select ordinal zero outside merchant removal.");

// Every surface is represented by the same protocol envelope. These fixtures
// protect the action shapes that a future trainer/headless runner will consume,
// without loading Godot or the game assembly.
var surfaceFixtures = new (OutsideCombatSurfaceKind Surface, OutsideCombatActionDescriptor Action)[]
{
    (OutsideCombatSurfaceKind.Rewards,
        new("reward:0", OutsideCombatActionKind.ClaimReward, 0, "CardReward")),
    (OutsideCombatSurfaceKind.CardReward,
        new("card_reward:0:BASH", OutsideCombatActionKind.ChooseCard, 0, "BASH")),
    (OutsideCombatSurfaceKind.CardChoice,
        new("card_choice:0:BASH", OutsideCombatActionKind.ChooseCard, 0, "BASH")),
    (OutsideCombatSurfaceKind.CardBundleChoice,
        new("bundle:0", OutsideCombatActionKind.ChooseCardBundle, 0, "STARTER_BUNDLE")),
    (OutsideCombatSurfaceKind.RelicChoice,
        new("relic:0", OutsideCombatActionKind.ChooseRelic, 0, "BURNING_BLOOD")),
    (OutsideCombatSurfaceKind.CardGridChoice,
        new("grid:0:BASH", OutsideCombatActionKind.ChooseCard, 0, "BASH")),
    (OutsideCombatSurfaceKind.Event,
        new("event:0", OutsideCombatActionKind.ChooseEventOption, 0, "OPTION_A")),
    (OutsideCombatSurfaceKind.RestSite,
        new("rest:0", OutsideCombatActionKind.ChooseRestSiteOption, 0, "REST")),
    (OutsideCombatSurfaceKind.Merchant,
        new("merchant:leave", OutsideCombatActionKind.LeaveMerchant, 0)),
    (OutsideCombatSurfaceKind.Treasure,
        new("treasure:open", OutsideCombatActionKind.OpenChest, 0, "CHEST")),
    (OutsideCombatSurfaceKind.Map,
        new("map:1:0", OutsideCombatActionKind.Travel, 0, MapCoordinate: next)),
    (OutsideCombatSurfaceKind.CrystalSphere,
        new("sphere:0", OutsideCombatActionKind.ChooseMinigameOption, 0, "CELL_0")),
};
foreach (var (surface, action) in surfaceFixtures)
{
    var fixtureObservation = observation with { Surface = surface };
    OutsideCombatActionDescriptor[] fixtureActions = [action];
    var fixture = new OutsideCombatDecisionPoint(
        OutsideCombatDecisionPoint.CurrentSchemaVersion,
        build,
        DecisionIndex: 8,
        ProtocolJson.ComputeOutsideStateFingerprint(build, fixtureObservation, fixtureActions),
        fixtureObservation,
        fixtureActions);
    fixture.Validate();
    if (policy.SelectAction(fixture).ActionId != action.ActionId)
        throw new Exception($"First-legal failed the {surface} action fixture.");
}

var step = new OutsideCombatStepRequest(Guid.NewGuid(), fingerprint, selected.ActionId);
if (OutsideCombatStepGuard.RequireCurrentAction(step, decision) != selected)
    throw new Exception("Step guard did not resolve the selected semantic action.");

var sample = new OutsideCombatDecisionSample(
    OutsideCombatDecisionSample.CurrentSchemaVersion,
    Guid.NewGuid(),
    policy.PolicyId,
    decision,
    step);
sample.Validate();
var execution = new OutsideCombatExecutionResult(
    OutsideCombatExecutionResult.CurrentSchemaVersion,
    sample.EpisodeId,
    decision.DecisionIndex,
    policy.PolicyId,
    step.RequestId,
    step.ExpectedStateFingerprint,
    step.ActionId,
    OutsideCombatExecutionStatus.Applied);
execution.Validate();
var executionJson = ProtocolJson.Serialize(execution);
ProtocolJson.Deserialize<OutsideCombatExecutionResult>(executionJson).Validate();
if (!executionJson.Contains("\"status\":\"applied\"", StringComparison.Ordinal))
    throw new Exception("Outside execution result JSON contract is invalid.");
try
{
    (execution with { Status = OutsideCombatExecutionStatus.Failed }).Validate();
    throw new Exception("A failed outside execution without diagnostics was accepted.");
}
catch (InvalidDataException) { }
var json = ProtocolJson.Serialize(sample);
if (!json.Contains("\"surface\":\"merchant_card_removal\"", StringComparison.Ordinal)
    || !json.Contains("\"kind\":\"remove_card\"", StringComparison.Ordinal))
    throw new Exception("Outside protocol JSON is not using the expected snake-case contract.");
if (json.Contains("Godot", StringComparison.OrdinalIgnoreCase)
    || json.Contains("node_path", StringComparison.OrdinalIgnoreCase)
    || json.Contains("instance_id", StringComparison.OrdinalIgnoreCase)
    || json.Contains("native_json", StringComparison.OrdinalIgnoreCase))
    throw new Exception("Outside policy contract leaked native adapter state.");

const string expectedActionJson =
    "{\"action_id\":\"event:0\",\"kind\":\"choose_event_option\",\"ordinal\":0,"
    + "\"target_id\":\"OPTION_A\",\"map_coordinate\":null,\"cost\":null,"
    + "\"target_deck_index\":null}";
if (ProtocolJson.Serialize(ordinaryActions[0]) != expectedActionJson)
    throw new Exception("Outside action JSON contract changed without a schema update.");

var roundTrip = ProtocolJson.Deserialize<OutsideCombatDecisionSample>(json);
roundTrip.Validate();
if (ProtocolJson.Serialize(roundTrip) != json)
    throw new Exception("Outside decision sample JSON did not round-trip byte-stably.");
if (ProtocolJson.ComputeOutsideStateFingerprint(
        roundTrip.Decision.Build,
        roundTrip.Decision.Observation,
        roundTrip.Decision.LegalActions) != fingerprint)
    throw new Exception("Outside decision fingerprint changed after serialization.");

var reordered = legalActions.Reverse().Select((action, ordinal) => action with
{
    ActionId = $"reordered:{ordinal}:{action.TargetId}",
    Ordinal = ordinal,
}).ToArray();
if (ProtocolJson.ComputeOutsideStateFingerprint(build, observation, reordered) == fingerprint)
    throw new Exception("Changing the legal action contract must change the fingerprint.");

var previewContextObservation = observation with
{
    ChoiceContext = choiceContext with
    {
        Phase = OutsideCombatChoicePhase.Preview,
        StateToken = new string('c', 64),
        SelectedCount = 1,
    },
};
if (ProtocolJson.ComputeOutsideStateFingerprint(
        build,
        previewContextObservation,
        legalActions) == fingerprint)
    throw new Exception("Changing the choice phase must change the outside fingerprint.");

try
{
    (sample with { SchemaVersion = 99 }).Validate();
    throw new Exception("An unsupported outside sample schema was accepted.");
}
catch (InvalidDataException) { }

try
{
    OutsideCombatStepGuard.RequireCurrentAction(
        step with { ExpectedStateFingerprint = new string('a', 64) },
        decision);
    throw new Exception("A stale outside-combat step was accepted.");
}
catch (StaleOutsideCombatStateException) { }

try
{
    (decision with
    {
        Observation = observation with { TotalFloor = observation.TotalFloor + 1 },
    }).Validate();
    throw new Exception("A decision with a tampered payload fingerprint was accepted.");
}
catch (InvalidDataException) { }

try
{
    var mismatchedRemoval = legalActions.ToArray();
    mismatchedRemoval[0] = mismatchedRemoval[0] with { TargetDeckIndex = 1 };
    (decision with
    {
        LegalActions = mismatchedRemoval,
        StateFingerprint = ProtocolJson.ComputeOutsideStateFingerprint(
            build,
            observation,
            mismatchedRemoval),
    }).Validate();
    throw new Exception("A RemoveCard action targeting the wrong deck instance was accepted.");
}
catch (InvalidDataException) { }

try
{
    var outOfOrder = new[] { legalActions[1], legalActions[0], legalActions[2] };
    (decision with
    {
        LegalActions = outOfOrder,
        StateFingerprint = ProtocolJson.ComputeOutsideStateFingerprint(
            build,
            observation,
            outOfOrder),
    }).Validate();
    throw new Exception("Out-of-order outside action ordinals were accepted.");
}
catch (InvalidDataException) { }

try
{
    var duplicateIds = new[]
    {
        legalActions[0],
        legalActions[1] with { ActionId = legalActions[0].ActionId, Ordinal = 1 },
    };
    (decision with
    {
        LegalActions = duplicateIds,
        StateFingerprint = ProtocolJson.ComputeOutsideStateFingerprint(
            build,
            observation,
            duplicateIds),
    }).Validate();
    throw new Exception("Duplicate outside action IDs were accepted.");
}
catch (InvalidDataException) { }

Console.WriteLine(
    $"outside protocol: observation, map, legal actions, first-legal merchant priority, "
    + $"surface fixtures, stale guard, sample/result round-trip passed fingerprint={fingerprint[..12]}");
