# STS1 RL / MCTS 工作区快照

此分支已按要求替换为 `D:\project\sts` 的当前代码快照（2026-10-26），不再包含原来的 STS2 工作区文件。旧内容保留在 Git 历史中。

## 内容

- `sts-rl-agent/`：Jialeiv/sts-rl-agent 源码、文档和发布权重。
- `simulator/`：本地修订后的 sts_lightspeed 源码，包含 Windows 兼容、战斗规则、状态快照以及定时 MCTS 接口。
- `deployment/`：训练启动器、自对弈、评测、数值稳定修复及 fast PUCT 优化。
- `deployment/training_audit_v3/selfplay/`：训练驱动实际使用的兼容源码模板，不包含训练日志。
- `deployment/selfplay_6x40_s64/` 与 `deployment/selfplay_stable_s512_r1/`：仅包含启动器所需的历史源码、配置和指定初始化权重，不是完整实验结果。
- `SOURCE_MANIFEST.json`：复制的本地文件 SHA256 清单。

没有上传虚拟环境、编译产物、临时文件、训练日志、经验池，或当前仍在运行的 10 轮实验目录。

## 获取依赖

```bash
git clone --recurse-submodules --branch snapshot/sts2-workspace-20261012 https://github.com/Cher1shYe/SlayTheModel.git
```

两个 C++ 依赖作为固定版本 submodule 保存。已有克隆需执行 `git submodule update --init --recursive`。

当前实际验证环境为 Windows + Python 3.12 + CPU PyTorch。创建 `.venv`，安装 torch、numpy、tensorboard、cmake、ninja 后，可参考 `deployment/Rebuild.ps1` 编译模拟器；该脚本使用 Visual Studio 2026 Build Tools。Linux 需要重新编译扩展，并适配当前驱动使用的 `simulator/build312/Release` 搜索目录；本快照不宣称已完成 Linux/CUDA 部署验证。

## 训练

通用入口见 `deployment/TRAINING_GUIDE.md`。单次稳定训练入口：

```bash
python deployment/selfplay_compare.py --out deployment/runs/example --rounds 10 --games 40 --epochs 2 --sims 512 --workers 4 --stabilize --fast-puct
```

此命令默认从上游发布的策略/价值权重开始。`deployment/run_selfplay10.py` 则从附带的最近稳定实验第 1 轮权重热启动（优化器和经验池重新初始化）。输出目录必须不存在。它包含前后各 50 局评测、每轮 10 局监控，以及同次数/同耗时原生 MCTS 对照。

本地 PowerShell 的隐藏后台进程启动方式不包含在上述 Python 命令中；服务器应自行使用持久任务管理工具。

数值修复包括状态有限值验证与限幅、搜索价值限制到 0～2、raw-value Huber loss 与梯度裁剪。fast PUCT 保留这些保护，通过减少重复编码和张量构造加速；固定 16 状态测试中约加速 2.3 倍，根统计与动作一致。不是 GPU 推理版本。

## 来源与许可

- Agent：https://github.com/Jialeiv/sts-rl-agent ，源版本 `039c199933b7d3a2e5d8fde51ae77a9175e1031f`；许可见 `sts-rl-agent/LICENSE`。
- Simulator：https://github.com/gamerpuppy/sts_lightspeed ，基于 `7476a81954020087da31d41d16fddf475746ec2d` 加本地修改；许可见 `simulator/LICENSE.md`。
- JSON 与 pybind11 版本由根目录 `.gitmodules` 和 gitlink 固定，分别遵循上游许可。

历史文档可能包含本机绝对路径和旧实验描述，以当前源码、此 README 和配置为准。
