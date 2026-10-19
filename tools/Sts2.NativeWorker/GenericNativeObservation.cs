using System.Text.Json;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Entities.Multiplayer;
using MegaCrit.Sts2.Core.Models;
using MegaCrit.Sts2.Core.Multiplayer.Serialization;
using MegaCrit.Sts2.Core.MonsterMoves.Intents;
using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;

public sealed partial class NativeSession
{
    // Live root only. Never call this from a simulated branch or a prior callback.
    public object ExportGenericObservation(IReadOnlyList<CombatSolverMctsAction> actions, int initialHp, int decisions)
    {
        var observation = CombatCaptureService.BuildObservation(_state, decisions);
        observation.Validate();
        var allCards = _player.PlayerCombatState!.AllPiles.SelectMany(p => p.Cards).ToArray();
        object Card(CardModel c) => new {
            model = c.Id.Entry, upgrade = c.CurrentUpgradeLevel,
            cost = c.EnergyCost.GetWithModifiers(CostModifiers.Local),
            type = c.Type.ToString(), target = c.TargetType.ToString(),
            keywords = c.Keywords.Select(k => k.ToString()).Order().ToArray(),
            enchantment = c.Enchantment?.Id.Entry, affliction = c.Affliction?.Id.Entry,
            variables = CombatSolver.Api.NativeGenericCardFeatures.Variables(c)
        };
        object Features(SearchAction a) => a.Selection is { } selected
            ? (object)new { kind = "Choose", selected = selected.Select(i => new { index = i, card = Card(_options[i]) }).ToArray() }
            : new { kind = a.Combat!.Kind.ToString(),
                source = a.Combat.CombatCardIndex is uint id
                    ? Card(allCards.Single(c => NetCombatCard.FromModel(c).CombatCardIndex == id)) : null,
                target = a.Combat.TargetCreatureId,
                potion = a.Combat.PotionIndex };
        var candidates = actions.Select(a => new { Key = a.Key, features = Features(ToLiveSearchAction(a)) }).ToArray();
        // Exact semantic action-class coverage, including all live selector combinations.
        // Native selector legality is set-valued (NativeSession.StepAsync uses the same
        // sorted-index comparison). Preserve execution order in exported features.
        // Search merges equivalent copies by their complete semantic state key.
        // Compare multisets of those keys, never merely names or option indices.
        string LegalClass(SearchAction a) => a.Selection is { } s
            ? "Choose:" + CombatSolver.Api.NativeMctsSimulationApi.LiveSelectionSemanticKey(_options,s)
            : JsonSerializer.Serialize(Features(a));
        var actual = Actions().Select(LegalClass).ToHashSet();
        var predicted = actions.Select(a => LegalClass(ToLiveSearchAction(a))).ToHashSet();
        if (!actual.SetEquals(predicted))
            throw new InvalidDataException($"MCTS/live legal-action coverage mismatch at decision {decisions}: missing={string.Join(";", actual.Except(predicted))} extra={string.Join(";", predicted.Except(actual))}");
        return new {
            version = "native-generic-observation-v1", initialHp, decisions, observation,
            cards = allCards.Select(c => new { index = NetCombatCard.FromModel(c).CombatCardIndex, data = Card(c) }).ToArray(),
            intents = _state.Enemies.Select(e => new { target = e.CombatId,
                intents = e.Monster!.NextMove.Intents.Select(i => new { kind = i.GetType().Name,
                    damage = i is AttackIntent attack ? attack.GetTotalDamage([_player.Creature], e) : 0 }).ToArray() }).ToArray(),
            choice = _choice == null ? null : (object)new { min = Math.Min(_min, _options.Length), max = Math.Min(_max, _options.Length), options = _options.Select(Card).ToArray() },
            actions = candidates
        };
    }
}
