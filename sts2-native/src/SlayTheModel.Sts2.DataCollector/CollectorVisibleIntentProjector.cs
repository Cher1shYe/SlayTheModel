using System.Reflection;
using Godot;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Entities.Creatures;
using MegaCrit.Sts2.Core.MonsterMoves.Intents;
using MegaCrit.Sts2.Core.Nodes.Combat;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.DataCollector;

/// <summary>
/// Reads only enemy intent icons that the live UI has already rendered. A
/// monster's NextMove can be rolled before its icon appears, so the model is
/// used only to verify each visible icon's identity and calculate displayed
/// attack values; it is never used as the visibility source.
/// </summary>
internal static class CollectorVisibleIntentProjector
{
    private const float ReadableAlpha = 0.5f;

    private static readonly FieldInfo? IconIntentField = FindIconField("_intent");
    private static readonly FieldInfo? IconOwnerField = FindIconField("_owner");
    private static readonly FieldInfo? IconTargetsField = FindIconField("_targets");
    private static readonly FieldInfo? IconSpriteField = FindIconField("_intentSprite");
    private static readonly FieldInfo? IconValueLabelField = FindIconField("_valueLabel");

    internal static IReadOnlyList<CombatEnemyIntentObservation> Capture(CombatState state)
    {
        ArgumentNullException.ThrowIfNull(state);

        return state.Creatures
            .Where(creature => creature.IsEnemy && creature.CombatId.HasValue)
            .OrderBy(creature => creature.CombatId!.Value)
            .Select(CaptureEnemy)
            .ToArray();
    }

    private static CombatEnemyIntentObservation CaptureEnemy(Creature creature)
    {
        var combatId = creature.CombatId!.Value;
        if (!creature.IsAlive)
        {
            return Unavailable(combatId, "not_visible");
        }

        try
        {
            var node = creature.GetCreatureNode();
            if (node is null || !IsRendered(node) || !IsRendered(node.IntentContainer))
            {
                return Unavailable(combatId, "not_visible");
            }

            var icons = DescendantIcons(node.IntentContainer)
                .Where(IsRendered)
                .ToArray();
            if (icons.Length == 0)
            {
                return Unavailable(combatId, "not_visible");
            }

            if (IconIntentField is null || IconOwnerField is null
                || IconTargetsField is null || IconSpriteField is null
                || IconValueLabelField is null)
            {
                return Unavailable(combatId, "unverified");
            }

            // Do not inspect NextMove until the live UI has visible icon nodes.
            var modelIntents = creature.Monster?.NextMove?.Intents;
            if (modelIntents is null || modelIntents.Count != icons.Length)
            {
                return Unavailable(combatId, "unverified");
            }

            var unmatched = modelIntents.ToList();
            var visibleIntents = new List<CombatIntentObservation>(icons.Length);
            foreach (var icon in icons)
            {
                var intent = IconIntentField.GetValue(icon) as AbstractIntent;
                var owner = IconOwnerField.GetValue(icon) as Creature;
                var targets = (IconTargetsField.GetValue(icon) as IEnumerable<Creature>)?.ToArray();
                var sprite = IconSpriteField.GetValue(icon) as Sprite2D;
                if (intent is null || !ReferenceEquals(owner, creature)
                    || targets is null || !IsRendered(sprite))
                {
                    return Unavailable(combatId, "unverified");
                }

                var matchingIndex = unmatched.FindIndex(candidate =>
                    ReferenceEquals(candidate, intent));
                if (matchingIndex < 0)
                {
                    return Unavailable(combatId, "unverified");
                }

                unmatched.RemoveAt(matchingIndex);

                var valueLabel = IconValueLabelField.GetValue(icon) as RichTextLabel;
                var displayText = IsRendered(valueLabel) ? valueLabel!.Text : null;
                int? totalDamage = null;
                int? hits = null;
                if (intent is AttackIntent attack && displayText is not null)
                {
                    // The icon and its numeric label may refresh on different
                    // frames. Never expose a newly calculated number while the
                    // older number is still on screen.
                    var currentLabel = intent.GetIntentLabel(targets, creature)
                        .GetFormattedText();
                    if (!string.Equals(displayText, currentLabel, StringComparison.Ordinal))
                    {
                        return Unavailable(combatId, "unverified");
                    }

                    totalDamage = attack.GetTotalDamage(targets, creature);
                    hits = attack.Repeats;
                }

                visibleIntents.Add(new CombatIntentObservation(
                    intent.IntentType.ToString(),
                    displayText,
                    totalDamage,
                    hits));
            }

            return unmatched.Count == 0
                ? new CombatEnemyIntentObservation(combatId, "visible", visibleIntents)
                : Unavailable(combatId, "unverified");
        }
        catch (Exception)
        {
            // Missing native UI nodes, a changed private ABI, and a race with
            // intent animation all fail closed at the observation boundary.
            return Unavailable(combatId, "unverified");
        }
    }

    private static FieldInfo? FindIconField(string name) =>
        typeof(NIntent).GetField(name, BindingFlags.Instance | BindingFlags.NonPublic);

    private static CombatEnemyIntentObservation Unavailable(uint combatId, string visibility) =>
        new(combatId, visibility, []);

    private static bool IsRendered(CanvasItem? item)
    {
        if (item is null || !GodotObject.IsInstanceValid(item)
            || !item.IsInsideTree() || !item.IsVisibleInTree())
        {
            return false;
        }

        // IsVisibleInTree ignores a fade tween's alpha. Multiply the alpha
        // along the node ancestry so a still-fading icon cannot reveal a move.
        var effectiveAlpha = 1f;
        for (Node? ancestor = item; ancestor is not null; ancestor = ancestor.GetParent())
        {
            if (ancestor is CanvasItem canvas)
            {
                effectiveAlpha *= canvas.Modulate.A * canvas.SelfModulate.A;
                if (effectiveAlpha < ReadableAlpha)
                {
                    return false;
                }
            }
        }

        return true;
    }

    private static IEnumerable<NIntent> DescendantIcons(Node parent)
    {
        foreach (var child in parent.GetChildren())
        {
            if (child is NIntent icon)
            {
                yield return icon;
            }

            foreach (var descendant in DescendantIcons(child))
            {
                yield return descendant;
            }
        }
    }
}
