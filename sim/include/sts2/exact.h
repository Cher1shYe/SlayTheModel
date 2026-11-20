#pragma once
// Exact rational arithmetic for damage/block modifiers. Native uses System.Decimal,
// which is exact for every multiplier here (0.75, 0.7, 1.5, 1.1 ...); binary floating
// point is not (15 * 3 * 1.4 = 62.99999999999999 in double, 63 in decimal).
#include <cmath>
#include <cstdint>
#include <numeric>

namespace sts2 {

struct Exact {
    std::int64_t n = 0, d = 1;

    static Exact of(std::int64_t num, std::int64_t den = 1) {
        if (den < 0) { num = -num; den = -den; }
        const std::int64_t g = std::gcd(num < 0 ? -num : num, den);
        return g > 1 ? Exact{num / g, den / g} : Exact{num, den};
    }
    // Engine helpers return multipliers as double: short decimals (1.25, 0.5, 1.1) and
    // ratios such as Debilitate's 2.0 / 1.5 = 4/3. Recover the exact fraction: the best
    // rational approximation with denominator <= 10000 (continued fractions).
    static Exact of_double(double x) {
        const bool negative = x < 0;
        double rest = negative ? -x : x;
        std::int64_t p0 = 0, q0 = 1, p1 = 1, q1 = 0;
        for (int i = 0; i < 64; ++i) {
            const double whole = std::floor(rest);
            const std::int64_t a = static_cast<std::int64_t>(whole);
            const std::int64_t q2 = a * q1 + q0;
            if (q2 > 10000) break;
            const std::int64_t p2 = a * p1 + p0;
            p0 = p1; q0 = q1; p1 = p2; q1 = q2;
            const double frac = rest - whole;
            if (frac < 1e-9) break;
            rest = 1.0 / frac;
        }
        return of(negative ? -p1 : p1, q1);
    }

    Exact operator+(Exact o) const { return of(n * o.d + o.n * d, d * o.d); }
    Exact operator*(Exact o) const {
        const std::int64_t g1 = std::gcd(n < 0 ? -n : n, o.d), g2 = std::gcd(o.n < 0 ? -o.n : o.n, d);
        const std::int64_t x = g1 ? g1 : 1, y = g2 ? g2 : 1;
        return of((n / x) * (o.n / y), (d / y) * (o.d / x));
    }
    bool operator<(Exact o) const { return n * o.d < o.n * d; }
    // (int)decimal truncates toward zero; callers clamp to >= 0 first.
    int truncate() const { return static_cast<int>(n / d); }
    double to_double() const { return static_cast<double>(n) / static_cast<double>(d); }
};

}  // namespace sts2
