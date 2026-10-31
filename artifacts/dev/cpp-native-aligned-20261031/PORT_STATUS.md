> **2026-10-31 暂停更新：第二部分为 WIP，尚未集成完成。** 用户已要求停止开发并自行上传到 `workspace_YE`。下文的第一部分完成记录属于历史已验证状态；当前源码已加入四角色扩展和新布局，尚未完成完整构建、schema/快照/观察接口及差分回归。不要把旧 v4 身份声明或现存二进制当作当前源码已验证。最新断点见仓库根 `docs/native-port-step2-wip-20261031.md`，恢复前先读该记录。

# C++ 原生规则对齐：第四轮第一部分

2026-10-31。当前开发副本，基线 `be401e8`；目标 `v0.111.0 / 41cef1ea`，
DLL SHA-256：`9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`。

**第一部分已完成：自伤累计、局外降级费用恢复、遗物计数关联。**
当前 ruleset 为 `native-41cef1ea-port-v4`，`NATIVE_PARITY_COMPLETE=false`。
下一部分是遗物的真实选牌/跳过和持续状态；3～5步是工作划分预期，不是完整等价的完成承诺。

## 本步修改

- Crimson Mantle / Inferno 分别保存每次实际出牌或重放累计的 SelfDamage，升级改变能力数值而不改变一次自伤增量。保留两能力首次获得顺序；移除重获会清零并重新排序。
- Inferno 只在己方回合受到实际伤害时触发；敌方回合、直接扣血和完全挡住的伤害不触发。Tungsten Rod / Beating Remnant 减伤先于 Buffer，归零后不消耗 Buffer。
- Reflections 和 Wongo 离开分支统一调用降级函数，恢复基础费用/关键词，保留卡牌实例、附魔、成长和已独立表达的费用状态。
- Touch of Orobas 原位替换首件起始遗物，初始化新遗物计数并经过获取钩子，不扰乱其他遗物的计数。没有起始遗物时在变更前拒绝；已升级起始遗物按原生回退 Circlet。
- 新获取遗物清零空槽计数；Toy Box 的既有删除路径同步移动 ID/计数并清理尾槽。这里只修数组一致性，Toy Box 蜡制遗物规则仍未补齐。
- 新状态接入 clone、快照校验、公开观察和 Python 绑定；公开战斗观察末尾追加3维，原有偏移不变。局外 ArmG 编码布局不变，工作进程入口版本检查同步更新。

## 本步验证

| 检查 | 结果 |
| --- | --- |
| 实际目标 DLL 新样例 | 95个：自伤56、降级28、遗物替换11，C++对照通过 |
| C++回归程序 | 27个全部通过；自伤1379项检查、遗物替换293项检查 |
| 快照与隐藏状态 | 6742个运行中快照、6000次重采样通过；新状态另测32次重采样、克隆/恢复后续、非法状态拒绝与新战斗清零 |
| Python检查 | 131通过、4跳过（缺少可选历史训练/网站数据） |
| 局外桥接工作进程 | 使用临时未训练的当前格式模型启动后EOF，退出0；未操作游戏UI |
| 贪心整局冒烟 | 1000局正常终止，0异常、0截断，平均9.5层、0胜，约114.8局/秒 |

吞吐只代表本机这次贪心测试，不是训练速度或模型能力。没有重新训练，也没有证明完整同种子整局原生等价。
原始权重SHA-256未变：`cfcb115024b0b0a222b88bf0033ef55e1e7b3cf667194c9dbba36b923180b91c`。

新证据在 `validation/round4-step1/`，原生宿主/结果在 `native-round4-step1-{card,downgrade,relic}-fixtures/`。
首次测试失败也保留：降级测试的不可打出费用标记转换错误已纠正，原生结果未修改；旧迁移测试已改为要求现有身份保护，未放宽加载规则。
第三轮报告/原生结果未覆盖，其当时的总览保存在 `validation/round4-step1/source-before/PORT_STATUS.md`。

## 当前版本与限制

- 观察schema13、动作schema12、ArmG feature4、快照v8。卡牌ID不变：223；卡牌特征251、战斗动作343、ArmG动作1300。
- 公开观察46082维＝战斗29691＋局外16391。旧快照/模型依然须通过身份检查；没有审核好的旧权重迁移方案。
- 本步降级修复用于两个牌组事件。完整战斗费用修正栈仍缺少来源信息，例如 Snecko 和 Frantic Escape；不宣称任意战斗中降级已完整等价。
- 原生最终死亡会清空全部能力，C++保留既有终局能力值。本步验证致死效果与失败结果，不包含全局死亡清理对齐。
- Splash / Mad Science、复杂遗物真实选择和持续机制、34项缺失事件、Aeonglass Boss、完整账号过滤与房间生成时序仍待完成。
- 原生桥接的活动选牌网格、Pael暂存范围与游戏UI执行仍不完整。

## 复现与交付

```sh
/opt/anaconda3/bin/python validation/build_local.py
/opt/anaconda3/bin/python validation/round4-step1/run_cpp_tests.py
/opt/anaconda3/bin/python validation/round4-step1/bridge_startup_check.py
```

Python完整选择命令见 `validation/round4-step1/commands.txt`。本机用Apple clang/Python3.11验证；未验证Windows或CMake构建。
源码增量补丁：`validation/round4-step1/native-rules-port-v4-step1.patch`，对本步前v3源码备份做apply检查。
第三轮累计基线补丁仍保留。补丁不含游戏DLL、宿主二进制或权重。未提交、推送、部署或发布。
