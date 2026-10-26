import csv
import json
from pathlib import Path
import statistics
import sys
import numpy as np

folder=Path(sys.argv[1])
result=json.loads((folder/'results.json').read_text())
rows=result['runs']; groups={}
for row in rows:
    groups.setdefault(row['label'],{})[row['seed']]=row
variants=((8,4),(16,8),(32,12))
rng=np.random.default_rng(20261026)
pairs={}
def compare(left,right):
    seeds=sorted(set(groups[left]) & set(groups[right]))
    if any(groups[name][s]['status']=='error' for name in (left,right) for s in seeds):
        raise ValueError('Do not summarize errors as outcomes')
    delta=np.array([groups[left][s]['floor']-groups[right][s]['floor'] for s in seeds])
    boot=delta[rng.integers(0,len(delta),(10000,len(delta)))].mean(axis=1)
    return dict(n=len(seeds),mean_delta=float(delta.mean()),better=int((delta>0).sum()),
        same=int((delta==0).sum()),worse=int((delta<0).sum()),
        descriptive_bootstrap_95=np.quantile(boot,[.025,.975]).tolist())
for w,d in variants:
    pairs[f'mcts_minus_beam_w{w}d{d}']=compare(f'mcts-w{w}d{d}',f'beam-w{w}d{d}')
    if w!=8:
        pairs[f'beam_w{w}d{d}_minus_w8d4']=compare(f'beam-w{w}d{d}','beam-w8d4')
(folder/'paired.json').write_text(json.dumps(pairs,indent=2),encoding='utf-8')
with (folder/'per_seed.csv').open('w',newline='',encoding='utf-8') as f:
    writer=csv.writer(f);labels=[f'{kind}-w{w}d{d}' for kind in ('beam','mcts') for w,d in variants]
    writer.writerow(['seed']+[f'{label}_{field}' for label in labels for field in ('floor','status','win')])
    for seed in sorted(groups[labels[0]]):
        writer.writerow([seed]+[groups[label][seed][field] for label in labels for field in ('floor','status','win')])
lines=['# 扩大束搜索与等平均决策耗时 MCTS','',
       '2026-10-26；STS1 战士 A0；同一固定50种子；同一内置非战斗策略；4个worker、每worker Torch单线程。',
       '冻结附带VAL256x256，不重训；沿用Barricade布尔编码修复。每场800动作/整局600外循环护栏。',
       '平均楼层计入所有50局，截断取停止所在层且不算自然死亡/通关。任何非预期异常均单列。','',
       '| 束宽/深度 | 束搜索平均楼层 | MCTS平均楼层 | 束搜索/实测MCTS毫秒 | 束搜索/MCTS通关 | 束搜索/MCTS截断 |',
       '|---|---:|---:|---:|---:|---:|']
for w,d in variants:
    b=result['summary'][f'beam-w{w}d{d}'];m=result['summary'][f'mcts-w{w}d{d}']
    lines.append(f"| {w}/{d} | {b['mean_floor']:.2f} | {m['mean_floor']:.2f} | {b['mean_search_ms']:.2f}/{m['mean_search_ms']:.2f} | {b['wins']}/50；{m['wins']}/50 | {b['cutoffs']}；{m['cutoffs']} |")
lines+=['','## 配对结果','']
for name,v in pairs.items():
    lo,hi=v['descriptive_bootstrap_95']
    lines.append(f"- {name}：平均差{v['mean_delta']:+.2f}层；高/同/低={v['better']}/{v['same']}/{v['worse']}；种子配对bootstrap描述区间[{lo:+.2f},{hi:+.2f}]。")
lines+=['','## 搜索与计时口径','',
    '- 束搜索按动作展开，每层按网络值保留最高W个，深度D包含出牌/结束回合/选择。终局用胜利指示+剩余HP比例；非终局用网络，不裁剪、不另加启发式、不去重。每次只执行首动作再重规划。',
    '- 原生MCTS保持原来的终局奖励、随机rollout和动作提取规则，仅把固定模拟次数改为steady_clock截止时间；每完成一个simulation检查时钟，至少一次。',
    '- 每档MCTS预算由对应束搜索全部50局的总搜索耗时/总搜索次数确定，包含截断局；预算不是根据MCTS成绩挑选。真实调用计时含状态复制、搜索、选动作及树释放。',
    '- 这是平均每次非强制决策的耗时匹配，不是每个局面完全相同耗时，也不是每整局总时间相同；策略不同会访问不同状态，步数不同。4进程调度、CPU频率与树释放造成小幅偏差，以表中实测为准。',
    '- MCTS与束搜索的评价函数不同，本实验比较完整部署方案，不能把差异仅归因于搜索结构。两者使用同一完整原生分支状态，均不是隐藏状态信息集采样方案。',
    '- MCTS的时间停止会造成模拟次数随运行时负载变化，胜率/楼层单次结果不保证逐位复现。正式评价前已通过6项等实际模拟次数动作一致性和根不变检查，见../timed-mcts-equivalence.json。',
    '- 固定50种子已被上游反复用于选择模型，且本次仅一次评估/档；bootstrap区间只是本组种子的描述性不确定性，不替代多训练seed与全新测试集。','',
    '## 工件','',
    '- config.json：种子、配置与脚本/模型/原生模块哈希。budgets.json：按束搜索实测确定的MCTS毫秒预算。',
    '- results.json：全部300局及汇总；per_seed.csv：逐种子六组结果；paired.json：配对比较。',
    '- ../beam_budget_comparison.py：评估入口；../eval_value_beam.py：共用束搜索与游戏循环；../simulator-local.patch：含定时MCTS绑定的模拟器差异。',
    f"- 总墙钟：{result['wall_seconds']:.2f}秒。所有任务已结束；未修改或运行STS2项目。"]
(folder/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('\n'.join(lines[:13]))
print(json.dumps(pairs,indent=2))
