// Math oracle: actual native v0.111.0/41cef1ea DLL, not simulator-generated goldens.
#include "sts2/common.h"
#include "../json/include/nlohmann/json.hpp"
#include <filesystem>
#include <fstream>
#include <iostream>
#include <limits>
#include <stdexcept>

using nlohmann::json;
using sts2::Rng;

static void require(bool condition, const std::string &label) {
    if (!condition) throw std::runtime_error(label);
}
static void verify_state(const Rng &rng, const json &state, const std::string &label) {
    require(rng.counter == state.at("counter").get<std::int32_t>(), label + ": counter");
    require(rng.state() == state.at("words").get<std::array<std::uint64_t, 4>>(), label + ": words");
    require(rng.valid_snapshot_state(), label + ": valid state");
    Rng restored;
    restored.restore_state(rng.state(), rng.counter);
    Rng copy = rng;
    for (int i = 0; i < 3; ++i)
        require(copy.next_unsigned_long() == restored.next_unsigned_long(), label + ": restore continuation");
}
static json execute(Rng &rng, const json &step) {
    const auto op = step.at("op").get<std::string>();
    const auto &p = step.at("parameters");
    if (op == "int") return rng.next_int_exclusive(p.at(0).get<int>());
    if (op == "range") return rng.next_int_range(p.at(0).get<int>(), p.at(1).get<int>());
    if (op == "bool") return rng.next_bool();
    if (op == "gaussian") return rng.next_gaussian_int(p.at(0).get<int>(),p.at(1).get<int>(),p.at(2).get<int>(),p.at(3).get<int>());
    if (op == "ulong") return rng.next_unsigned_long();
    if (op == "float_bits") {
        const float value = rng.next_float(p.at(0).get<float>(), p.at(1).get<float>());
        std::uint32_t bits; std::memcpy(&bits, &value, sizeof(bits)); return bits;
    }
    if (op == "double_bits" || op == "double_range_bits") {
        const double value = op == "double_bits" ? rng.next_double() :
            rng.next_double(p.at(0).get<double>(),p.at(1).get<double>());
        std::uint64_t bits; std::memcpy(&bits, &value, sizeof(bits)); return bits;
    }
    throw std::runtime_error("Unknown native fixture operation: " + op);
}
int main(int argc, char **argv) {
    const auto fixture = argc > 1 ? std::filesystem::path(argv[1]) :
        std::filesystem::path(__FILE__).parent_path() / "fixtures/native_rng_41cef1ea.json";
    std::ifstream input(fixture);
    require(bool(input), "Missing native RNG fixture: " + fixture.string());
    const json data = json::parse(input);
    require(data.at("oracle_dll_sha256") == "9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4", "Native oracle identity");
    for (const auto &test : data.at("hashes")) {
        const auto text = test.at("text").get<std::string>();
        require(Rng::deterministic_hash_code(std::string_view(text)) == test.at("hash").get<std::uint64_t>(), "xxHash64 UTF-8 vector");
    }
    for (const auto &test : data.at("canonical")) {
        const auto canonical = Rng::canonicalize_seed(test.at("text").get<std::string>());
        require(canonical == test.at("canonical").get<std::string>(), "Native ASCII seed canonicalization");
        require(Rng::deterministic_hash_code(std::string_view(canonical)) == test.at("hash").get<std::uint64_t>(), "Canonical seed hash");
    }
    int checked = 0;
    for (const auto &test : data.at("vectors")) {
        const auto seed = test.at("seed").get<std::uint64_t>();
        Rng rng(seed);
        verify_state(rng, test.at("initial"), "initial seed " + std::to_string(seed));
        for (const auto &step : test.at("steps")) {
            const auto label = "seed " + std::to_string(seed) + ", step " + std::to_string(checked);
            require(execute(rng, step) == step.at("value"), label + ": output " + step.at("op").get<std::string>());
            verify_state(rng, step.at("state"), label);
            ++checked;
        }
    }
    for (const auto &test : data.at("oldRegression")) {
        Rng rng(0);
        int result;
        if (test.at("op") == "long_int") {
            for (int i = 0; i < 155215; ++i) rng.next_int_exclusive(100);
            result = rng.next_int_exclusive(100);
        } else result = rng.next_gaussian_int(100, 10, 0, 200);
        require(result == test.at("value").get<int>(), "Long/Gaussian native vector");
        verify_state(rng, test.at("state"), "Long/Gaussian state");
        require(rng.next_int_exclusive(100) == test.at("next100").get<int>(), "Long/Gaussian next draw");
    }
    {
        Rng rng(22), original = rng;
        bool threw = false;
        try { rng.next_int_exclusive(0); } catch (const std::invalid_argument &) { threw = true; }
        require(threw && rng.counter == 1 && rng.state() == original.state(), "Native max-only invalid bound counter");
        threw = false;
        try { rng.next_int_range(1, 1); } catch (const std::invalid_argument &) { threw = true; }
        require(threw && rng.counter == 1 && rng.state() == original.state(), "Native two-bound validation before counter");
        rng.restore_state(original.state(), std::numeric_limits<std::int32_t>::max());
        rng.next_double();
        require(rng.counter == std::numeric_limits<std::int32_t>::min(), "Defined native int32 counter wrap");
        require(rng.valid_snapshot_state(), "Counter wrap does not invalidate seeded state");
        threw = false;
        try { rng.restore_state({}, 0); } catch (const std::invalid_argument &) { threw = true; }
        require(threw, "Reject impossible all-zero seeded state");
        threw = false;
        try { Rng::canonicalize_seed("\xc3\xa9"); } catch (const std::invalid_argument &) { threw = true; }
        require(threw, "Unsupported Unicode canonicalization is explicit");
    }
    {
        Rng high(0x100000016ull), low(22);
        require(high.state() != low.state(), "High seed bits preserved");
        int ascending[] = {0,1,2,3}, descending[] = {3,2,1,0};
        std::sort(descending, descending + 4);
        Rng a(22), b(22);
        a.shuffle(ascending, 4); b.shuffle(descending, 4);
        const int expected[] = {1,2,0,3}; // actual DLL StableShuffle fixture
        require(std::equal(ascending, ascending+4, expected) &&
                std::equal(descending, descending+4, expected), "Native stable/unstable integer shuffle");
    }
    std::cout << "native RNG contract: " << checked << " mixed operations, hashes, states and edge cases passed\n";
}
