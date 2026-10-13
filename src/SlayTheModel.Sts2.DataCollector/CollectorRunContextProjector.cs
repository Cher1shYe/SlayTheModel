using System.Text.Json;
using MegaCrit.Sts2.Core.Map;
using MegaCrit.Sts2.Core.Runs;
using SlayTheModel.Sts2.ModAdapter;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.DataCollector;

/// <summary>
/// Persistent context shared by combat and outside-combat decisions. Seed,
/// native saves, RNG streams, and unrevealed outcomes are intentionally absent.
/// </summary>
internal static class CollectorRunContextProjector
{
    internal static JsonElement Capture(RunState state)
    {
        var map = EnumerateMap(state)
            .Select(point => new
            {
                coordinate = new { row = point.coord.row, column = point.coord.col },
                point_type = point.PointType.ToString(),
                visited = state.VisitedMapCoords.Contains(point.coord),
                children = point.Children
                    .Select(child => new { row = child.coord.row, column = child.coord.col })
                    .OrderBy(child => child.row)
                    .ThenBy(child => child.column)
                    .ToArray(),
            })
            .OrderBy(point => point.coordinate.row)
            .ThenBy(point => point.coordinate.column)
            .ToArray();
        var players = state.Players
            .OrderBy(player => player.NetId)
            .Select(player => new
            {
                player_id = player.NetId,
                character_id = player.Character.Id.ToString(),
                current_hp = player.Creature.CurrentHp,
                max_hp = player.Creature.MaxHp,
                gold = player.Gold,
                max_potion_count = player.MaxPotionCount,
                deck = player.Deck.Cards
                    .Select((card, index) => new
                    {
                        entity_index = index,
                        model_id = card.Id.ToString(),
                        upgrade_level = card.CurrentUpgradeLevel,
                        enchantment_id = card.Enchantment?.Id.ToString(),
                        enchantment_display = CollectorEnchantmentDisplayProjector.Capture(card),
                        affliction_id = card.Affliction?.Id.ToString(),
                    })
                    .OrderBy(card => card.model_id, StringComparer.Ordinal)
                    .ThenBy(card => card.upgrade_level)
                    .ThenBy(card => card.entity_index)
                    .ToArray(),
                relics = player.Relics
                    .Select(relic => new
                    {
                        model_id = relic.Id.ToString(),
                        display = RelicDisplayProjector.Capture(relic),
                    })
                    .OrderBy(relic => relic.model_id, StringComparer.Ordinal)
                    .ToArray(),
                potions = player.PotionSlots
                    .Select((potion, index) => new { potion, index })
                    .Where(item => item.potion is not null)
                    .Select(item => new
                    {
                        slot_index = item.index,
                        model_id = item.potion!.Id.ToString(),
                    })
                    .ToArray(),
            })
            .ToArray();

        return JsonSerializer.SerializeToElement(
            new
            {
                schema_version = 3,
                act_index = state.CurrentActIndex,
                act_floor = state.ActFloor,
                total_floor = state.TotalFloor,
                ascension_level = state.AscensionLevel,
                game_mode = state.GameMode.ToString(),
                room_type = state.CurrentRoom?.RoomType.ToString() ?? "Unknown",
                room_model_id = state.CurrentRoom?.ModelId?.ToString(),
                current_map_coordinate = state.CurrentMapCoord is { } coordinate
                    ? new { row = coordinate.row, column = coordinate.col }
                    : null,
                players,
                map,
            },
            ProtocolJson.Options);
    }

    internal static RunMetrics CaptureMetrics(RunState state)
    {
        var player = state.Players.Count == 1 ? state.Players[0] : null;
        return new RunMetrics(
            player?.Creature.CurrentHp,
            player?.Creature.MaxHp,
            player?.Gold,
            state.CurrentActIndex,
            state.ActFloor,
            state.TotalFloor,
            player?.Deck.Cards.Count,
            player?.Relics.Count,
            player?.Potions.Count());
    }

    private static IReadOnlyList<MapPoint> EnumerateMap(RunState state)
    {
        if (state.Map?.StartingMapPoint is not { } start)
        {
            return [];
        }

        var result = new List<MapPoint>();
        var queue = new Queue<MapPoint>();
        var seen = new HashSet<MapPoint>();
        queue.Enqueue(start);
        seen.Add(start);
        while (queue.TryDequeue(out var point))
        {
            result.Add(point);
            foreach (var child in point.Children)
            {
                if (seen.Add(child))
                {
                    queue.Enqueue(child);
                }
            }
        }

        return result;
    }
}

internal sealed record RunMetrics(
    int? CurrentHp,
    int? MaxHp,
    int? Gold,
    int? ActIndex,
    int? ActFloor,
    int? TotalFloor,
    int? DeckSize,
    int? RelicCount,
    int? PotionCount);
