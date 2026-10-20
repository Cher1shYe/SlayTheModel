# 1024-fight / 3-epoch candidate

`candidate.pt` is the candidate from experiment
`epoch1024_e3_500ms_20261020_005445`, copied byte-for-byte from
`output/epoch1024_e3_500ms_20261020_005445/run/candidate.pt`.
Publishing this artifact does not promote it or replace the champion.

- Size: 12,119,191 bytes.
- SHA256: `9603642088b8a926abc61ab95de1080c69e15cd4194f7fab8866aa1b9ff98b13`.
- Initialization: first-round champion, SHA256
  `b95195162750e188ecfad53d9eadcf730b18c097f60c6bc438ba5331a119d034`.
- Model: XS native generic Transformer, `native-generic-json-v1`, V7 reward.
- Collection: 1,024 fights, 500 ms per search decision, four workers.
- Training: 18,327 decision rows, three complete epochs, batch size 64,
  861 updates, learning rate **0.0003**, `drop_last=false`.

Results on the same 296 frozen recipes:

| Evaluation | Champion wins | Candidate wins |
| --- | ---: | ---: |
| Pure policy (argmax, no MCTS) | 193 (65.20%) | 196 (66.22%) |
| Root policy / mixed value MCTS, 500 ms | 225 (76.01%) | 238 (80.41%) |
| All-node policy / pure model value MCTS, 500 ms | 194 (65.54%) | 236 (79.73%) |

The pure-policy difference is not statistically conclusive. These results
do not isolate the causal contributions of the policy and value heads.
Full results, runtime provenance, and regression evidence:
[experiment artifacts](../../experiments/native_20261020/README.md) and
[training report](../../docs/AZ_EPOCH1024_500MS_RESULTS.md).

Training caches and optimizer checkpoints remain in the local output directory;
they are not included in this model release.
