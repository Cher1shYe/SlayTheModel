# 现有 XS 训练器的原生采集桥接

新增独立 `collection-pilot` worker 模式，对接同工作区 `sts2-rl-agent/scripts/check_native_collection.py`。与已有 `NativeEvolution` 不同，此入口只执行有上限的原生采集／策略比较，不负责模型更新、晋级或正式训练。

范围为 BYRDONIS_ELITE 与未修改的初始打击／防御／痛击。每个真实决策独立捕获原生状态核对特征及合法动作；新快照的局部历史计数通过已执行输入和原生 DamageReceivedEntry 补齐，不能复制预测值伪造一致。每个非终局动作核对完整 continuation，终局核对胜负／HP／奖励。完整对局逐场原子写入指定新文件；不覆盖已有场次。

搜索支持纯策略、原生 UCT、学习先验 PUCT 三组。每个决策使用新树，访问次数只包含该决策；学习先验通过外部项目的 `native_pilot_service.py` 推理，与训练导入共用特征 codec。未访问合法动作显式为 0。原生合法动作表可能合并同状态手牌副本，外部 codec 按等价动作组检查完整性。

本轮 18 场、281 个决策核对通过；Release worker 构建及 ReplaySearch smoke 通过。原生 UCT／学习先验 PUCT 的搜索吞吐约 716／161 次模拟每秒，均为 3/6 胜，与纯网络相同。没有广泛卡牌／遭遇兼容性或强度增益结论。详细输出、两步 Learner 接线检查及原生数据兼容性说明在外部项目 `docs/NATIVE_COLLECTION_PILOT_20261019.md`。

现有游戏 Adapter、Collector、NativeEvolution 与玩家默认策略均未切换到此模式，CombatSolver 引擎没有修改。
