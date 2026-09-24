# Third-party architecture references

SpireFormer v0.1 is a new PyTorch implementation written for SlayTheModel. It does not vendor the upstream repositories, but its architecture and tests were developed after studying these projects and papers:

1. **Set Transformer**
   - Paper: *Set Transformer: A Framework for Attention-based Permutation-Invariant Neural Networks* — https://arxiv.org/abs/1810.00825
   - Reference implementation: https://github.com/juho-lee/set_transformer
   - Inspected revision: `73432c640ac78140496d6738416c54d32c686d65`
   - License: MIT, copyright © 2020 Juho Lee

2. **Decision Transformer**
   - Paper: *Decision Transformer: Reinforcement Learning via Sequence Modeling* — https://arxiv.org/abs/2106.01345
   - Reference implementation: https://github.com/kzl/decision-transformer
   - Inspected revision: `e2d82e68f330c00f763507b3b01d774740bee53f`
   - License: MIT, copyright © 2021 Decision Transformer authors

Both upstream MIT licenses permit use, modification, and redistribution subject to preserving their copyright and permission notices in copies or substantial portions of their software. The repositories above remain the authoritative sources for their full license text.
