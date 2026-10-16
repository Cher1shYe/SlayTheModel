"""V7 reward from public facts; no hidden state, future RNG or repeated damage pay."""
import math

VERSION = 'risk-terminal-v7'


def utility(reason, hp, start_hp, max_hp, damage, risk):
    values = (hp, start_hp, max_hp, damage, risk)
    if (any(type(v) not in (float, int) or not math.isfinite(v) for v in values)
            or not 0 <= hp <= max_hp or start_hp <= 0 or max_hp <= 0
            or not 0 <= damage <= 1 or not 0 <= risk <= 1
            or reason not in (None, 'win', 'death', 'time_limit')):
        raise ValueError('Invalid V7 reward facts')
    if reason == 'death':
        if hp != 0: raise ValueError('Death requires zero HP')
        return -1.0
    if hp == 0: raise ValueError('Death takes precedence over cutoff')
    if reason == 'win': return .9 + .1 * hp / max_hp
    if reason is None: return 0.0
    loss = max(-.5, min(1., (start_hp - hp) / max(1., start_hp)))
    return max(-.8, min(.8, -.1 + .9 * damage - .55 * loss - .25 * max(0., loss)**2 - .25 * risk**2))


def incoming_risk(hp, block, vulnerable, attacks):
    """Current visible enemy wave, after Strength, Vulnerable and shared block.

    Each tuple is (base damage, hits, strength). Current G2.3e admits no
    player mitigation other than block and Vulnerable. No future intents are
    predicted. Secondary enemies count for danger, not for damage progress.
    """
    if hp <= 0: return 0.0
    damage = sum(max(0, math.floor((base + strength) * (1.5 if vulnerable else 1))) * hits
                 for base, hits, strength in attacks)
    return min(1., max(0., damage - block) / hp)


def public_risk(info):
    attacks = [(e.intent[1], e.intent[2], e.strength) for e in info.enemies
               if e.hp > 0 and not e.reviving and 'ATTACK' in e.intent[0]]
    return incoming_risk(info.player_hp, info.player_block, info.player_vulnerable, attacks)


def world_risk(world):
    # The same visible intent/base damage used by observe(); no private AI memory.
    from sts2_env.core.enums import PowerId
    def amount(creature, power):
        p = creature.powers.get(power)
        return p.amount if p else 0
    attacks = []
    for enemy in world.enemies:
        if enemy.current_hp <= 0: continue
        for intent in world.enemy_ais[enemy.combat_id].current_move.intents:
            if 'ATTACK' in intent.intent_type.name:
                attacks.append((intent.damage, intent.hits, amount(enemy, PowerId.STRENGTH)))
    return incoming_risk(world.player.current_hp, world.player.block,
                         amount(world.player, PowerId.VULNERABLE), attacks)


def progress(rows):
    if len(rows) == 1 and 'boss_phase' in rows[0]:
        from .boss_phases import BossPhaseState
        return BossPhaseState.from_dict(rows[0]['boss_phase']).damage_progress
    from .summon import ledger_from_rows
    return ledger_from_rows(rows).damage_progress


def search_utility(root, successor):
    """One root-relative truncated simulation; nonterminal leaf is a cutoff.

    d retains the finite enemy obligation denominator (all Boss forms).
    H0 is the search root HP, never the leaf HP or the original battle HP.
    """
    from .boss import phase_rows
    from .summon import ledger_from_slots, ledger_rows
    rows = phase_rows(successor.boss.phase) if successor.boss else ledger_rows(ledger_from_slots(successor.enemies))
    return utility(successor.termination_reason or 'time_limit', successor.player_hp,
                   root.player_hp, successor.player_max_hp, progress(rows), public_risk(successor))
