using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.Encodings.Web;
using CombatSolver.Api;
using Microsoft.ML.OnnxRuntime;
using Microsoft.ML.OnnxRuntime.Tensors;
using SlayTheModel.Sts2.Protocol;

/// <summary>Experimental legal-root scorer. Failure never bypasses ReplayMcts.</summary>
internal sealed class AlphaZeroOnnxEvaluator : IDisposable
{
    private const int EntityWidth = 12;
    private const int GlobalWidth = 4;
    private const int ActionWidth = 19;
    private readonly InferenceSession session;

    private AlphaZeroOnnxEvaluator(InferenceSession session) => this.session = session;

    public static AlphaZeroOnnxEvaluator? TryLoad(string? path, out string status)
    {
        if (string.IsNullOrWhiteSpace(path))
        {
            status = "pure-mcts:no-model-configured";
            return null;
        }
        try
        {
            path = Path.GetFullPath(path);
            var manifestPath = Path.ChangeExtension(path, ".manifest.json");
            using var manifest = JsonDocument.Parse(File.ReadAllText(manifestPath));
            var root = manifest.RootElement;
            if (root.GetProperty("format").GetString() != "azcombat.onnx.v4"
                || root.GetProperty("featureAbi").GetString() != "azcombat.features.v4"
                || root.GetProperty("inputs").GetProperty("entities")[1].GetInt32() != EntityWidth
                || root.GetProperty("inputs").GetProperty("globals")[0].GetInt32() != GlobalWidth
                || root.GetProperty("inputs").GetProperty("actions")[1].GetInt32() != ActionWidth)
                throw new InvalidDataException("ONNX feature ABI/manifest mismatch.");
            var hash = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path)));
            if (!hash.Equals(root.GetProperty("onnxSha256").GetString(), StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("ONNX SHA256 does not match its manifest.");
            var loaded = new InferenceSession(path);
            status = $"model-ready path={path} sha256={hash}";
            return new AlphaZeroOnnxEvaluator(loaded);
        }
        catch (Exception error)
        {
            status = $"pure-mcts:model-load-failed:{error.GetType().Name}:{error.Message}";
            return null;
        }
    }

    public bool TryChoose(CombatObservation observation, IReadOnlyList<CombatSolverMctsAction> legal,
        out CombatSolverMctsAction? chosen, out float value, out string status)
    {
        chosen = null;
        value = float.NaN;
        try
        {
            if (!TryEvaluate(observation, legal, out var logits, out value, out status)) return false;
            var best = Enumerable.Range(0, legal.Count).MaxBy(index => logits[index]);
            chosen = legal[best];
            status = "model-root:" + chosen.Key;
            return true;
        }
        catch (Exception error)
        {
            status = $"pure-mcts:model-inference-failed:{error.GetType().Name}:{error.Message}";
            return false;
        }
    }

    public bool TryEvaluate(CombatObservation observation, IReadOnlyList<CombatSolverMctsAction> legal,
        out float[] logits, out float value, out string status)
    {
        logits = [];
        value = float.NaN;
        try
        {
            observation.Validate();
            if (legal.Count == 0 || legal.Select(a => a.Key).Distinct(StringComparer.Ordinal).Count() != legal.Count)
                throw new InvalidDataException("Empty or duplicate root legal actions.");
            var entities = EncodeEntities(observation);
            var globals = new float[] { observation.RoundNumber, Hash(((int)observation.CurrentSide).ToString(CultureInfo.InvariantCulture)),
                observation.Players.Count, observation.Creatures.Count };
            var actions = EncodeActions(legal);
            var inputs = new[]
            {
                NamedOnnxValue.CreateFromTensor("entities", new DenseTensor<float>(entities, [entities.Length / EntityWidth, EntityWidth])),
                NamedOnnxValue.CreateFromTensor("globals", new DenseTensor<float>(globals, [GlobalWidth])),
                NamedOnnxValue.CreateFromTensor("actions", new DenseTensor<float>(actions, [legal.Count, ActionWidth])),
            };
            using var outputs = session.Run(inputs);
            logits = outputs.Single(output => output.Name == "logits").AsTensor<float>().ToArray();
            var values = outputs.Single(output => output.Name == "value").AsTensor<float>().ToArray();
            if (logits.Length != legal.Count || values.Length != 1 || logits.Any(x => !float.IsFinite(x))
                || !float.IsFinite(values[0]) || values[0] < -1.0001f || values[0] > 1.0001f)
                throw new InvalidDataException("ONNX output shape or finite-value constraint failed.");
            value = values[0];
            status = $"model-evaluate:value={value:F6}";
            return true;
        }
        catch (Exception error)
        {
            status = $"pure-mcts:model-inference-failed:{error.GetType().Name}:{error.Message}";
            return false;
        }
    }

    public void Dispose() => session.Dispose();

    private static float Hash(string? value)
    {
        if (value is null) return 0;
        var digest = SHA256.HashData(Encoding.UTF8.GetBytes(value));
        return (float)(System.Buffers.Binary.BinaryPrimitives.ReadUInt32BigEndian(digest) / (double)uint.MaxValue);
    }

    private static float[] EncodeEntities(CombatObservation observation)
    {
        var rows = new List<float>();
        void Add(params float[] features)
        {
            if (features.Length > EntityWidth) throw new InvalidDataException("Entity feature overflow.");
            rows.AddRange(features);
            for (int index = features.Length; index < EntityWidth; index++) rows.Add(0);
        }
        foreach (var player in observation.Players)
        {
            Add(1, Hash(player.CharacterId), player.Energy, player.Stars, player.TurnNumber, Hash(player.Phase));
            foreach (var pile in player.Piles)
            {
                if (string.Equals(pile.PileType, "Draw", StringComparison.OrdinalIgnoreCase)
                    && pile.Cards.Count > 0)
                    throw new InvalidDataException("Hidden draw pile contents cannot enter the policy encoder.");
                foreach (var card in pile.Cards)
                    Add(2, Hash(card.ModelId), card.CombatCardIndex, card.EnergyCost ?? 0,
                        Hash(pile.PileType), Hash(card.AfflictionId), card.AfflictionCount, card.Keywords.Count);
            }
            foreach (var relic in player.Relics) Add(3, Hash(relic.ModelId));
            foreach (var potion in player.Potions) Add(4, Hash(potion.ModelId), potion.SlotIndex);
            foreach (var orb in player.Orbs) Add(5, Hash(orb.ModelId), orb.Passive, orb.Evoke);
        }
        foreach (var creature in observation.Creatures)
        {
            Add(6, Hash(creature.MonsterId), creature.CurrentHp, creature.MaxHp, creature.Block,
                creature.PlayerId.HasValue ? 1 : 0);
            if (creature.CurrentIntent != null) Add(8, Hash(creature.CurrentIntent));
            foreach (var power in creature.Powers) Add(7, Hash(power.ModelId), power.Amount);
        }
        if (observation.Choice is { } choice)
        {
            Add(9, Hash(choice.TriggerCardId), Hash(choice.Effect), Hash(choice.SourcePile),
                choice.MinCount, choice.MaxCount, choice.Ordered ? 1 : 0,
                choice.Candidates.Count, choice.CompletedSelections.Count);
            for (int index = 0; index < choice.Candidates.Count; index++)
            {
                var candidate = choice.Candidates[index];
                Add(10, Hash(candidate.ModelId), candidate.CombatCardIndex, candidate.UpgradeLevel, index);
            }
            for (int index = 0; index < choice.CompletedSelections.Count; index++)
            {
                var completed = choice.CompletedSelections[index];
                var selectedJson = JsonSerializer.Serialize(completed.CombatCardIndices,
                    new JsonSerializerOptions { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping });
                Add(11, Hash(completed.Effect), completed.CombatCardIndices.Count,
                    completed.CombatCardIndices.Count == 0 ? 0 : Hash(selectedJson), index);
            }
        }
        if (rows.Count == 0) Add(0);
        return rows.ToArray();
    }

    private static float[] EncodeActions(IReadOnlyList<CombatSolverMctsAction> legal)
    {
        string[] kinds = ["PlayCard", "UsePotion", "EndTurn", "Target", "Option", "CardSubset", "CardOrder", "NestedChoice"];
        var data = new List<float>(legal.Count * ActionWidth);
        foreach (var item in legal)
        {
            var action = item.Native;
            var kind = action.ChoiceKey is null ? action.Kind : "NestedChoice";
            if (!kinds.Contains(kind, StringComparer.Ordinal))
                throw new InvalidDataException("Unrecognized legal action kind: " + kind);
            foreach (var candidateKind in kinds) data.Add(kind == candidateKind ? 1 : 0);
            var selected = action.SelectedCards ?? [];
            var selectionJson = JsonSerializer.Serialize(
                selected.Select(card => card.CardId).ToArray(),
                new JsonSerializerOptions { Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping });
            data.AddRange([
                Hash(action.CardId), action.CardOccurrence, action.TargetCombatId ?? 0,
                0, 0, selected.Count,
                selected.Count == 0 ? 0 : selected.Sum(card => Hash(card.CardId)) / selected.Count,
                selected.Count == 0 ? 0 : Hash(selectionJson), 0, 0, 0,
            ]);
        }
        return data.ToArray();
    }
}
