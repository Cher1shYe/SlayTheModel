"""Summarize a completed selfplay_compare experiment with paired seed intervals."""
import csv
import json
from pathlib import Path
import random
import statistics
import sys

out=Path(sys.argv[1]); results=json.loads((out/'results.json').read_text())
names=['before_pure','after_pure','before_puct','after_puct','native_equal_count','native_time_before_puct','native_time_after_puct']
rows={n:json.loads((out/f'{n}.json').read_text())['runs'] for n in names}
seeds={n:{r['seed'] for r in group} for n,group in rows.items()}
assert all(s==seeds[names[0]] for s in seeds.values())
assert all(len(group)==len(seeds[n]) for n,group in rows.items())
assert all(r['status']!='error' for group in rows.values() for r in group)
def paired(a,b):
    left={r['seed']:r['floor'] for r in rows[a]}; right={r['seed']:r['floor'] for r in rows[b]}
    d=[left[s]-right[s] for s in sorted(left)]; rng=random.Random(42)
    bs=sorted(statistics.mean(rng.choices(d,k=len(d))) for _ in range(10000))
    return dict(difference=statistics.mean(d),bootstrap95=[bs[250],bs[9749]],better=sum(x>0 for x in d),equal=sum(x==0 for x in d),worse=sum(x<0 for x in d))
comparisons={a+' minus '+b:paired(a,b) for a,b in [('after_pure','before_pure'),('after_puct','before_puct'),('after_puct','native_equal_count'),('after_puct','native_time_after_puct')]}
(out/'paired.json').write_text(json.dumps(comparisons,indent=2))
with (out/'per_seed.csv').open('w',newline='',encoding='utf-8-sig') as f:
    w=csv.DictWriter(f,fieldnames=['arm',*rows[names[0]][0].keys()]); w.writeheader()
    for n in names:
        for r in rows[n]: w.writerow(dict(arm=n,**r))
lines=['# 多轮自对弈实验','',
       'Ironclad A0；6 轮 × 40 局，每轮 2 epoch，PUCT 每步 64 次模拟。所有组固定同一个发布版 ArmG 非战斗策略。主比较为预先指定的第 6 轮与第 0 轮，未挑选最终测试最优 checkpoint。',
       '', '| 组别 | 平均楼层 | 通关/50 | 截断 | 每决策 ms | 每局秒 |', '|---|---:|---:|---:|---:|---:|']
for n in names:
    r=results['summary'][n]
    lines.append(f"| {n} | {r['mean_floor']:.2f} | {r['wins']} | {r['cutoffs']} | {r['mean_decision_ms']:.3f} | {r['mean_run_seconds']:.3f} |")
lines += ['', '## 每轮独立监控集（10 seeds）','', '| 轮次 | 新样本 | buffer | 平均楼层 | 截断 |', '|---|---:|---:|---:|---:|']
zero=results['summary']['monitor_0']; lines.append(f"| 0 | — | — | {zero['mean_floor']:.2f} | {zero['cutoffs']} |")
for h in results['history']: lines.append(f"| {h['round']} | {h['new_samples']} | {h['buffer']} | {h['mean_floor']:.2f} | {h['cutoffs']} |")
lines += ['', '## 配对比较','']
for name,r in comparisons.items(): lines.append(f"- {name}: Δ={r['difference']:+.2f}，描述性 paired bootstrap 95% 区间 {r['bootstrap95']}；改善/持平/下降={r['better']}/{r['equal']}/{r['worse']}。")
lines += ['', '## 口径与限制','',
 '- 原生 MCTS equal_count 使用每决策 64 次模拟；Python PUCT 的第 1 次为根展开，两者每次模拟的计算内容不同。',
 '- equal-time 原生 MCTS 的每步期限分别取训练前/后 PUCT 全部非强制决策的平均耗时；这是平均决策预算匹配，不是每局总耗时或同一状态配对匹配。实际耗时列包含调用开销。',
 '- 原生 MCTS 使用手写终局评分和随机战斗 rollout；PUCT 使用学习的策略和价值，比较的是完整算法。',
 '- 800 战斗动作或 600 外层步上限触发时记录 cutoff 和停止楼层，不当作自然死亡；训练丢弃整局截断样本。异常直接失败。',
 '- 一个训练随机种子，240 局属于小规模探索；主评测使用历史反复使用的 50 seeds，与本次训练和 10 个监控 seeds 不相交，但不是从未使用过的泛化测试集。bootstrap 只反映这组种子的波动，不能替代重复训练。',
 '- 训练沿用上游结构/奖励/优化方式，无额外根噪声和温度调度；兼容修正包括 BARRICADE flag 和严格异常处理。',
 '- 纯网络指战斗策略直接 argmax、不调用价值或搜索；战斗外仍使用固定 ArmG。',
 f"- 全流程耗时 {results['wall_seconds']/60:.2f} 分钟。配置、源代码、原生模块及初始化权重哈希见 config.json；每轮权重保留，latest_training_state.pt 保存优化器、buffer 和随机状态。"]
(out/'REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(json.dumps(comparisons,indent=2))
