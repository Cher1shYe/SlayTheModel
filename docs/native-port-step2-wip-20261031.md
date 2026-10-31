# C++ 原生规则对齐：第二部分暂停记录

2026-10-31，用户要求停止继续开发、释放资源，由用户自行上传到 `workspace_YE`。
本次提交是 **WIP 工作检查点，不是第二部分完成版，也不是可训练版本**。

## 工作位置和版本

- 可编辑副本：`artifacts/dev/cpp-native-aligned-20261031/`。
- C++ 来源：`be401e8ba09ac58c9f3b01cf77e195f7122c8d0c`。
- 原生参照：`v0.111.0 / 41cef1ea`；DLL SHA-256 为 `9cb4f1ad8c9f284aa8fec3122ffd6d780bbf543d875c817abdd12ff63fbf12b4`。
- 第一部分完成版仍有独立证据：开发副本内 `validation/round4-step1/`。
- 第二部分开始前的源码备份：`validation/round4-step2/source-before/` 及其 manifest。它表示已验证的第一部分源码，不能与当前 WIP 源码混为一谈。
- 暂停时源码仍保留旧 ruleset v4、观察/动作 13/12、ArmG feature4、快照8声明；这些声明尚未随新布局升级。现存 Python 扩展/可执行文件也不是当前源码的完整新构建。

## 本轮范围与已经落盘的工作

用户最初要求补齐遗物的真实选择、跳过和持续状态；随后明确要求同时扩展另四个角色的完整牌池及相关机制。当前仍以铁甲单人、包括跨角色生牌为主；这不等于另外四个角色的整局流程已完成。

- 实际目标 DLL 导出了五角色牌池顺序、全部卡牌基础/升级数据。保留旧 ID，追加缺失词表；当前生成数据含 596 条卡牌记录（含保留的 Grapple），CardId::COUNT 为 597。原生 Sloth 保持旧 SLOTH_STATUS ID，Null 使用 NULL_CARD 避免宏冲突。
- Lead Paperweight、Sea Glass、Arcane Scroll、Dream Catcher、Dusty Tome 的奖励候选生成及相关 RNG/遗物联动已有独立实现与对照；局外 15 候选选择、预配置角色/卡牌和恢复流程正在接入。
- Toy Box 蜡制遗物、Small/Large Capsule 生命周期，以及 Bone Tea、Fake Venerable Tea Set、Byrdpip/鸟蛋已有独立模块；固定物理药槽、Delicate Frond 和 Alchemical Coffer 改动尚在集成。
- 静默猎手、故障机器人、亡灵契约师的卡牌/机制源文件及原生样例已落盘；储君的卡牌分支和状态/API头文件已落盘，`simulator/src/regent.cpp` 尚未实现。
- 公共费用修正、Sly/Retain、充能球、Osty、星星、父卡牌执行帧和自动打牌队列开始接入。伤害、能力和回合代码已拆到 `battle_damage.cpp`、`battle_powers.cpp`、`battle_turns.cpp`，仍需完成统一调度。

## 验证边界

下表各项是独立目录内实际目标 DLL 的受控记录；原生样例生成成功不表示当前 C++ 已通过对应差分。

| 样例目录后缀 | 记录数 | 当前 C++ 状态 |
| --- | ---: | --- |
| card-reward | 82 | 早期集成构建通过 5932 项检查 |
| persistent | 18 | 早期集成构建通过 415 项检查 |
| relic-lifecycle | 24 | 早期 C++ 测试因 Large Capsule 新增牌漏蛋类升级失败；通用加牌钩子已修改，未复跑 |
| silent | 240 | 新差分测试已写，尚未完成集成运行 |
| necrobinder | 198 | 包括 184 个卡牌执行、2 个单人无队友目标记录、12 个机制样例；尚未完成 C++ 集成差分 |
| defect | 176 | 172 个卡牌基础/升级记录及 4 个充能球记录；尚未完成 C++ 集成差分 |

早期集成结果保留在 `validation/round4-step2/relic-integration-initial.json`。之后又修改了共享布局和执行机制，因此其通过结果不覆盖暂停时全部源码。暂停时没有运行新的全量构建、Python回归、整局冒烟或训练；当前源码尚未闭环，不能声明编译通过或原生等价。

## 恢复工作时的顺序

1. 重新核对文件和分工。此前并行任务已停止，不自动恢复旧 agent。
2. 完成储君机制、通用卡牌费用和自动打牌/选牌恢复；将各角色钩子接入初始化、抽牌、生成、打牌、伤害和回合流程。当前 `draw_cards` 声明/实现、新增调用与缺失定义仍待统一，回合状态机尚未完成。
3. 完成药槽空位模型、遗物奖励继续执行、Dream Catcher 正常奖励和 Prismatic Gem 全角色奖励池；检查 Splash、跨角色生成与单人过滤。
4. 统一 clone/快照校验/隐藏状态重采样、公开观察、Python绑定、ArmG和动作编码。补全可见/隐藏自动队列区别；新的 `AutoPlayRequest.visible` 尚未在所有入队路径正确赋值。
5. 统一 ruleset、schema、snapshot、引擎身份；重建后逐项跑新角色和遗物差分，再跑旧回归。修复每个失败后再汇总完成状态，保留此前失败证据。

已确认的注意点：负 Strength/Focus 等能力是否被 Artifact 拦截取决于原生 `GetTypeForAmount`，不能只看静态 Buff 类型；`Single` 也不能直接把 Amount 限制为1。多选中暂存实体、Nightmare 模板、父执行帧和药槽空位都需正确处理身份与观察。

## 上传方式

根 `.gitignore` 忽略 `artifacts/`，普通 `git add .` 不会上传主要 C++ 改动。
使用同目录 `native-port-step2-upload-paths.txt` 的明确清单强制添加。
清单包含当前开发源码、构建依赖头文件、测试/宿主源代码、文本证据与源码备份；排除了游戏 DLL、复制的游戏 App、原生反编译树、模型权重、编译产物、缓存和根目录无关改动。

```sh
cd /Users/yebohou/SlayTheModel
git switch workspace_YE
git --literal-pathspecs add -f --pathspec-from-file=docs/native-port-step2-upload-paths.txt
git diff --cached --stat
git commit -F docs/native-port-step2-commit-message.txt
git push -u origin workspace_YE
```

以上命令由用户执行。本次仅准备本地文档和上传清单，没有代为暂存、提交或推送。
