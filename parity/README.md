# 原生宿主与逐步对照

这里用备份的 **v0.111.0 / 41cef1ea 原生 DLL** 在 Godot 无界面模式中运行，通过本机 HTTP 读取决策和执行动作，再与 C++ 模拟器对照。不会修改 `artifacts/preserved-game-versions/` 中的游戏备份。

当前模拟器 ruleset 为 **`native-41cef1ea-port-v14`**；本轮静态怪物数值导出与动态规则修正见 [怪物数值核对报告](../docs/monster-number-audit.md)。

**2026-11-19 已完成 31 个动作、32 个决策点的完整公共接口对照。** 铁甲 A10、种子 `PARITY0001`，从 Neow、首战一直到领金币/药水、卡牌奖励跳过后重开并领取，再返回地图；全部公共事实、网络输入张量和合法动作语义相符。双方末态 **51/80 HP、258 金币、12 张牌、Ashwater**。新原始帧与离线回归在 `fixtures/native-public-first-combat-rewards-parity0001-a10/`。这证明该轨迹的接口一致，不代表其他场景、整局或 A1–A10 所有规则一致。旧 24 步公开子集记录保持原样。

## 本机编译和启动

以下命令已在这台 Mac 使用。Python `/opt/anaconda3/bin/python` 是 3.11，含 numpy、pytest、torch；现有扩展是 Python 3.11 ABI。运行前按仓库 `AGENTS.md` 编译 C++ 模拟器。

```sh
cd /Users/yebohou/SlayTheModel

DOTNET_CLI_HOME="$PWD/parity/stage/dotnet-home" artifacts/tools/dotnet-sdk/dotnet build parity/host-src/Sts2.HeadlessHost.csproj \
  -c ExportRelease --no-restore -p:UseSharedCompilation=false \
  -p:Sts2ManagedDir=/Users/yebohou/SlayTheModel/artifacts/preserved-game-versions/sts2-v0.111.0-41cef1ea-macos-20261110/SlayTheSpire2.app/Contents/Resources/data_sts2_macos_arm64

/opt/anaconda3/bin/python parity/stage.py \
  --game artifacts/preserved-game-versions/sts2-v0.111.0-41cef1ea-macos-20261110/SlayTheSpire2.app \
  --platform macos

bash parity/run_host.sh 18779 SlayTheModelParity20261118
```

宿主在前台运行，日志是 `parity/stage/godot-18779.log`，存档目录是 `~/Library/Application Support/SlayTheModelParity20261118`。`run_host.sh` 默认端口为 18777；上面显式使用 18779。对照脚本不会自行启动或停止宿主。修改 C# 后需要重新 build、stage，并重新启动宿主，正在运行的进程不会加载新字段。

`stage.py` 也有 Windows 分支，但这里记录的是已经执行过的 macOS 路径。`--no-restore` 使用已准备好的 .NET/Godot 依赖；缺少依赖时先处理构建环境，不能把启动失败当游戏差异。

## 对照命令

只读当前原生决策，并在模拟器端从指定种子初始化进行一次比较：

```sh
/opt/anaconda3/bin/python parity/compare.py \
  --url http://127.0.0.1:18779 --seed PARITY0001 --ascension 10 \
  --sim-profile fresh-unlocked-host
```

不带 `--new-run` 不创建原生新局；不带动作序列或 `--steps` 不提交游戏动作。若原生已经走到后续决策，上述命令不会猜测或重建历史，会报告与刚初始化模拟器的差异。

创建新的原生诊断对局，并严格执行已保存的 **Golden Pearl → Proceed → 地图 (0,1)** 三个选择：

```sh
/opt/anaconda3/bin/python parity/compare.py \
  --url http://127.0.0.1:18779 --seed PARITY0001 --ascension 10 \
  --new-run --sim-profile fresh-unlocked-host \
  --actions parity/fixtures/native-opening-parity0001-a10/actions.json
```

动作文件写语义，如 `{"kind":"neow_proceed","args":[]}`，不写原生菜单下标。只有本决策的运行身份、已覆盖公共状态和整套合法动作都通过核验，才执行指定动作。独立 Proceed 是真实选择，不能自动跳过。另一种诊断方式是 `--steps N --diagnostic-policy first-legal`，显式选择模拟器当前第一项合法动作；这只是确定性接口测试，**不是训练模型或游戏策略评估**。

若要重放本轮完整验证的首战及领奖，将 `--actions` 设为 `parity/fixtures/native-public-first-combat-rewards-parity0001-a10/actions.json`（31 个动作）。

若要重放旧整场首战序列，把上述 `--actions` 路径改为 `parity/fixtures/native-first-combat-parity0001-a10/actions.json`。该序列含 24 个动作。旧保存帧缺少新的完整公共观察和奖励元数据，离线历史回归仍停在该边界；最新宿主已导出这些字段，新的在线重放必须单独检查并保留报告。

`fresh-unlocked-host` 只适用于新原生存档、宿主已解锁全部 epoch 的上下文：0 局历史、首次尚未发现 Underdocks、没有已见遭遇、未见 Aeonglass。它不会清空或修改原生存档。如果真实进度不同，用 `--sim-context context.json` 显式传入对应的 `NativeProgressContext` 字段；不要为了凑出相同选项而猜隐藏状态。`config.json` 会记录最终实际使用的全部模拟器进度字段。默认 `--sim-profile default` 保留模拟器默认开局条件，与新宿主存档并不等价。

## 报告与停止条件

默认输出在 `parity/stage/reports/<UTC时间>-<种子>-<编号>/`，可用 `--reports` 指定父目录：

- `config.json`：种子、升阶、模拟器 ruleset、目标 DLL 哈希、进度上下文、诊断动作。
- `decision-XXXX-native.json`：未改写的原生 HTTP 状态。
- `decision-XXXX-comparison.json`：两端投影、状态差异、动作差异；执行前先记录具体请求，执行后记录响应。
- `summary.json`：停止原因、已提交动作数和已通过比较的决策数。异步原生错误的最后状态另存为 `native-error.json`。

原生 `runIdentity` 的 seed（原生规范化形式）、character、ascension、gameVersion、gameCommit、gameDllSha256 单独核验。模拟器 ruleset 记入报告。身份信息用于核实对照来源，不进入策略观察；相同初始血量和牌组不等于相同运行身份。

轮询需要新的 revision、ready 状态和连续稳定快照，且受 `--ready-timeout` 限制；不假设等固定几秒就完成。`ready` 中带 `error` 也会停止。HTTP 状态错误、非 JSON 响应和 JSON 格式错误分别报告；动作 POST 失败不自动重试，不继续走模拟器。

退出码：0 为比较到指定动作上限或序列结束；2 为差异；3 为未支持；4 为宿主/身份/传输错误；5 为原生接受动作后模拟器拒绝或抛错。此时保留两端不同步的证据并停止，不重试。退出码 0 只证明该报告模式下实际走过的决策通过，**不表示整局或未走过的状态一致**。

## 当前接口与验证边界

v12 新增 `train/spire_rl/public_obs.py`，协议 **`spire.public/1`**。两端公开事实经过同一个编码器，再由 `UnifiedNetConfig(observation_schema="spire.public/1")` 构造的同一个网络消费。旧 `obs.observe` / legacy 网络仍保留，新公共布局不会静默套用旧权重。新增能力包括：

- 完整牌实例、费用修饰、附魔/苦难、动态变量、公开牌堆、可推知的顶牌；能力显示、结构化意图、遗物计数、物理药槽与排队状态。
- 地图公开图结构与房间、奖励和商店商品、事件当前页、卡牌选择上下限与预览状态。
- 出牌/目标、药水使用与丢弃、奖励领取/重掷/删牌/特殊牌、事件、休息、宝箱、网格及手牌选中/取消/确认等语义动作。

原生 GUID、actionId、模拟器 UID/物理下标只用于路由。抽牌堆随机顺序、RNG、怪物私有 AI 状态不进入模型。公共观察测试会实际改隐藏状态并检查张量不变。

`compare.py` **默认 `--observation-schema spire.public/1`**，比较全部公共事实和每个模型输入张量；通过时为 `aligned_model_interface`。`--observation-schema subset` 仅用于明确缩小范围的历史诊断，不能把它的通过结果写成完整接口通过。缺失字段、未知模型/状态或含糊动作直接中止，不补零、不删合法动作。纯商店打开菜单单独记录为 transport 导航，不作为策略决策；游戏内确认和真实选择必须交给策略。

源码移植/单元测试和实际 DLL 执行是两种证据。当前完整接口的真实覆盖与已发现差异以 `docs/DEVLOG.md` 第 12 节及相应报告为准；更多战斗、复杂遗物组合和整局仍待核实。

## 固定原生样例与测试

`fixtures/native-opening-parity0001-a10/` 保存四个真实原生决策 JSON、当时配置和摘要，`manifest.json` 记录来源目录、UTC时间、DLL身份、固定动作和每份原始文件的 SHA-256。原始字节（包括进程内 GUID）保持不变。样例中的历史差异用于定位问题，不要求未来模拟器继续保持这个错误。

`fixtures/native-first-combat-parity0001-a10/` 保存最终首战的25个原生状态、24步动作及配置/摘要。离线测试逐一比较决策0–23并执行其明确动作，再确认双方都停在奖励页、HP51/80和金币249；奖励页保持 `unsupported`。其中保留了击杀第一只怪、剩余目标序号压缩的真实证据。

```sh
/opt/anaconda3/bin/python -m unittest discover -s parity/tests -v
```

测试包括真实原生开局样例回归，以及候选乱序、重复手牌、敌人换位、缺字段、运行身份不符、HTTP/JSON错误和超时不误推进等契约检查。它们不代替原生逐步战斗和整局执行对照。

## 基础注册导出与核对

v13 的 `NativeRegistryExport.cs` 直接读取真实 DLL 的 ModelDb。完成宿主编译与 stage 后，用独立 parity 存档运行：

```sh
STS2_REGISTRY_OUTPUT="$PWD/parity/stage/native-registry-41cef1ea.json" \
  bash parity/run_host.sh 18779 SlayTheModelParityRegistry20261119
```

该模式不启动 HTTP 服务，导出后自动退出。先在未开局上下文读取 A0 血量，再通过正常开局进入 Ironclad A10 读取升阶血量；不会替换 DLL 规则。每个属性读取失败会明确写入错误。它是离线审计资料，不能进入策略观察。

固定原始输出为 `sim/native-fixtures/native-registry-41cef1ea.json`，不可为了使测试通过修改。重新导出写 stage，再单独审查来源和差异。卡牌还与既有完整 `content-metadata.json` 交叉比较，覆盖无 owner 的 Stardust 导出限制。

```sh
python sim/tools/audit_native_registry.py --out docs/registry-audit.json
```

核对范围、修正、历史占位和编号锁说明见 [基础注册报告](../docs/registry-audit.md)。通过表示所列基础注册检查没有未解释差异，不表示各项效果或整局原生对照通过。

## 怪物数值导出与核对

v14 的 `NativeMonsterNumbersExport.cs` 读取真实 DLL 的怪物数值属性，并构造招式意图读取伤害与次数。完成上面的宿主编译与 stage 后，从仓库根目录依次导出 A7、A8、A9、A10：

```sh
for ascension in 7 8 9 10; do
  STS2_MONSTER_NUMBERS_OUTPUT="$PWD/parity/stage/monster-numbers-a${ascension}.json" \
  STS2_MONSTER_NUMBERS_ASCENSION="$ascension" \
    bash parity/run_host.sh 18779 "SlayTheModelParityMonsterNumbersA${ascension}"
done
```

`STS2_MONSTER_NUMBERS_OUTPUT` 指定输出文件；设置后宿主进入导出模式，不启动 HTTP 服务，成功写出后自动退出。`STS2_MONSTER_NUMBERS_ASCENSION` 接受 0–10，省略时默认 10。每次先在未开局上下文读取 A0，再正常创建种子 `MONSTERNUMBERS0001` 的 Ironclad 指定升阶对局，读取该升阶的新建怪物模型。属性读取失败保留错误，不注入 Creature 或改写怪物内部状态。

固定原始输出位于 `sim/native-fixtures/native-monster-numbers-41cef1ea/`，包含 `monster-numbers-a7.json`、`monster-numbers-a8.json`、`monster-numbers-a9.json`、`monster-numbers-a10.json` 和 `manifest.json`。manifest 与审计代码同时锁定文件 SHA-256；重新导出写入 stage 后审查差异，不能覆盖固定原始数据使检查通过。

```sh
python sim/tools/audit_monster_numbers.py --out docs/monster-number-audit.json
```

去除重复 A0 后，A0/A7/A8/A9/A10 共 **535 个模型上下文、1,635 个招式上下文、1,075 个攻击上下文，3,215 次血量/伤害/次数比较，0 个未解释差异**。C++ 回归还将相同原始数据与编译后的怪物表比较。The Forgotten 的动态敏捷伤害、Waterfall Giant 压力枪的初值与成长等例外在 [怪物数值核对报告](../docs/monster-number-audit.md) 中单列。

这份导出读取静态 getter 和新建意图，**没有执行原生怪物招式，不是原生战斗对拍**。动态规则的源码核对和 C++ 执行测试不能替代 DLL 中实际走过同一战斗轨迹的证据。
