using Godot;
using System.Diagnostics.CodeAnalysis;
using MegaCrit.Sts2.Core.AutoSlay.Helpers;
using MegaCrit.Sts2.Core.Combat;
using MegaCrit.Sts2.Core.Nodes.Cards;
using MegaCrit.Sts2.Core.Nodes.Cards.Holders;
using MegaCrit.Sts2.Core.Nodes.CommonUi;
using MegaCrit.Sts2.Core.Nodes.Events;
using MegaCrit.Sts2.Core.Nodes.Events.Custom.CrystalSphere;
using MegaCrit.Sts2.Core.Nodes.GodotExtensions;
using MegaCrit.Sts2.Core.Nodes.Relics;
using MegaCrit.Sts2.Core.Nodes.RestSite;
using MegaCrit.Sts2.Core.Nodes.Rewards;
using MegaCrit.Sts2.Core.Nodes.Rooms;
using MegaCrit.Sts2.Core.Nodes.Screens;
using MegaCrit.Sts2.Core.Nodes.Screens.CardSelection;
using MegaCrit.Sts2.Core.Nodes.Screens.Map;
using MegaCrit.Sts2.Core.Nodes.Screens.Overlays;
using MegaCrit.Sts2.Core.Nodes.Screens.Shops;
using MegaCrit.Sts2.Core.Nodes.Screens.TreasureRoomRelic;
using MegaCrit.Sts2.Core.Nodes.TreasureRooms;
using MegaCrit.Sts2.Core.Rewards;
using MegaCrit.Sts2.Core.Runs;

namespace SlayTheModel.Sts2.ModAdapter;

/// <summary>
/// Deterministic outside-combat integration policy. It acts through the game's
/// native controls rather than screen coordinates, and only on known run screens.
/// Main-menu and character-selection controls are deliberately outside its scope.
/// </summary>
internal static class OutsideCombatController
{
    private static readonly HashSet<ulong> AttemptedOnSurface = [];
    private static bool _enabled;
    private static ulong _surfaceId;
    private static ulong _lastControlId;
    private static ulong _completedSingleChoiceSurfaceId;
    private static ulong _merchantOpenedInRoom;
    private static bool _awaitingMerchantCardRemoval;
    private static long _nextActionAt;
    private static long _surfaceReadyAt;
    private static long _mapReadyAt;
    private static long _nextMapWaitLogAt;
    private static bool _faulted;
    private static bool _clicking;

    private const int ActionCooldownMilliseconds = 350;
    private const int SurfaceSettleMilliseconds = 450;
    private const int MapSettleMilliseconds = 1000;

    internal static void Initialize(AdapterConfiguration configuration)
    {
        if (configuration.RunMode == AdapterRunMode.Train)
        {
            Console.WriteLine("[SlayTheModel] train mode is declared but no trainer is connected yet; live policies are disabled");
            return;
        }

        if (configuration.OutsideCombatPolicy != OutsideCombatPolicyKind.FirstLegal)
        {
            return;
        }

        _enabled = true;
        Callable.From(() =>
        {
            var tree = (SceneTree)Engine.GetMainLoop();
            tree.ProcessFrame += Tick;
            tree.Root.TreeExiting += Stop;
        }).CallDeferred();
        Console.WriteLine(
            "[SlayTheModel] OUTSIDE CONTROL ENABLED policy=first-legal; "
            + "the adapter will choose the first enabled option on supported run screens");
    }

    private static void Stop()
    {
        _enabled = false;
        AttemptedOnSurface.Clear();
        _surfaceId = 0;
        _lastControlId = 0;
        _completedSingleChoiceSurfaceId = 0;
        _merchantOpenedInRoom = 0;
        _awaitingMerchantCardRemoval = false;
    }

    private static void Tick()
    {
        var runManager = RunManager.Instance;
        if (!_enabled || _faulted || _clicking || CombatManager.Instance.IsInProgress
            || System.Environment.TickCount64 < _nextActionAt)
        {
            return;
        }

        // IsSingleplayerOrFakeMultiplayer dereferences transient run internals and
        // throws while a saved run is being reconstructed. The state itself is a
        // safe readiness signal, and this policy only supports one local player.
        if (runManager.IsInProgress)
        {
            var state = runManager.DebugOnlyGetState();
            if (state is null || state.Players.Count != 1)
            {
                return;
            }
        }

        try
        {
            var decision = FindDecision();
            if (decision is null)
            {
                return;
            }

            // The map can open underneath a rewards overlay that remains mounted
            // during its outro. Alternating discovery between those two nodes
            // must not restart the generic surface timer forever; map travel has
            // its own one-second quiet-window readiness check.
            var isMapDecision = decision.Surface is NMapScreen;
            if (!isMapDecision)
            {
                SetSurface(decision.Surface);
            }

            if (!isMapDecision && System.Environment.TickCount64 < _surfaceReadyAt)
            {
                return;
            }

            var targetId = decision.Target.GetInstanceId();
            if (_lastControlId == targetId)
            {
                return;
            }

            _lastControlId = targetId;
            AttemptedOnSurface.Add(targetId);
            if (decision.CompletesSingleChoice)
            {
                _completedSingleChoiceSurfaceId = _surfaceId;
            }
            _nextActionAt = System.Environment.TickCount64 + ActionCooldownMilliseconds;
            if (decision.MarksMerchantOpened)
            {
                _merchantOpenedInRoom = _surfaceId;
            }
            if (decision.StartsMerchantCardRemoval)
            {
                _awaitingMerchantCardRemoval = true;
            }
            if (decision.CompletesMerchantCardRemoval)
            {
                _awaitingMerchantCardRemoval = false;
            }

            _clicking = true;
            _ = ClickAsync(decision);
        }
        catch (Exception exception)
        {
            _faulted = true;
            Console.Error.WriteLine($"[SlayTheModel] outside first-legal failed: {exception}");
            Console.Error.WriteLine("[SlayTheModel] outside policy disabled after failure; restart to retry.");
        }
    }

    private static async Task ClickAsync(OutsideDecision decision)
    {
        try
        {
            GD.Print(
                $"[SlayTheModel] outside first-legal: {decision.Description} "
                + $"node={decision.Target.GetPath()}");
            if (decision.CardHolder is not null)
            {
                // NCardHolder listens for its own Pressed signal. ForceClick on
                // its child hitbox only emits NClickableControl.Released, which
                // does not select the card. Match the game's AutoSlay handlers by
                // emitting the holder signal directly.
                decision.CardHolder.EmitSignal(
                    NCardHolder.SignalName.Pressed,
                    decision.CardHolder);
                await Task.Delay(100);
            }
            else
            {
                // Use the same input helper as the game's built-in AutoSlay. Its
                // delay lets signal handlers push the next choice screen before
                // we enumerate again.
                await UiHelper.Click(decision.Control!, 100);
            }
        }
        catch (Exception exception)
        {
            _faulted = true;
            GD.PushError($"[SlayTheModel] outside first-legal click failed: {exception}");
        }
        finally
        {
            _clicking = false;
            _nextActionAt = System.Environment.TickCount64 + ActionCooldownMilliseconds;
            // Reward collection may open another choice screen asynchronously,
            // while the map can already be visible underneath it. Require one
            // quiet second after every outside action before selecting a route.
            _mapReadyAt = System.Environment.TickCount64 + MapSettleMilliseconds;
        }
    }

    private static OutsideDecision? FindDecision()
    {
        var overlay = GetTopOverlay();
        if (overlay is not null)
        {
            var overlayDecision = FindOverlayDecision(overlay);
            if (overlayDecision is not null)
            {
                return overlayDecision;
            }

            // A completed reward/card overlay can remain visible during its
            // outro while the map is already open. Known decision overlays are
            // safe to drain and then fall through; unknown overlays still block
            // clicks into the room beneath them.
            if (!IsKnownDecisionOverlay(overlay))
            {
                return null;
            }
        }

        // A few choice screens are pushed while an action is awaiting input and
        // can briefly precede NOverlayStack bookkeeping. Falling back to the live
        // scene tree prevents the policy from deadlocking on that synchronization
        // window without clicking through a different top overlay.
        var detachedChoice = overlay is null ? FindActiveChoiceScreen() : null;
        if (detachedChoice is not null)
        {
            var detachedDecision = FindOverlayDecision(detachedChoice);
            if (detachedDecision is not null)
            {
                return detachedDecision;
            }
        }

        var eventRoom = NEventRoom.Instance;
        if (IsActive(eventRoom))
        {
            var eventDecision = FindEventDecision(eventRoom);
            if (eventDecision is not null)
            {
                return eventDecision;
            }
        }

        var restSite = NRestSiteRoom.Instance;
        if (IsActive(restSite))
        {
            var restDecision = FindRestSiteDecision(restSite);
            if (restDecision is not null)
            {
                return restDecision;
            }
        }

        var merchant = NMerchantRoom.Instance;
        if (IsActive(merchant))
        {
            var merchantDecision = FindMerchantDecision(merchant);
            if (merchantDecision is not null)
            {
                return merchantDecision;
            }
        }

        var tree = (SceneTree)Engine.GetMainLoop();
        var treasure = tree.Root.GetNodeOrNull<NTreasureRoom>(
            "/root/Game/RootSceneContainer/Run/RoomContainer/TreasureRoom")
            ?? FindActiveNode<NTreasureRoom>();
        if (treasure is not null)
        {
            var treasureDecision = FindTreasureDecision(treasure);
            if (treasureDecision is not null)
            {
                return treasureDecision;
            }
        }

        // Room and overlay decisions always take priority. Only choose a route
        // after every currently actionable outside-combat decision is drained.
        var map = NMapScreen.Instance;
        return IsActive(map) && map.IsOpen ? FindMapDecision(map) : null;
    }

    private static Node? FindActiveChoiceScreen()
    {
        Node? screen = FindActiveNode<NCardRewardSelectionScreen>();
        screen ??= FindActiveNode<NChooseACardSelectionScreen>();
        screen ??= FindActiveNode<NChooseABundleSelectionScreen>();
        screen ??= FindActiveNode<NChooseARelicSelection>();
        screen ??= FindActiveNode<NCardGridSelectionScreen>();
        screen ??= FindActiveNode<NCrystalSphereScreen>();
        screen ??= FindActiveNode<NRewardsScreen>();
        return screen;
    }

    private static Node? GetTopOverlay()
    {
        var stack = NOverlayStack.Instance;
        if (!IsActive(stack) || stack.ScreenCount == 0)
        {
            return null;
        }

        var top = stack.Peek() as Node;
        // Closed screens can remain on the stack for part of their outro. They
        // must not hide the newly opened map from the outside policy.
        return IsActive(top) ? top : null;
    }

    private static OutsideDecision? FindOverlayDecision(Node screen) => screen switch
    {
        NRewardsScreen rewards =>
            FromFirstUnattempted(rewards, Descendants<NRewardButton>(rewards).Where(CanClaimReward), "reward")
            ?? FromFirstUnattempted(rewards, Descendants<NProceedButton>(rewards), "rewards proceed"),
        NCardRewardSelectionScreen cardReward => FindCardRewardDecision(cardReward),
        NChooseACardSelectionScreen chooseCard => FindSingleCardDecision(chooseCard),
        NChooseABundleSelectionScreen chooseBundle => FindBundleDecision(chooseBundle),
        NChooseARelicSelection chooseRelic => FindSingleRelicDecision(chooseRelic),
        NCardGridSelectionScreen grid => FindGridDecision(grid),
        NCrystalSphereScreen crystalSphere => FindCrystalSphereDecision(crystalSphere),
        NMapScreen map => FindMapDecision(map),
        _ => null,
    };

    private static bool IsKnownDecisionOverlay(Node screen) => screen is
        NRewardsScreen
        or NCardRewardSelectionScreen
        or NChooseACardSelectionScreen
        or NChooseABundleSelectionScreen
        or NChooseARelicSelection
        or NCardGridSelectionScreen
        or NCrystalSphereScreen
        or NMapScreen;

    private static OutsideDecision? FindMapDecision(NMapScreen map)
    {
        // Map travel can itself be the input awaited by a running game action, so
        // gating on ActionExecutor.IsRunning deadlocks. The game's own AutoSlay
        // handler uses the map's travel flags and the selected point's enabled
        // state as the readiness contract.
        var now = System.Environment.TickCount64;
        if (now < _mapReadyAt)
        {
            return WaitForMap(map, $"settling outside choices ({_mapReadyAt - now}ms remaining)");
        }

        if (!map.IsOpen || !map.IsTravelEnabled || map.IsTraveling)
        {
            return WaitForMap(map, "travel flags not ready");
        }

        var state = RunManager.Instance.DebugOnlyGetState();
        if (state is null)
        {
            return WaitForMap(map, "run state not ready");
        }

        var points = Descendants<NMapPoint>(map).ToArray();
        NMapPoint? next;
        if (state.VisitedMapCoords.Count == 0)
        {
            // This matches the game's AutoSlay policy for the first floor.
            next = points.FirstOrDefault(point => point.Point.coord.row == 0);
        }
        else
        {
            // Do not take the first clickable node in scene-tree order. Follow
            // the actual graph from the most recently visited map coordinate.
            var last = state.VisitedMapCoords[^1];
            var current = points.FirstOrDefault(point => point.Point.coord.Equals(last));
            var child = current?.Point.Children.FirstOrDefault()
                ?? state.CurrentMapPoint?.Children.FirstOrDefault();
            next = child is null
                ? null
                : points.FirstOrDefault(point => point.Point.coord.Equals(child.coord));
        }

        if (next is null)
        {
            return WaitForMap(map, "no graph child node found");
        }

        // This is the same readiness check used by the game's MapScreenHandler.
        // Visibility is intentionally not required: clipped map controls are
        // still valid ForceClick targets.
        if (!GodotObject.IsInstanceValid(next) || !next.IsInsideTree() || !next.IsEnabled)
        {
            return WaitForMap(map, $"point ({next.Point.coord.row}, {next.Point.coord.col}) not enabled");
        }

        var coord = next.Point.coord;
        return new OutsideDecision(map, next, $"map point ({coord.row}, {coord.col})");
    }

    private static OutsideDecision? WaitForMap(NMapScreen map, string reason)
    {
        var now = System.Environment.TickCount64;
        if (now >= _nextMapWaitLogAt)
        {
            _nextMapWaitLogAt = now + 3000;
            GD.Print(
                $"[SlayTheModel] outside first-legal waiting for map: {reason}; "
                + $"open={map.IsOpen} travelEnabled={map.IsTravelEnabled} traveling={map.IsTraveling}");
        }

        return null;
    }

    private static OutsideDecision? FindCardRewardDecision(NCardRewardSelectionScreen screen)
    {
        SetSurface(screen);
        if (_completedSingleChoiceSurfaceId == _surfaceId)
        {
            return null;
        }

        var card = FromFirstCard(screen, Descendants<NCardHolder>(screen), "card reward");
        if (card is not null)
        {
            return card with { CompletesSingleChoice = true };
        }

        return FromFirstUnattempted(
                screen,
                Descendants<NCardRewardAlternativeButton>(screen),
                "card reward alternative")
            ?? MarkSingleChoiceComplete(FromFirst(
                screen,
                Descendants<NChoiceSelectionSkipButton>(screen),
                "card reward skip"));
    }

    private static OutsideDecision? FindSingleCardDecision(NChooseACardSelectionScreen screen)
    {
        SetSurface(screen);
        if (_completedSingleChoiceSurfaceId == _surfaceId)
        {
            return null;
        }

        return MarkSingleChoiceComplete(
            FromFirstCard(screen, Descendants<NCardHolder>(screen), "card choice")
            ?? FromFirst(screen, Descendants<NChoiceSelectionSkipButton>(screen), "card choice skip"));
    }

    private static OutsideDecision? FindSingleRelicDecision(NChooseARelicSelection screen)
    {
        SetSurface(screen);
        if (_completedSingleChoiceSurfaceId == _surfaceId)
        {
            return null;
        }

        return MarkSingleChoiceComplete(
            FromFirst(screen, Descendants<NRelicBasicHolder>(screen), "relic choice")
            ?? FromFirst(screen, Descendants<NChoiceSelectionSkipButton>(screen), "relic choice skip"));
    }

    private static OutsideDecision? MarkSingleChoiceComplete(OutsideDecision? decision) =>
        decision is null ? null : decision with { CompletesSingleChoice = true };

    private static OutsideDecision? FindBundleDecision(NChooseABundleSelectionScreen screen)
    {
        SetSurface(screen);
        var confirm = FirstUsable(Descendants<NConfirmButton>(screen));
        if (AttemptedOnSurface.Count > 0 && confirm is not null)
        {
            return new(screen, confirm, "confirm first card bundle");
        }

        return FromFirst(screen, Descendants<NCardBundle>(screen).Select(bundle => bundle.Hitbox), "card bundle");
    }

    private static OutsideDecision? FindGridDecision(NCardGridSelectionScreen screen)
    {
        SetSurface(screen);
        var confirm = FirstUsable(Descendants<NConfirmButton>(screen));
        if (AttemptedOnSurface.Count > 0 && confirm is not null)
        {
            var confirmation = new OutsideDecision(screen, confirm, "confirm first card selection");
            return _awaitingMerchantCardRemoval
                ? confirmation with { CompletesMerchantCardRemoval = true }
                : confirmation;
        }

        if (_awaitingMerchantCardRemoval)
        {
            var removalTarget = Descendants<NCardHolder>(screen)
                .Select(holder => new { Holder = holder, Card = holder.CardNode?.Model })
                .Where(candidate => IsActive(candidate.Holder)
                    && IsUsable(candidate.Holder.Hitbox)
                    && candidate.Card is not null
                    && !AttemptedOnSurface.Contains(candidate.Holder.GetInstanceId()))
                .OrderBy(candidate => RemovalPriority(candidate.Card!.Id.Entry))
                .ThenBy(candidate => candidate.Card!.Id.Entry, StringComparer.Ordinal)
                .FirstOrDefault();
            if (removalTarget is not null)
            {
                var entry = removalTarget.Card!.Id.Entry;
                return new OutsideDecision(
                    screen,
                    removalTarget.Holder,
                    $"merchant remove card {entry}",
                    CardHolder: removalTarget.Holder);
            }

            var cancel = FromFirst(screen, Descendants<NBackButton>(screen), "skip merchant card removal");
            return cancel is null
                ? null
                : cancel with { CompletesMerchantCardRemoval = true };
        }

        return FromFirstCard(screen, Descendants<NCardHolder>(screen), "card selection", requireUnattempted: true);
    }

    private static int RemovalPriority(string cardId) =>
        cardId.Equals("STRIKE", StringComparison.Ordinal)
            || cardId.StartsWith("STRIKE_", StringComparison.Ordinal) ? 0
        : cardId.Equals("DEFEND", StringComparison.Ordinal)
            || cardId.StartsWith("DEFEND_", StringComparison.Ordinal) ? 1
        : 2;

    private static OutsideDecision? FindCrystalSphereDecision(NCrystalSphereScreen screen) =>
        FromFirst(screen, Descendants<NDivinationButton>(screen), "crystal sphere divination")
        ?? FromFirst(screen, Descendants<NCrystalSphereCell>(screen), "crystal sphere cell")
        ?? FromFirst(screen, Descendants<NProceedButton>(screen), "crystal sphere proceed");

    private static OutsideDecision? FindEventDecision(NEventRoom room)
    {
        // NEventRoom creates the buttons in semantic option order. The model
        // flags let us skip locked and already-consumed choices instead of
        // getting stuck on the first rendered button.
        var option = Descendants<NEventOptionButton>(room)
            .Where(button => IsUsable(button)
                && button.Option is not null
                && !button.Option.IsLocked
                && !button.Option.WasChosen)
            .FirstOrDefault();
        return FromControl(room, option, "event option")
            ?? FromFirst(room, Descendants<NAncientDialogueHitbox>(room), "ancient event option")
            ?? FromFirst(room, Descendants<NDivinationButton>(room), "event divination")
            ?? FromFirst(room, Descendants<NCrystalSphereCell>(room), "event minigame choice");
    }

    private static OutsideDecision? FindRestSiteDecision(NRestSiteRoom room)
    {
        return FromFirstUnattempted(room, Descendants<NRestSiteButton>(room), "rest-site option")
            ?? FromControl(room, room.ProceedButton, "rest-site proceed", requireUnattempted: true);
    }

    private static OutsideDecision? FindMerchantDecision(NMerchantRoom room)
    {
        SetSurface(room);
        var inventory = room.Inventory;
        if (IsActive(inventory) && inventory.IsOpen)
        {
            _merchantOpenedInRoom = _surfaceId;
            var removal = inventory.GetAllSlots().OfType<NMerchantCardRemoval>().FirstOrDefault();
            if (removal is not null && removal.Entry.IsStocked && removal.Entry.EnoughGold)
            {
                if (_awaitingMerchantCardRemoval
                    || AttemptedOnSurface.Contains(removal.Hitbox.GetInstanceId()))
                {
                    return null;
                }

                return IsUsable(removal.Hitbox)
                    ? new OutsideDecision(
                        room,
                        removal.Hitbox,
                        "open merchant card removal",
                        StartsMerchantCardRemoval: true)
                    : null;
            }

            // Do not buy arbitrary inventory items. If removal is absent, used,
            // or unaffordable, first-legal deliberately leaves the shop.
            var back = inventory.GetNodeOrNull<NClickableControl>("%BackButton");
            return FromControl(
                    room,
                    back,
                    "leave merchant (card removal unavailable or unaffordable)",
                    requireUnattempted: true)
                ?? FromFirstUnattempted(room, Descendants<NButton>(inventory), "close merchant inventory");
        }

        if (_merchantOpenedInRoom != _surfaceId)
        {
            var open = FromControl(room, room.MerchantButton, "open merchant inventory");
            return open is null ? null : open with { MarksMerchantOpened = true };
        }

        return FromControl(room, room.ProceedButton, "merchant-room proceed", requireUnattempted: true);
    }

    private static OutsideDecision? FindTreasureDecision(NTreasureRoom room)
    {
        SetSurface(room);
        return FromControl(room, room.GetNodeOrNull<NClickableControl>("Chest"), "open treasure chest", requireUnattempted: true)
            ?? FromFirstUnattempted(room, Descendants<NTreasureButton>(room), "open treasure chest")
            ?? FromFirstUnattempted(room, Descendants<NTreasureRoomRelicHolder>(room), "treasure relic")
            ?? FromControl(room, room.ProceedButton, "treasure-room proceed", requireUnattempted: true);
    }

    private static OutsideDecision? FromFirstUnattempted<T>(
        Node surface,
        IEnumerable<T> controls,
        string description)
        where T : NClickableControl
    {
        SetSurface(surface);
        var control = controls.FirstOrDefault(candidate =>
            IsUsable(candidate) && !AttemptedOnSurface.Contains(candidate.GetInstanceId()));
        return FromControl(surface, control, description);
    }

    private static OutsideDecision? FromFirst<T>(Node surface, IEnumerable<T> controls, string description)
        where T : NClickableControl =>
        FromControl(surface, FirstUsable(controls), description);

    private static OutsideDecision? FromFirstCard(
        Node surface,
        IEnumerable<NCardHolder> holders,
        string description,
        bool requireUnattempted = false)
    {
        SetSurface(surface);
        var holder = holders.FirstOrDefault(candidate =>
            IsActive(candidate)
            && IsUsable(candidate.Hitbox)
            && (!requireUnattempted || !AttemptedOnSurface.Contains(candidate.GetInstanceId())));
        return holder is null
            ? null
            : new OutsideDecision(surface, holder, description, CardHolder: holder);
    }

    private static OutsideDecision? FromControl(
        Node surface,
        NClickableControl? control,
        string description,
        bool requireUnattempted = false) =>
        control is not null && IsUsable(control)
            && (!requireUnattempted || !AttemptedOnSurface.Contains(control.GetInstanceId()))
            ? new OutsideDecision(surface, control, description)
            : null;

    private static T? FirstUsable<T>(IEnumerable<T> controls) where T : NClickableControl =>
        controls.FirstOrDefault(IsUsable);

    private static bool CanClaimReward(NRewardButton button)
    {
        if (button.Reward is not PotionReward)
        {
            return true;
        }

        var state = RunManager.Instance.DebugOnlyGetState();
        return state is not null
            && state.Players.Count == 1
            && state.Players[0].HasOpenPotionSlots;
    }

    private static T? FindActiveNode<T>() where T : Node
    {
        var tree = Engine.GetMainLoop() as SceneTree;
        return tree is null
            ? null
            : Descendants<T>(tree.Root).FirstOrDefault(IsActive);
    }

    private static IEnumerable<T> Descendants<T>(Node root) where T : Node
    {
        foreach (var child in root.GetChildren())
        {
            if (child is T match)
            {
                yield return match;
            }

            foreach (var descendant in Descendants<T>(child))
            {
                yield return descendant;
            }
        }
    }

    private static bool IsUsable(NClickableControl control) =>
        IsActive(control) && control.IsEnabled;

    private static bool IsActive([NotNullWhen(true)] Node? node) =>
        node is not null
        && GodotObject.IsInstanceValid(node)
        && node.IsInsideTree()
        && (node is not CanvasItem canvasItem || canvasItem.IsVisibleInTree());

    private static void SetSurface(Node surface)
    {
        var id = surface.GetInstanceId();
        if (_surfaceId == id)
        {
            return;
        }

        _surfaceId = id;
        _lastControlId = 0;
        _completedSingleChoiceSurfaceId = 0;
        AttemptedOnSurface.Clear();
        _surfaceReadyAt = System.Environment.TickCount64 + SurfaceSettleMilliseconds;
    }

    private sealed record OutsideDecision(
        Node Surface,
        Node Target,
        string Description,
        bool MarksMerchantOpened = false,
        NCardHolder? CardHolder = null,
        bool CompletesSingleChoice = false,
        bool StartsMerchantCardRemoval = false,
        bool CompletesMerchantCardRemoval = false)
    {
        internal NClickableControl? Control => Target as NClickableControl;
    }
}
