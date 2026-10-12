
    // TEMPORARY SPIKE — measures the engine's per-step cost. Remove after the experiment.
    public Dictionary<string, object?> StepBench(int maxSteps = 60)
    {
        var player = _runState?.Players?.FirstOrDefault();
        if (player == null) return Error("no run in progress");

        var playMs = new List<double>();
        var endMs = new List<double>();
        var enqMs = new List<double>();
        var waitMs = new List<double>();
        int played = 0, ended = 0, skipped = 0;

        for (int step = 0; step < maxSteps; step++)
        {
            if (!CombatManager.Instance.IsInProgress) break;
            var state = CombatManager.Instance.DebugOnlyGetState();
            var pcs = player.PlayerCombatState;
            if (state == null || pcs == null) break;

            int idx = -1; CardModel? card = null; Creature? target = null;
            var hand = pcs.Hand.Cards;
            for (int i = 0; i < hand.Count; i++)
            {
                var c = hand[i];
                if (!c.CanPlay(out _, out _)) continue;
                Creature? t = null;
                if (c.TargetType == TargetType.AnyEnemy)
                {
                    var alive = state.Enemies.Where(e => e != null && e.IsAlive).ToList();
                    if (alive.Count == 0) continue;
                    t = alive[0];
                }
                idx = i; card = c; target = t; break;
            }

            if (idx >= 0 && card != null)
            {
                var sw = Stopwatch.StartNew();
                var act = new PlayCardAction(card, target);
                RunManager.Instance.ActionQueueSet.EnqueueWithoutSynchronizing(act);
                var t1 = sw.Elapsed.TotalMilliseconds;
                WaitForActionExecutor();
                var t2 = sw.Elapsed.TotalMilliseconds;
                enqMs.Add(t1); waitMs.Add(t2 - t1); playMs.Add(t2);
                played++;
                // if nothing changed, avoid a spin
                if (t2 < 0.001) { skipped++; if (skipped > 3) break; }
            }
            else
            {
                var sw = Stopwatch.StartNew();
                DoEndTurn(player);
                endMs.Add(sw.Elapsed.TotalMilliseconds);
                ended++;
            }
        }

        // cost of building the CLI decision payload (pure overhead for search)
        var detectMs = new List<double>();
        for (int i = 0; i < 5 && CombatManager.Instance.IsInProgress; i++)
        {
            var sw = Stopwatch.StartNew();
            DetectDecisionPoint();
            detectMs.Add(sw.Elapsed.TotalMilliseconds);
        }

        static Dictionary<string, object?> Stat(List<double> xs)
        {
            if (xs.Count == 0) return new Dictionary<string, object?> { ["n"] = 0 };
            var s = xs.OrderBy(x => x).ToList();
            return new Dictionary<string, object?>
            {
                ["n"] = s.Count,
                ["mean_ms"] = Math.Round(s.Average(), 3),
                ["p50_ms"] = Math.Round(s[s.Count / 2], 3),
                ["p95_ms"] = Math.Round(s[Math.Min(s.Count - 1, (int)(s.Count * 0.95))], 3),
                ["min_ms"] = Math.Round(s[0], 3),
                ["max_ms"] = Math.Round(s[^1], 3),
                ["total_ms"] = Math.Round(s.Sum(), 1),
            };
        }

        return new Dictionary<string, object?>
        {
            ["type"] = "step_bench",
            ["played"] = played,
            ["ended_turns"] = ended,
            ["enqueue"] = Stat(enqMs),
            ["wait_for_executor"] = Stat(waitMs),
            ["play_card_total"] = Stat(playMs),
            ["end_turn_total"] = Stat(endMs),
            ["detect_decision_point"] = Stat(detectMs),
        };
    }
