using System.Reflection;
using System.Runtime.CompilerServices;
using System.Text.Json;
using HarmonyLib;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Models.Cards;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using SlayTheModel.Collector;
using SlayTheModel.Sts2.DataCollector;
using SlayTheModel.Sts2.ModAdapter;

// The state projector and journal sink are isolated doubles. Completion,
// reference mapping, confirmation, receipt and teardown logic is production.
var checks = 0;
void Check(bool condition, string message)
{
    checks++;
    if (!condition) throw new Exception(message + ": " + string.Join(",", CollectorRuntime.Gaps));
}

var nativeComplete = AccessTools.Method(typeof(NSimpleCardSelectScreen), "CompleteSelection")!;
var patcher = new Harmony("SlayTheModel.MctsChoiceCapture.Smoke");
patcher.Patch(nativeComplete, prefix: new HarmonyMethod(typeof(CollectorRuntime), nameof(CollectorRuntime.TestConfirmPrefix)));
Check(Harmony.GetPatchInfo(nativeComplete)!.Prefixes.Any(patch => patch.owner == patcher.Id), "native simple confirmation ABI");
patcher.Unpatch(nativeComplete, HarmonyPatchType.All, patcher.Id);

var cards = Enumerable.Range(0, 3).Select(_ => (CardModel)RuntimeHelpers.GetUninitializedObject(typeof(StrikeIronclad))).ToArray();
var automatic = CollectorRuntime.TestBegin(cards);
CollectorRuntime.ObserveMctsCardChoiceCompleted(automatic.Selector, [cards[1]], null);
CollectorRuntime.TestCombatEnd();
Check(CollectorRuntime.Commits.Count == 1 && CollectorRuntime.Gaps.Count == 0, "callback receipt needs no nonexistent native receipt");
Check(CollectorRuntime.Commits[0]!.Actor == ActionActor.Policy && CollectorRuntime.Commits[0]!.PolicyId == "native-mcts", "automated source retained");
CollectorRuntime.ObserveMctsCardChoiceCompleted(automatic.Selector, [cards[1]], null);
Check(CollectorRuntime.Commits.Count == 1, "duplicate callback ignored");

automatic = CollectorRuntime.TestBegin(cards);
CollectorRuntime.ObserveMctsCardChoiceCompleted(automatic.Selector, [], null);
Check(CollectorRuntime.Commits.Count == 1 && CollectorRuntime.Gaps.Count == 0, "valid zero policy choice");

foreach (var selected in new[] { new[] { cards[1] }, Array.Empty<CardModel>() })
{
    var fallback = CollectorRuntime.TestBegin(cards);
    var ui = new object();
    CollectorRuntime.ObserveMctsCardChoiceManualFallback(fallback.Selector, ui);
    CollectorRuntime.ObserveHandChoiceConfirmation(ui, selected);
    CollectorRuntime.AttachCombatChoiceTask(fallback, Task.FromResult<IEnumerable<CardModel>>(selected));
    Check(CollectorRuntime.Commits.Count == 0, "UI task alone does not finish MCTS callback");
    CollectorRuntime.ObserveMctsCardChoiceCompleted(fallback.Selector, selected, null);
    CollectorRuntime.TestCombatEnd();
    Check(CollectorRuntime.Commits.Count == 1 && CollectorRuntime.Gaps.Count == 0, "manual fallback including explicit empty confirmation");
    Check(CollectorRuntime.Commits[0]!.Actor == ActionActor.Human, "fallback source human only after input evidence");
}

var missing = CollectorRuntime.TestBegin(cards);
var missingUi = new object();
CollectorRuntime.ObserveMctsCardChoiceManualFallback(missing.Selector, missingUi);
CollectorRuntime.AttachCombatChoiceTask(missing, Task.FromResult<IEnumerable<CardModel>>([]));
CollectorRuntime.ObserveMctsCardChoiceCompleted(missing.Selector, [], null);
Check(CollectorRuntime.Commits.Count == 0 && CollectorRuntime.Gaps.Contains("combat_choice_without_manual_input_evidence"), "unconfirmed empty result is not human input");

var mismatch = CollectorRuntime.TestBegin(cards);
var mismatchUi = new object();
CollectorRuntime.ObserveMctsCardChoiceManualFallback(mismatch.Selector, mismatchUi);
CollectorRuntime.ObserveHandChoiceConfirmation(mismatchUi, [cards[0]]);
CollectorRuntime.AttachCombatChoiceTask(mismatch, Task.FromResult<IEnumerable<CardModel>>([cards[1]]));
CollectorRuntime.ObserveMctsCardChoiceCompleted(mismatch.Selector, [cards[1]], null);
Check(CollectorRuntime.Commits.Count == 0 && CollectorRuntime.Gaps.Contains("combat_choice_hand_confirmation_mismatch"), "confirmation differs from returned cards");

mismatch = CollectorRuntime.TestBegin(cards);
mismatchUi = new object();
CollectorRuntime.ObserveMctsCardChoiceManualFallback(mismatch.Selector, mismatchUi);
CollectorRuntime.ObserveHandChoiceConfirmation(mismatchUi, [cards[0]]);
CollectorRuntime.AttachCombatChoiceTask(mismatch, Task.FromResult<IEnumerable<CardModel>>([cards[0]]));
CollectorRuntime.ObserveMctsCardChoiceCompleted(mismatch.Selector, [cards[1]], null);
Check(CollectorRuntime.Commits.Count == 0 && CollectorRuntime.Gaps.Contains("combat_choice_task_failed"), "UI and selector callback differ");

foreach (var failure in new Exception[] { new OperationCanceledException(), new InvalidOperationException("worker failed") })
{
    var pending = CollectorRuntime.TestBegin(cards);
    CollectorRuntime.ObserveMctsCardChoiceCompleted(pending.Selector, null, failure);
    Check(CollectorRuntime.Commits.Count == 0 && CollectorRuntime.Gaps.Contains("combat_choice_task_failed"), "failed callback excluded");
}
var unfinished = CollectorRuntime.TestBegin(cards);
CollectorRuntime.TestCombatEnd();
CollectorRuntime.ObserveMctsCardChoiceCompleted(unfinished.Selector, [], null);
Check(CollectorRuntime.Commits.Count == 0 && CollectorRuntime.Gaps.Count == 1, "unfinished callback remains gap and late result ignored");

var invalid = CollectorRuntime.TestBegin(cards);
CollectorRuntime.ObserveMctsCardChoiceCompleted(invalid.Selector, [cards[0], cards[0]], null);
Check(CollectorRuntime.Commits.Count == 0 && CollectorRuntime.Gaps.Contains("combat_choice_result_reference_unmatched"), "duplicate object cannot select same card twice");

var legacy = CollectorRuntime.TestBegin(cards, mcts: false);
CollectorRuntime.MarkCombatChoiceManualInput(legacy.Selector);
CollectorRuntime.CompleteCombatChoice(legacy, [cards[0]]);
CollectorRuntime.TestCombatEnd();
Check(CollectorRuntime.Gaps.Contains("combat_choice_native_result_missing"), "ordinary UI still requires native receipt");

var observed = 0;
Action<object, CardModel[], int, int> throwing = (_, _, _, _) => throw new InvalidOperationException("expected observer failure");
Action<object, CardModel[], int, int> succeeding = (_, received, _, _) => { received[0] = cards[1]; observed++; };
PolicyDecisionTelemetry.CardChoiceRequested += throwing;
PolicyDecisionTelemetry.CardChoiceRequested += succeeding;
PolicyDecisionTelemetry.NotifyCardChoiceRequested(new object(), cards, 0, 3);
PolicyDecisionTelemetry.CardChoiceRequested -= throwing;
PolicyDecisionTelemetry.CardChoiceRequested -= succeeding;
Check(observed == 1 && !ReferenceEquals(cards[0], cards[1]), "observer failures and array edits do not mutate game input");
Console.WriteLine($"mcts_choice_capture_smoke=ok assertions={checks} native_card_objects=true lifecycle=simulated game_started=false");
