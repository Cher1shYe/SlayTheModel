// Sampling randomness is independent of all game RNG streams.
internal static class PolicySampling
{
    internal static double[] Normalize(IReadOnlyList<double> probabilities, int count)
    {
        if (count < 1 || probabilities.Count != count ||
            probabilities.Any(p => !double.IsFinite(p) || p < 0) ||
            Math.Abs(probabilities.Sum() - 1d) > 1e-5)
            throw new InvalidDataException("Invalid behavior policy");
        double total = probabilities.Sum();
        return probabilities.Select(p => p / total).ToArray();
    }

    internal static int Sample(IReadOnlyList<double> probabilities, double uniform)
    {
        if (!double.IsFinite(uniform) || uniform < 0 || uniform >= 1)
            throw new InvalidDataException("Invalid sampling uniform");
        double sum = 0;
        for (int i = 0; i < probabilities.Count; i++)
        {
            sum += probabilities[i];
            if (uniform < sum) return i;
        }
        throw new InvalidDataException("Incomplete sampling distribution");
    }
}
