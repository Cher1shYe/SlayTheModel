namespace SlayTheModel.Search;

/// <summary>Outcome bands keep progress shaping below a genuine victory.</summary>
public static class CombatRolloutReward
{
    public static double Evaluate(bool won, bool dead, int playerHp, int maxHp,
        int rolloutStartHp, double enemyDamageFraction, double incomingDamage)
    {
        if (!double.IsFinite(enemyDamageFraction) || enemyDamageFraction < 0 || enemyDamageFraction > 1)
            throw new ArgumentOutOfRangeException(nameof(enemyDamageFraction));
        if (!double.IsFinite(incomingDamage) || incomingDamage < 0)
            throw new ArgumentOutOfRangeException(nameof(incomingDamage));
        if (dead || playerHp <= 0) return -1;
        if (maxHp <= 0) throw new ArgumentOutOfRangeException(nameof(maxHp));
        if (won) return 0.9 + 0.1 * Math.Clamp((double)playerHp / maxHp, 0, 1);
        var loss = Math.Clamp(((double)rolloutStartHp - playerHp) / Math.Max(1, rolloutStartHp), -0.5, 1);
        var positiveLoss = Math.Max(0, loss);
        var risk = Math.Clamp(incomingDamage / Math.Max(1, playerHp), 0, 1);
        return Math.Clamp(-0.1 + 0.9 * enemyDamageFraction - 0.55 * loss
            - 0.25 * positiveLoss * positiveLoss - 0.25 * risk * risk, -0.8, 0.8);
    }
}
