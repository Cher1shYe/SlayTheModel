namespace SlayTheModel.Search;

/// <summary>Outcome bands keep progress shaping below a genuine victory.</summary>
public static class CombatRolloutReward
{
    public static double Evaluate(
        bool won,
        bool dead,
        int playerHp,
        int entryHp,
        double enemyDamageFraction)
    {
        if (!double.IsFinite(enemyDamageFraction)
            || enemyDamageFraction < 0
            || enemyDamageFraction > 1)
        {
            throw new ArgumentOutOfRangeException(nameof(enemyDamageFraction));
        }

        if (won && !dead)
        {
            return 0.5 + Math.Atan(((double)playerHp - entryHp) / 20.0) / Math.PI;
        }

        // Damage is the endpoint HP deficit of the fixed root cohort. It is
        // not accumulated damage, so healing and revival reduce the progress.
        // A loss remains below every unresolved living rollout.
        return (dead ? -1.0 : -0.5) + 0.49 * enemyDamageFraction;
    }
}
