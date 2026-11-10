#pragma once
// Locates the C++ port root (the directory holding simulator/ and the
// native-*-fixtures/ result folders) at run time, so test binaries keep
// working after the checkout is synced to another path or machine.
// Order: $STS2_PORT_ROOT, then the current directory and its parents, then
// the executable-independent compile-time location as a last resort.
#include <cstdlib>
#include <filesystem>

inline std::filesystem::path port_root() {
    namespace fs = std::filesystem;
    if (const char *env = std::getenv("STS2_PORT_ROOT"); env && *env) return fs::path(env);
    const auto looks_like_root = [](const fs::path &p) {
        std::error_code ec;
        return fs::exists(p / "simulator" / "tests" / "port_root.h", ec);
    };
    std::error_code ec;
    for (fs::path p = fs::current_path(ec); !ec && !p.empty(); p = p.parent_path()) {
        if (looks_like_root(p)) return p;
        if (p == p.parent_path()) break;
    }
    return fs::path(__FILE__).parent_path().parent_path().parent_path();
}
