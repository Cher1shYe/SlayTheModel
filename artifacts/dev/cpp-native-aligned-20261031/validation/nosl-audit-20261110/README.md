# NoSL audit — 2026-11-10

检查与受控复现，未修改生产源码、Python 扩展或远端实验。

完整中文说明：仓库根 `docs/mcts-nosl-audit-20261110.md`。

进度：

1. 跟踪 `MacroEnv` → `play_combat_mcts` → `mcts` → `resample_hidden`，核实公开节点分支和单动作执行路径。
2. 旧隐藏状态测试通过；新增同名成长牌、公开编码新增属性和 `orbRng` 反例。15 个检查项中 7 个失败，不能认证严格 NoSL。
3. 源码缓存指纹一致后，仅链接审计程序；结果与复现种子见 `probe.txt`，完整来源见 `results.json`。

`run_audit.py` 在发现失败时返回 1。不要覆盖本次证据来证明修复；下一轮使用新目录。
