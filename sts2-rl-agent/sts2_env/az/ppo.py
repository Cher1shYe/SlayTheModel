"""On-policy PPO for strictly validated, finite-horizon native battles."""
import math
import numpy as np
import torch
from .native_generic import validate_raw, raw_leaf_settings
from .native_transformer import batch_native
from .network import masked_log_probs
from . import cost_reward
from .risk_reward import utility


def potential(facts, initial_hp, terminal, hp):
    """Recompute native V7 potential; missing/corrupt evidence is a hard error."""
    if (facts['version'] != 'v7-potential-v1' or facts['initialHp'] != initial_hp
            or facts['terminal'] is not terminal or facts['hp'] != hp
            or type(facts['pendingChoice']) is not bool
            or facts['pendingChoice'] and facts['risk'] != 1.):
        raise ValueError('Invalid V7 potential evidence')
    # Validate all facts even at an absorbing endpoint.
    score = utility('death' if hp == 0 else 'time_limit', hp, initial_hp,
                    facts['maxHp'], facts['damage'], facts['risk'])
    expected = 0. if terminal else score
    if not math.isfinite(facts['value']) or abs(facts['value'] - expected) > 1e-12:
        raise ValueError('Native/Python V7 potential mismatch')
    return expected


def trajectory_rows(raw, model_sha, shaping_coefficient=0., reward_mode='v7'):
    packed = validate_raw(raw, allow_ppo_training_cutoff=True)
    if (raw['modelSha256'] != model_sha or raw['split'] != 'train'
            or raw['arm'] != 'policy' or raw.get('policySample') is not True
            or raw_leaf_settings(raw) != ('learned', 1.)):
        raise ValueError('PPO requires current-policy sampled native training trajectories')
    if not math.isfinite(shaping_coefficient) or not 0 <= shaping_coefficient <= 1:
        raise ValueError('Invalid shaping coefficient')
    if reward_mode not in ('v7', 'cost'):
        raise ValueError('Unknown PPO reward mode')
    rows, turns = [], 0
    for s, obs in zip(raw['steps'], packed):
        keys = [a['Key'] for a in s['observation']['actions']]
        p = s['behaviorProbabilities']
        u, value, logp = s['policyUniform'], s['behaviorValue'], s['behaviorLogProbability']
        if (s['simulations'] != 0 or len(p) != len(keys)
                or any(not math.isfinite(x) or x < 0 for x in p)
                or abs(sum(p) - 1) > 1e-12
                or not math.isfinite(u) or not 0 <= u < 1
                or not math.isfinite(value) or not -1 <= value <= 1
                or not math.isfinite(logp)):
            raise ValueError('Invalid PPO behavior record')
        chosen = keys.index(s['action'])
        cumulative = np.cumsum(p)
        if (p[chosen] <= 0 or abs(math.log(p[chosen]) - logp) > 1e-12
                or int(np.searchsorted(cumulative, u, side='right')) != chosen):
            raise ValueError('PPO sampling/log probability mismatch')
        mapping = dict(zip(keys, p))
        ordered = [mapping[a['key']] for a in obs['actions']]
        rows.append(dict(observation=obs, action=s['action'], old_logp=logp,
                         old_value=value, old_probabilities=ordered, forced=s['forced'],
                         scenario_id=raw['recipe']['scenario_id'], step=len(rows)))
        if reward_mode == 'cost':
            index = len(rows) - 1
            hp_before = raw['initialHp'] if index == 0 else raw['steps'][index-1]['hpAfter']
            before = cost_reward.cost(hp_before, raw['initialHp'], turns)
            if s['action'].startswith('EndTurn'):
                turns += 1
            after = cost_reward.cost(s['hpAfter'], raw['initialHp'], turns)
            if not math.isfinite(before) or not math.isfinite(after):
                raise ValueError('Nonfinite battle cost')
            rows[-1]['shaping_reward'] = before - after
        elif shaping_coefficient:
            index = len(rows) - 1
            hp_before = raw['initialHp'] if index == 0 else raw['steps'][index-1]['hpAfter']
            before = potential(s['potentialBefore'], raw['initialHp'], False, hp_before)
            after = potential(s['potentialAfter'], raw['initialHp'], s['terminalAfter'], s['hpAfter'])
            frame = s['observation']['observation']
            pid = frame['Players'][0]['PlayerId']
            player = next(c for c in frame['Creatures'] if c['PlayerId'] == pid)
            if s['potentialBefore']['maxHp'] != player['MaxHp']:
                raise ValueError('Potential max HP differs from native observation')
            if index and s['potentialBefore'] != raw['steps'][index-1]['potentialAfter']:
                raise ValueError('Discontinuous potential trajectory')
            # A real time_limit is also an absorbing finite-horizon endpoint.
            final = index == len(raw['steps']) - 1
            if final:
                end = raw['outcome']
                if s['potentialAfter']['maxHp'] != end['maxHp']:
                    raise ValueError('Potential endpoint max HP mismatch')
                if not raw['complete'] and any(s['potentialAfter'][key] != end['cutoff'][key]
                                               for key in ('damage', 'risk', 'pendingChoice')):
                    raise ValueError('Potential cutoff facts mismatch')
            rows[-1]['shaping_reward'] = shaping_coefficient * ((0. if final else after) - before)
            rows[-1]['potential'] = before
    return rows


def terminal_reward(raw, reward_mode='v7'):
    """Episode-end payoff: native V7, or the linear cost objective's R_end."""
    if reward_mode == 'v7':
        return raw['outcome']['reward']
    if reward_mode == 'cost':
        return cost_reward.terminal(raw)
    raise ValueError('Unknown PPO reward mode')


def advantages(rows, terminal_reward, gamma=1., gae_lambda=.95):
    """V7 is the finite-horizon payoff, including time_limit; no double bootstrap."""
    if not rows or not math.isfinite(terminal_reward) or not -1 <= terminal_reward <= 1:
        raise ValueError('Invalid finite episode')
    advantage = 0.
    for i in reversed(range(len(rows))):
        final = i == len(rows) - 1
        next_value = 0. if final else rows[i + 1]['old_value']
        shaping = rows[i].get('shaping_reward', 0.)
        if not math.isfinite(shaping) or shaping and gamma != 1.:
            raise ValueError('V7 difference shaping requires finite rewards and gamma=1')
        delta = (terminal_reward if final else 0.) + shaping + gamma * next_value - rows[i]['old_value']
        advantage = delta + gamma * gae_lambda * advantage
        rows[i]['advantage'] = advantage
        rows[i]['return'] = advantage + rows[i]['old_value']
    return rows


def normalize_advantages(rows):
    values = np.array([r['advantage'] for r in rows if not r['forced']])
    if not len(values):
        raise ValueError('Rollout has no trainable policy choices')
    mean, std = float(values.mean()), float(values.std())
    for r in rows:
        r['normalized_advantage'] = 0. if r['forced'] else (r['advantage'] - mean) / max(std, 1e-8)


def distribution(model, rows):
    batch = batch_native([r['observation'] for r in rows], next(model.parameters()).device)
    logits, values = model(batch)
    logs = masked_log_probs(logits, batch['legal_mask'])
    indices = torch.tensor([keys.index(r['action']) for keys, r in zip(batch['action_keys'], rows)],
                           device=logs.device)
    selected = logs.gather(1, indices[:, None]).squeeze(1)
    safe_logs = logs.masked_fill(~batch['legal_mask'], 0.)
    entropy = -(logs.exp() * safe_logs).sum(-1)
    return selected, values, entropy, logs, batch['legal_mask']


@torch.no_grad()
def verify_behavior(model, rows, microbatch=16):
    """Audit every old probability/value against the frozen collection model."""
    model.eval()
    maximum = 0.
    for start in range(0, len(rows), microbatch):
        block = rows[start:start + microbatch]
        selected, values, _, logs, mask = distribution(model, block)
        for i, r in enumerate(block):
            p = logs[i][mask[i]].exp().cpu()
            old = torch.tensor(r['old_probabilities'])
            error = max(float((p-old).abs().max()),
                        abs(float(selected[i])-r['old_logp']),
                        abs(float(values[i])-r['old_value']))
            maximum = max(maximum, error)
            if error > 2e-5:
                raise ValueError(f'Frozen PPO policy/value differs: {error}, {r["scenario_id"]}/{r["step"]}')
    return maximum


def loss_terms(new_logp, values, entropy, old_logp, targets, advantage, clip=.2):
    ratio = (new_logp - old_logp).exp()
    policy = -torch.minimum(ratio * advantage, ratio.clamp(1-clip, 1+clip) * advantage)
    value = (values - targets).square()
    kl = (ratio - 1) - (new_logp - old_logp)
    clipped = (torch.abs(ratio - 1) > clip).float()
    return policy, value, entropy, kl, clipped


@torch.no_grad()
def rollout_kl(model, rows, microbatch=16):
    """Same sampled-action k3 estimator, averaged over ALL non-forced rollout rows."""
    count = sum(not r['forced'] for r in rows)
    if not count or microbatch < 1:
        raise ValueError('Full-rollout KL requires policy choices and positive microbatch')
    was_training = model.training
    total = 0.
    model.eval()
    try:
        for start in range(0, len(rows), microbatch):
            block = [r for r in rows[start:start + microbatch] if not r['forced']]
            if not block:
                continue
            selected, _, _, _, _ = distribution(model, block)
            delta = selected.double() - selected.new_tensor([r['old_logp'] for r in block]).double()
            estimates = torch.expm1(delta) - delta
            if not torch.isfinite(estimates).all():
                raise ValueError('Nonfinite full-rollout KL')
            total += float(estimates.sum())
    finally:
        model.train(was_training)
    return dict(rollout_kl=total/count, kl_policy_rows=count, kl_total_rows=len(rows))


def update(model, optimizer, rows, config, *, kl_rows=None, check_rollout_kl=True):
    """One minibatch, microbatched with exact sample weighting; no update on high KL."""
    scope = config.get('kl_scope', 'minibatch')
    if scope not in ('minibatch', 'rollout'):
        raise ValueError('Unknown PPO KL scope')
    check = {}
    if scope == 'rollout' and check_rollout_kl:
        if kl_rows is None:
            raise ValueError('Full rollout rows required for KL check')
        check = rollout_kl(model, kl_rows, config['microbatch'])
        if check['rollout_kl'] > config['target_kl']:
            optimizer.zero_grad(set_to_none=True)
            return dict(check, applied=False, reason='target_kl', kl_scope=scope)
    model.train()
    optimizer.zero_grad(set_to_none=True)
    totals = dict(policy_loss=0., value_loss=0., entropy=0., approx_kl=0., clip_fraction=0.)
    policy_count = sum(not r['forced'] for r in rows)
    # Check KL before any optimizer mutation; all selected rows must be processed.
    for start in range(0, len(rows), config['microbatch']):
        block = rows[start:start + config['microbatch']]
        selected, values, entropy, _, _ = distribution(model, block)
        tensor = lambda key: selected.new_tensor([r[key] for r in block])
        terms = loss_terms(selected, values, entropy, tensor('old_logp'), tensor('return'),
                           tensor('normalized_advantage'), config['clip'])
        active = selected.new_tensor([not r['forced'] for r in block])
        policy, value, entropy, kl, clipped = terms
        loss = (policy * active).sum() / max(policy_count, 1)
        loss += config['value_weight'] * value.sum() / len(rows)
        loss -= config['entropy_weight'] * (entropy * active).sum() / max(policy_count, 1)
        if not torch.isfinite(loss):
            raise ValueError('Nonfinite PPO loss')
        loss.backward()
        for key, values_, denom in [('policy_loss',policy*active,max(policy_count,1)),
                                    ('value_loss',value,len(rows)), ('entropy',entropy*active,max(policy_count,1)),
                                    ('approx_kl',kl*active,max(policy_count,1)),
                                    ('clip_fraction',clipped*active,max(policy_count,1))]:
            totals[key] += float(values_.detach().sum()) / denom
    totals.update(check)
    if scope == 'minibatch' and totals['approx_kl'] > config['target_kl']:
        optimizer.zero_grad(set_to_none=True)
        return dict(totals, applied=False, reason='target_kl')
    grad = torch.nn.utils.clip_grad_norm_(model.parameters(), config['max_grad_norm'], error_if_nonfinite=True)
    optimizer.step()
    if any(not torch.isfinite(p).all() for p in model.parameters()):
        raise ValueError('Nonfinite PPO weights')
    return dict(totals, applied=True, gradient_norm=float(grad))


def batch_plan(count, config, cycle):
    rng = np.random.default_rng(config['seed'] + cycle)
    for epoch in range(config['epochs']):
        order = rng.permutation(count).tolist()
        for start in range(0, count, config['batch_size']):
            yield epoch + 1, order[start:start + config['batch_size']]


def scheduled_update(model, optimizer, rows, config, *, kl_rows, rollout_updates, epoch_end):
    """Check post-update rollout KL at persisted update-count boundaries and epoch ends."""
    interval = config.get('kl_check_interval', 1)
    if type(interval) is not int or interval < 1:
        raise ValueError('Invalid KL check interval')
    if config.get('kl_scope') != 'rollout' or interval == 1:
        return update(model, optimizer, rows, config, kl_rows=kl_rows)
    if kl_rows is None:
        raise ValueError('Full rollout rows required for scheduled KL')
    metrics = update(model, optimizer, rows, config, kl_rows=kl_rows, check_rollout_kl=False)
    if (rollout_updates + 1) % interval == 0 or epoch_end:
        metrics.update(rollout_kl(model, kl_rows, config['microbatch']))
        metrics.update(kl_check_position='post_update', kl_epoch_end=epoch_end,
                       kl_interval_boundary=(rollout_updates + 1) % interval == 0)
        metrics['stop_rollout'] = metrics['rollout_kl'] > config['target_kl']
        if metrics['stop_rollout']:
            metrics['reason'] = 'target_kl'
    return metrics
