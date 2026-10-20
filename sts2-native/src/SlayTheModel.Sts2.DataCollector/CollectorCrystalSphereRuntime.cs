using System.Reflection;
using Godot;
using HarmonyLib;
using MegaCrit.Sts2.Core.Events.Custom.CrystalSphereEvent;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.Events;
using MegaCrit.Sts2.Core.Nodes.Events.Custom.CrystalSphere;
using MegaCrit.Sts2.Core.Nodes.GodotExtensions;
using SlayTheModel.Collector;
using SlayTheModel.Sts2.Protocol;

namespace SlayTheModel.Sts2.DataCollector;

internal static partial class CollectorRuntime
{
    private sealed record PendingCrystalSphereCellTask(
        NativeActionCapture? Capture,
        Task Task,
        long RuntimeGeneration)
    {
        internal bool InvalidatedByOverlap { get; set; }
    }

    private static readonly FieldInfo CrystalSphereEntityField =
        AccessTools.Field(typeof(NCrystalSphereScreen), "_entity")
        ?? throw new MissingFieldException(typeof(NCrystalSphereScreen).FullName, "_entity");
    private static readonly FieldInfo CrystalSphereSmallButtonField =
        AccessTools.Field(typeof(NCrystalSphereScreen), "_smallDivinationButton")
        ?? throw new MissingFieldException(typeof(NCrystalSphereScreen).FullName,
            "_smallDivinationButton");
    private static readonly FieldInfo CrystalSphereBigButtonField =
        AccessTools.Field(typeof(NCrystalSphereScreen), "_bigDivinationButton")
        ?? throw new MissingFieldException(typeof(NCrystalSphereScreen).FullName,
            "_bigDivinationButton");
    private static readonly FieldInfo CrystalSphereProceedButtonField =
        AccessTools.Field(typeof(NCrystalSphereScreen), "_proceedButton")
        ?? throw new MissingFieldException(typeof(NCrystalSphereScreen).FullName,
            "_proceedButton");
    private static readonly FieldInfo CrystalSphereRevealedItemsField =
        AccessTools.Field(typeof(CrystalSphereMinigame), "_revealed")
        ?? throw new MissingFieldException(typeof(CrystalSphereMinigame).FullName,
            "_revealed");
    private static readonly FieldInfo CrystalSphereUiItemField =
        AccessTools.Field(typeof(NCrystalSphereItem), "_item")
        ?? throw new MissingFieldException(typeof(NCrystalSphereItem).FullName, "_item");
    private static readonly FieldInfo CrystalSphereUiItemMaterialField =
        AccessTools.Field(typeof(NCrystalSphereItem), "_material")
        ?? throw new MissingFieldException(typeof(NCrystalSphereItem).FullName,
            "_material");
    private static readonly FieldInfo CrystalSphereUiIconField =
        AccessTools.Field(typeof(NCrystalSphereItem), "_icon")
        ?? throw new MissingFieldException(typeof(NCrystalSphereItem).FullName, "_icon");
    private static readonly FieldInfo CrystalSphereUiCardField =
        AccessTools.Field(typeof(NCrystalSphereItem), "_card")
        ?? throw new MissingFieldException(typeof(NCrystalSphereItem).FullName, "_card");
    private static readonly FieldInfo CrystalSphereUiCardFrameField =
        AccessTools.Field(typeof(NCrystalSphereItem), "_cardFrame")
        ?? throw new MissingFieldException(typeof(NCrystalSphereItem).FullName,
            "_cardFrame");
    private static readonly FieldInfo CrystalSphereUiCardBannerField =
        AccessTools.Field(typeof(NCrystalSphereItem), "_cardBanner")
        ?? throw new MissingFieldException(typeof(NCrystalSphereItem).FullName,
            "_cardBanner");
    private static readonly List<PendingCrystalSphereCellTask>
        PendingCrystalSphereCellTasks = [];

    internal static NativeActionCapture? CaptureCrystalSphereTool(
        NCrystalSphereScreen screen,
        bool big)
    {
        if (!CrystalSpherePriorTaskSettled())
        {
            return null;
        }

        var selected = (big ? CrystalSphereBigButtonField : CrystalSphereSmallButtonField)
            .GetValue(screen) as NDivinationButton;
        return CaptureCrystalSphere(screen, selected, big ? "tool_big" : "tool_small");
    }

    internal static void CompleteCrystalSphereTool(
        NativeActionCapture? capture,
        NCrystalSphereScreen screen,
        bool big)
    {
        if (!IsCurrentCapture(capture) || capture!.IsCompleted)
        {
            return;
        }

        var entity = CrystalSphereEntityField.GetValue(screen) as CrystalSphereMinigame;
        if (entity?.CrystalSphereTool.ToString()
            .Equals(big ? "Big" : "Small", StringComparison.Ordinal) == true)
        {
            MarkNativeActionAccepted(capture);
        }
        else
        {
            CompleteNativeAction(capture, CollectorExecutionStatus.Cancelled,
                "crystal sphere tool did not become selected");
        }
    }

    internal static NativeActionCapture? CaptureCrystalSphereCell(
        NCrystalSphereScreen screen,
        NCrystalSphereCell cell) =>
        CrystalSpherePriorTaskSettled()
            ? CaptureCrystalSphere(screen, cell, "cell_click")
            : null;

    internal static void AttachCrystalSphereCellTask(
        NativeActionCapture? capture,
        Task task)
    {
        if (_episodes?.HasActiveEpisode != true)
        {
            return;
        }

        // Track even an unmatched click: its native Task still mutates the
        // board and must block later decisions until the reveal finishes.
        var pending = new PendingCrystalSphereCellTask(capture, task, _runGeneration);
        PendingCrystalSphereCellTasks.Add(pending);
        if (task.IsCompleted)
        {
            CompleteCrystalSphereCellTask(pending);
            return;
        }

        _ = task.ContinueWith(
            _ => ScheduleOnMainThread(() => CompleteCrystalSphereCellTask(pending)),
            CancellationToken.None,
            TaskContinuationOptions.ExecuteSynchronously,
            TaskScheduler.Default);
    }

    internal static NativeActionCapture? CaptureCrystalSphereProceed(
        NCrystalSphereScreen screen)
    {
        if (!CrystalSpherePriorTaskSettled())
        {
            return null;
        }

        var selected = CrystalSphereProceedButtonField.GetValue(screen) as NProceedButton;
        return CaptureCrystalSphere(screen, selected, "proceed");
    }

    private static NativeActionCapture? CaptureCrystalSphere(
        NCrystalSphereScreen screen,
        Node? selected,
        string inputKind)
    {
        return CaptureOutside(
            $"crystal_sphere_{inputKind}",
            (state, sourceIndex) =>
            {
                var board = CaptureCrystalSphereBoard(screen);
                var bindings = CrystalSphereLegalBindings(screen, board);
                var actions = bindings.Select(binding => binding.Action).ToArray();
                var selectedOrdinal = bindings.FindIndex(binding =>
                    ReferenceEquals(binding.Control, selected));
                var decision = CollectorOutsideProjector.ForCrystalSphere(
                    state, board, actions, sourceIndex);
                return (decision, selectedOrdinal);
            });
    }

    private static CrystalSphereBoardObservation CaptureCrystalSphereBoard(
        NCrystalSphereScreen screen)
    {
        if (!GodotObject.IsInstanceValid(screen) || !screen.IsInsideTree()
            || !screen.IsVisibleInTree()
            || CrystalSphereEntityField.GetValue(screen) is not CrystalSphereMinigame entity
            || CrystalSphereRevealedItemsField.GetValue(entity)
                is not IReadOnlyCollection<CrystalSphereItem> revealedItems)
        {
            throw new InvalidOperationException(
                "Crystal Sphere screen or revealed-item evidence is unavailable.");
        }

        var size = entity.GridSize;
        var nodes = Descendants<NCrystalSphereCell>(screen).ToArray();
        if (size.X <= 0 || size.Y <= 0 || nodes.Length != size.X * size.Y
            || nodes.Any(node => !GodotObject.IsInstanceValid(node)
                || !node.IsInsideTree() || !node.IsVisibleInTree()
                || node.Entity is null))
        {
            throw new InvalidOperationException(
                "Crystal Sphere visible cell grid does not match the native board.");
        }

        var revealed = revealedItems.ToHashSet(ReferenceEqualityComparer.Instance);
        var visiblyRevealed = new Dictionary<CrystalSphereItem, string?>(
            ReferenceEqualityComparer.Instance);
        foreach (var uiItem in Descendants<NCrystalSphereItem>(screen))
        {
            if (!GodotObject.IsInstanceValid(uiItem)
                || !uiItem.IsInsideTree() || !uiItem.IsVisibleInTree()
                || CrystalSphereUiItemMaterialField.GetValue(uiItem)
                    is not ShaderMaterial material
                || material.GetShaderParameter("val").AsDouble() < 0.99
                || CrystalSphereUiItemField.GetValue(uiItem)
                    is not CrystalSphereItem nativeItem
                || !revealed.Contains(nativeItem))
            {
                continue;
            }

            visiblyRevealed[nativeItem] = CrystalSphereVisibleVisualId(uiItem);
        }
        var cells = nodes.Select(node =>
        {
            var cell = node.Entity;
            // Do not read Item at all while its cell is hidden. Native Item is
            // pre-populated before the player can see it.
            string? visibleItemKind = null;
            string? visibleVisualId = null;
            if (!cell.IsHidden && cell.Item is { } item
                && visiblyRevealed.TryGetValue(item, out visibleVisualId))
            {
                visibleItemKind = item.GetType().Name;
            }

            return new CrystalSphereCellObservation(
                cell.X, cell.Y, cell.IsHidden, cell.IsHighlighted,
                visibleItemKind, visibleVisualId);
        }).OrderBy(cell => cell.Y).ThenBy(cell => cell.X).ToArray();

        var board = new CrystalSphereBoardObservation(
            size.X,
            size.Y,
            entity.DivinationCount,
            entity.CrystalSphereTool.ToString().ToLowerInvariant(),
            entity.IsFinished,
            cells);
        board.Validate();
        return board;
    }

    private static string? CrystalSphereVisibleVisualId(NCrystalSphereItem uiItem)
    {
        var parts = new List<string>();
        if (CrystalSphereUiIconField.GetValue(uiItem) is TextureRect icon
            && icon.IsVisibleInTree()
            && icon.Texture?.ResourcePath is { Length: > 0 } iconPath)
        {
            parts.Add($"icon:{iconPath}");
        }

        if (CrystalSphereUiCardField.GetValue(uiItem) is Control card
            && card.IsVisibleInTree())
        {
            if (CrystalSphereUiCardFrameField.GetValue(uiItem) is TextureRect frame
                && frame.IsVisibleInTree()
                && frame.Material?.ResourcePath is { Length: > 0 } framePath)
            {
                parts.Add($"frame:{framePath}");
            }

            if (CrystalSphereUiCardBannerField.GetValue(uiItem) is TextureRect banner
                && banner.IsVisibleInTree()
                && banner.Material?.ResourcePath is { Length: > 0 } bannerPath)
            {
                parts.Add($"banner:{bannerPath}");
            }
        }

        return parts.Count == 0 ? null : string.Join("|", parts);
    }

    private static List<(Node Control, OutsideCombatActionDescriptor Action)>
        CrystalSphereLegalBindings(
            NCrystalSphereScreen screen,
            CrystalSphereBoardObservation board)
    {
        var bindings = new List<(Node, OutsideCombatActionDescriptor)>();
        void Add(Node? control, OutsideCombatActionKind kind, string target)
        {
            if (control is not NClickableControl clickable)
            {
                return;
            }

            if (!GodotObject.IsInstanceValid(clickable)
                || !clickable.IsInsideTree() || !clickable.IsVisibleInTree()
                || !clickable.IsEnabled)
            {
                return;
            }

            var ordinal = bindings.Count;
            bindings.Add((clickable, new OutsideCombatActionDescriptor(
                $"{kind.ToString().ToLowerInvariant()}:{ordinal}:{target}",
                kind, ordinal, target)));
        }

        if (!board.IsFinished)
        {
            Add(CrystalSphereSmallButtonField.GetValue(screen) as Node,
                OutsideCombatActionKind.ChooseMinigameOption, "tool:small");
            Add(CrystalSphereBigButtonField.GetValue(screen) as Node,
                OutsideCombatActionKind.ChooseMinigameOption, "tool:big");
            if (board.DivinationsRemaining > 0)
            {
                foreach (var cell in Descendants<NCrystalSphereCell>(screen)
                             .OrderBy(cell => cell.Entity.Y)
                             .ThenBy(cell => cell.Entity.X))
                {
                    if (cell.Entity.IsHidden)
                    {
                        Add(cell, OutsideCombatActionKind.ChooseMinigameOption,
                            $"cell:{cell.Entity.X},{cell.Entity.Y}");
                    }
                }
            }
        }

        if (board.IsFinished)
        {
            Add(CrystalSphereProceedButtonField.GetValue(screen) as Node,
                OutsideCombatActionKind.Proceed, "proceed");
        }

        return bindings;
    }

    private static bool CrystalSpherePriorTaskSettled()
    {
        foreach (var completed in PendingCrystalSphereCellTasks
                     .Where(pending => pending.Task.IsCompleted)
                     .ToArray())
        {
            CompleteCrystalSphereCellTask(completed);
        }

        var unfinished = PendingCrystalSphereCellTasks
            .Where(pending => pending.RuntimeGeneration == _runGeneration)
            .ToArray();
        if (unfinished.Length == 0)
        {
            return true;
        }

        // The current input will still run natively, but its pre-state is not
        // settled. Keep every Task as a barrier, including unmatched inputs.
        foreach (var pending in unfinished)
        {
            if (pending.Capture is { IsCompleted: false } capture)
            {
                CompleteNativeAction(capture, CollectorExecutionStatus.Failed,
                    "Crystal Sphere input overlapped an unfinished cell reveal");
                pending.InvalidatedByOverlap = true;
            }
        }

        var related = unfinished.Select(pending => pending.Capture)
            .FirstOrDefault(capture => capture is not null);
        RecordCoverageGap("crystal_sphere_input_during_pending_reveal",
            new { unfinished_native_tasks = unfinished.Length },
            invalidatePendingDecision: false,
            relatedDecisionId: related?.Draft.Receipt.DecisionId,
            relatedAttemptId: related?.Draft.AttemptId);
        return false;
    }

    private static void CompleteCrystalSphereCellTask(
        PendingCrystalSphereCellTask pending)
    {
        if (!PendingCrystalSphereCellTasks.Remove(pending))
        {
            return;
        }

        if (pending.RuntimeGeneration != _runGeneration)
        {
            return;
        }

        var capture = pending.Capture;
        if (pending.InvalidatedByOverlap)
        {
            FinishPendingRun();
            return;
        }

        if (pending.Task.Status == TaskStatus.RanToCompletion)
        {
            MarkNativeActionAccepted(capture);
            FinishPendingRun();
            return;
        }

        var detail = pending.Task.Exception?.GetBaseException().ToString()
                     ?? $"Crystal Sphere cell task ended with {pending.Task.Status}";
        if (capture is { IsCompleted: true })
        {
            FailStagedAcceptedAction(capture, detail);
        }
        else
        {
            CompleteNativeAction(capture, CollectorExecutionStatus.Failed, detail);
        }

        RecordCoverageGap("crystal_sphere_cell_task_failed",
            new { status = pending.Task.Status.ToString(), detail },
            invalidatePendingDecision: false,
            relatedDecisionId: capture?.Draft.Receipt.DecisionId,
            relatedAttemptId: capture?.Draft.AttemptId);
        FinishPendingRun();
    }
}
