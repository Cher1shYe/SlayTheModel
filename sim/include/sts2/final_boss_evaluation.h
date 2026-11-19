#pragma once

namespace sts2 {
struct RunContext;

// Evaluation routing is local to one synchronous call on one run. Other
// environments and ordinary simulator callers keep their normal rules.
class FinalBossEvaluationScope {
    inline static thread_local const RunContext* active = nullptr;
    const RunContext* previous;
public:
    explicit FinalBossEvaluationScope(const RunContext& rc) : previous(active) { active = &rc; }
    ~FinalBossEvaluationScope() { active = previous; }
    FinalBossEvaluationScope(const FinalBossEvaluationScope&) = delete;
    static bool applies(const RunContext& rc) { return active == &rc; }
};
}

