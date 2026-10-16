namespace SlayTheModel.Search;

/// <summary>Outcome bands keep progress shaping below a genuine victory.</summary>
public static class CombatRolloutReward
{
    public static double Evaluate(bool won, bool dead, int playerHp, int entryHp, double enemyDamageFraction)
    {
        if (!double.IsFinite(enemyDamageFraction) || enemyDamageFraction < 0 || enemyDamageFraction > 1)
            throw new ArgumentOutOfRangeException(nameof(enemyDamageFraction));
        if (won && !dead)
            return 0.5 + Math.Atan(((double)playerHp - entryHp) / 20.0) / Math.PI;
        // Damage is net HP removed from a fixed root cohort, not accumulated
        // damage events. Death cannot outrank an unresolved living rollout.
        if (dead)
            return -1.0 + 0.49 * enemyDamageFraction;
        if (entryHp <= 0)
            throw new ArgumentOutOfRangeException(nameof(entryHp));
        // Net loss relative to combat entry: healing removes the penalty,
        // without rewarding healing beyond entry HP. Equal percentage weights
        // stay inside the living-cutoff band [-0.5, -0.01].
        var playerLossFraction = Math.Clamp(((double)entryHp - playerHp) / entryHp, 0.0, 1.0);
        return -0.255 + 0.245 * (enemyDamageFraction - playerLossFraction);
    }
}
