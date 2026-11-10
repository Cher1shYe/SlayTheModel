# C++ 模拟器工作目录

先读仓库根 [`../../../AGENTS.md`](../../../AGENTS.md)。当前分支为 **`v111_simulator_test`**，这里只维护 C++ 规则、MCTS、公开接口及验证；新的网络与训练工作在 `v111_SF1`，未包含在本分支。

来源是本地 `50d72a6` 的模拟器源码，不是远端 `workspace_YE` v10 的整合版。当前身份：ruleset `native-41cef1ea-port-v6`、观察 v15、动作 v14、快照 v10、ArmG 特征 6、实体观察 v1。目标 `v0.111.0 / 41cef1ea`，DLL SHA-256：
`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`。

**严格 NoSL 审计未通过。** 同名不同实例属性牌的重采样、公开牌堆排序和 `orbRng` 已复现缺口；生产修复尚未实施。先读根 `docs/mcts-nosl-audit-20261110.md`，保留 `validation/nosl-audit-20261110/` 原始失败证据。

详细进度：

- `validation/round4-step2-resume-20261108/README.md`：四角色扩展、真实选择和持续状态。
- `validation/round4-step3-events-20261108/README.md`：第三至六步追加记录，按时间读到末尾。第三步起主要为源码移植，缺 DLL 执行验证。
- `validation/branch-export-20261110/README.md`：本次独立分支构建与检查。

约定：保留真实选择；新增 ID 追加，生成器与生成结果同步；新增状态覆盖 clone、快照、观察、动作和绑定，禁止隐藏未来信息泄漏。测试断言必须开启；从此目录运行测试，或设置 `STS2_PORT_ROOT`。新验证写新目录，不修改旧期望与证据来迁就实现。旧 `agent/`、训练器和实机 worker 不属于新功能开发范围，必要的接口兼容改动要单独说明。未经用户明确授权，不提交、推送或安装模组；不可覆盖原始权重、参考副本或游戏安装备份。
