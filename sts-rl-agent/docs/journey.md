# From an LLM memory agent to a small policy network

The project began as a tabula-rasa LLM agent: play a run, record the trajectory,
reflect after death, retrieve relevant lessons, and consolidate repeated lessons into
a strategy memory. No internet guide or human gameplay trace was supplied.

That design exposed a credit-assignment problem. Prompting, retrieval, memory,
reflection, search budget, and hidden heuristics were all changing at once. A better
result could not be attributed to a specific mechanism.

The experiment was narrowed in three steps:

1. Fix the simulator, seed protocol, baselines, and evaluation loop.
2. Separate reactive non-combat choices from multi-step combat planning.
3. Train a shared candidate scorer for map, card, shop, rest, and event actions while
   leaving combat to online MCTS planning.

This is not LLM pretraining. It is a small episodic reinforcement-learning system that
reproduces several general ML-engineering problems: data generation, leakage,
held-out evaluation, capacity selection, checkpointing, and deployment calibration.
