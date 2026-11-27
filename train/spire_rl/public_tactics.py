"""Checklist A3 / A4 / B: tactical summaries from PublicState facts only.

Shared by the simulator and the native client (no engine state, no trial plays). Built
on the A1 display values (card ``displayDamageVs`` / ``displayBlock``) and on visible
intents (already the game's final per-hit numbers), following v0.111.0 source:

* A3 ``max_damage``: per enemy, the most damage the current hand can deal to it with the
  current energy (each legal attack once; no draws, no order effects such as applying
  Vulnerable first) and whether that kills it (>= HP + block).
* A4 ``end_turn``: HP the player loses if the turn ends now, resolving in native order
  (CombatManager.EndPlayerTurnPhaseOne/Two, then the enemy turn):
    BeforeSideTurnEndVeryEarly  Orichalcum / Fake Orichalcum check Block == 0
    BeforeSideTurnEnd(Early)    Plating, Orichalcum 6, Fake Orichalcum 3, Cloak Clasp
                                1 per hand card, Ripple Basin 4 (no Attack this turn);
                                Regret counts the hand here
    DoTurnEnd                   Ethereal cards exhaust (Feel No Pain block), then the
                                turn-end cards in hand order: Burn/Decay/Infection/
                                Toxic/Wither (Damage, blockable), Bad Luck 13, Beckon 6,
                                Regret = hand size (unblockable)
    AfterSideTurnEnd(Late)      Constrict, Demise (unblockable), Disintegration
    enemy turn                  each visible Attack / DeathBlow intent, hit by hit
  Effects at the start of the next player turn (Inferno self-damage, Poison) are not
  part of this value.
  Player damage: Intangible caps each hit at 1; block absorbs blockable damage; HP loss
  then Tungsten Rod -1 / Beating Remnant (20 per player turn incl. this one, relic order)
  and Buffer (one stack prevents one HP loss).
* B ``action_preview``: see the B section below (player side exact or unknown; enemy-specific
  defenses excluded). Fields: HP + block removed from each enemy, kills, block gained, energy
  left, HP lost (or healed) during the play, and the A4 value after that play (its damage,
  block, HP loss and hand applied, killed enemies' intents removed). End turn gets the current A4.

Anything not modelled sets an explicit ``unknown`` flag instead of a guessed number:
hidden intents, cards whose hit count is decided during play, other characters' unported
calculated variables.
"""
from __future__ import annotations

import json
from pathlib import Path

_CATALOG = json.loads(Path(__file__).with_name("public_catalog.json").read_text())
HITS = _CATALOG["cardHits"]

TURN_END_DAMAGE = {"CARD.BURN", "CARD.DECAY", "CARD.INFECTION", "CARD.TOXIC", "CARD.WITHER"}  # DamageVar, blockable
TURN_END_HP_LOSS = {"CARD.BAD_LUCK": 13, "CARD.BECKON": 6}                                    # unblockable
ATTACK_INTENTS = {"Attack", "DeathBlow"}
# Enemy powers known not to react when an ally dies. A kill next to any other power
# (Ravenous, Queen's Enrage switch, ...) can change the survivors' turn: B marks unknown.
DEATH_QUIET_POWERS = {"POWER.VULNERABLE_POWER", "POWER.WEAK_POWER", "POWER.STRENGTH_POWER", "POWER.THORNS_POWER",
                      "POWER.ARTIFACT_POWER", "POWER.RITUAL_POWER", "POWER.PLATING_POWER"}
HIDDEN_INTENTS = {"Hidden", "Unknown"}
# Enemy powers whose reaction to being damaged changes the player's HP or that enemy's turn
# (AfterDamageReceived / BeforeDamageReceived in v0.111.0): wake / stun (Asleep, Slumber, Shriek,
# Flutter, Plow), retaliation (Thorns, Reflect, Flame Barrier, Inferno), Strength on hit (Rupture),
# cards into the player's piles (Personal Hive), The Gambit. Defense-only reactions (Curl Up,
# Hardened Shell, Slippery, Skittish, Hard to Kill, Intangible) are outside the damage values by
# definition and do not appear here.
ENEMY_ON_HIT = frozenset("POWER." + n for n in
    "ASLEEP_POWER SLUMBER_POWER SHRIEK_POWER FLUTTER_POWER PLOW_POWER THORNS_POWER REFLECT_POWER "
    "FLAME_BARRIER_POWER INFERNO_POWER RUPTURE_POWER PERSONAL_HIVE_POWER THE_GAMBIT_POWER".split())


def _reacts_on_hit(enemy):
    return any(pw[0] in ENEMY_ON_HIT for pw in enemy["powers"])


def _power(powers, ident):
    return sum(row[1] for row in powers if row[0] == ident)


def _relics(facts):
    return [r["modelId"] for r in sorted(facts["relics"], key=lambda r: r["position"]) if r["status"] != "Disabled"]


def _var(card, name):
    for n, v in card["dynamicVars"]:
        if n == name:
            return v
    return None


def card_hits(card, facts, target=None):
    """Hits per play, or None when decided during play. ``target``: enemy fact dict."""
    kind = HITS.get(card["modelId"], 1)
    if isinstance(kind, int):
        return kind
    if kind == "repeat":
        return int(_var(card, "Repeat") or 1)
    if kind == "x":   # ResolveEnergyXValue: captured energy + Chemical X Increase 2
        return facts["player"]["energy"] + (2 if "RELIC.CHEMICAL_X" in _relics(facts) else 0)
    if card["modelId"] == "CARD.SPITE":       # Repeat if the owner lost HP this turn, else 1
        return int(_var(card, "Repeat") or 1) if facts["combat"]["hpLostTurn"] > 0 else 1
    if card["modelId"] == "CARD.DISMANTLE":   # 2 if the target has Vulnerable, else 1
        if target is None:
            return None
        return 2 if any(p[0] == "POWER.VULNERABLE_POWER" and p[1] > 0 for p in target["powers"]) else 1
    return None


def _hittable(facts):
    return [e for e in facts["enemies"] if e["hittable"]]


def _hits_total(per_hit, hits, enemy, facts):
    """Damage of ``hits`` hits. The Boot turns a hit costing the enemy 1..4 HP into 5, after its block."""
    if not any(r["modelId"] == "RELIC.THE_BOOT" and r["status"] != "Disabled" for r in facts["relics"]):
        return per_hit * hits
    block, total = enemy["block"], 0
    for _ in range(int(hits)):
        absorbed = min(block, per_hit)
        block -= absorbed
        left = per_hit - absorbed
        total += absorbed + (5 if 0 < left < 5 else left)
    return total


def play_damage(card, facts, target_order):
    """{enemy order: expected damage before block} of one play, or None if unknown."""
    vs = card["displayDamageVs"]
    if card["modelId"] == "CARD.PACTS_END":   # PactsEnd.CanDealDamage: >= Cards exhausted cards
        if sum(c["pile"] == "exhaust" for c in facts["cards"]) < int(_var(card, "Cards") or 3):
            return {}
    if vs is None:
        return {} if card["displayDamage"] is None and not card["previewUnsupported"] else None
    enemies = {e["order"]: e for e in _hittable(facts)}
    if card["target"] == "AllEnemies":
        out = {}
        for order, e in enemies.items():
            hits = card_hits(card, facts, e)
            if hits is None:
                return None
            out[order] = _hits_total(vs[order], hits, e, facts)
        return out
    if card["target"] == "RandomEnemy":   # expected value: each hit picks a hittable enemy uniformly
        hits = card_hits(card, facts)
        if hits is None or not enemies:
            return None if hits is None else {}
        return {order: _hits_total(vs[order], hits, e, facts) / len(enemies) for order, e in enemies.items()}
    if target_order is None or target_order not in enemies:
        return {}
    hits = card_hits(card, facts, enemies[target_order])
    return None if hits is None else {target_order: _hits_total(vs[target_order], hits, enemies[target_order], facts)}


def _energy_cost(card, facts):
    return facts["player"]["energy"] if card["costX"] else max(0, card["cost"])


def _energy_after(card, facts):
    """Energy after paying for the card; Sown (Status Normal) refunds Amount on play."""
    energy = facts["player"]["energy"] - _energy_cost(card, facts)
    enchantment = card["enchantment"]
    if enchantment is not None and enchantment[0] == "ENCHANTMENT.SOWN" and not enchantment[2]:
        energy += enchantment[1]
    return energy


def _plays(state):
    """(action index, hand card, target order or None) for every legal play."""
    hand = {c["position"]: c for c in state.facts["cards"] if c["pile"] == "hand"}
    out = []
    for index, action in enumerate(state.actions):
        if action.key.kind != "play":
            continue
        args = action.key.args
        card = hand.get(args[0][0])
        if card is None:
            continue
        target = args[1][0] if len(args) > 1 and args[1] is not None else None
        out.append((index, card, target))
    return out


# ------------------------------------------------------------------------------- A3

def max_damage(state):
    """{enemy order: (max damage, can kill, unknown)} with current hand and energy."""
    facts = state.facts
    energy = facts["player"]["energy"]
    result = {}
    plays = _plays(state)
    for enemy in _hittable(facts):
        options, unknown = {}, False
        for _, card, target in plays:
            dmg = play_damage(card, facts, target)
            if dmg is None:
                unknown = True
                continue
            value = dmg.get(enemy["order"], 0)
            if value <= 0:
                continue
            key = id(card)
            if value > options.get(key, (0, 0))[0]:
                options[key] = (value, _energy_cost(card, facts))
        best = [0.0] * (energy + 1)   # 0/1 knapsack on energy
        for value, cost in options.values():
            for e in range(energy, cost - 1, -1):
                best[e] = max(best[e], best[e - cost] + value)
        total = best[energy]
        result[enemy["order"]] = (total, total >= enemy["hp"] + enemy["block"], unknown)
    return result


# ------------------------------------------------------------------------------- A4

class _Player:
    def __init__(self, facts, extra_block):
        powers = facts["powers"]
        self.block = facts["player"]["block"] + extra_block
        self.intangible = _power(powers, "POWER.INTANGIBLE_POWER") > 0
        self.buffer = _power(powers, "POWER.BUFFER_POWER")
        self.relics = _relics(facts)
        self.lost_this_turn = facts["combat"]["hpLostTurn"]  # Beating Remnant DamageReceivedThisTurn
        self.osty = facts["player"].get("ostyHp")
        self.unknown = self.osty is None                     # legacy capture without Osty export
        self.osty = self.osty or 0
        self.lost = 0

    def copy(self):
        other = _Player.__new__(_Player)
        other.__dict__.update(self.__dict__)
        return other

    def damage(self, amount, blockable=True, powered=False):
        """Applies one hit; returns the HP actually lost (unblocked damage after caps)."""
        before = self.lost
        self._damage(amount, blockable, powered)
        return self.lost - before

    def _damage(self, amount, blockable, powered):
        if amount <= 0:
            return
        if self.intangible:
            amount = min(amount, 1)                          # IntangiblePower.ModifyDamageCap
        if blockable:
            absorbed = min(self.block, amount)
            self.block -= absorbed
            amount -= absorbed
        if amount <= 0:
            return
        if powered and self.osty > 0:                        # Osty takes unblocked powered attack damage first
            absorbed = min(self.osty, amount)
            self.osty -= absorbed
            amount -= absorbed
            if amount <= 0:
                return
        for relic in self.relics:                            # ModifyHpLostAfterOsty, relic order
            if relic == "RELIC.TUNGSTEN_ROD":
                amount = max(0, amount - 1)
            elif relic == "RELIC.BEATING_REMNANT":
                amount = max(0, min(amount, 20 - self.lost_this_turn))
        if amount > 0 and self.buffer > 0:                   # BufferPower (AfterOstyLate) + decrement
            self.buffer -= 1
            amount = 0
        self.lost += amount
        self.lost_this_turn += amount


# Player powers whose end-of-turn / enemy-turn effect is not modelled: The Gambit (dies on an
# unblocked powered hit), Stampede (auto-plays Attacks at turn end), The Bomb on its last turn.
END_TURN_OPAQUE = ("POWER.THE_GAMBIT_POWER", "POWER.STAMPEDE_POWER")


def end_turn(facts, extra_block=0, enemy_damage=None, played=None, attack_played=False,
             player=None, hand=None, silenced=(), gained=None):
    """(hp lost, unknown, self damage, incoming before block). ``enemy_damage``: damage
    already dealt to each enemy order this decision (B); ``played``: hand card removed.
    B passes ``player`` (state after the play, losses so far not counted again), ``hand``
    (hand after the play), ``silenced`` (enemy orders that will not act: stunned) and
    ``gained`` ({power id: amount} the play applied to the player)."""
    enemy_damage = enemy_damage or {}
    gained = gained or {}
    powers = list(facts["powers"]) + [(k, v, v, ()) for k, v in gained.items()]
    relics = _relics(facts)
    if hand is None:
        hand = [c for c in facts["cards"] if c["pile"] == "hand" and c is not played]
    hand = sorted(hand, key=lambda c: c["position"])
    p = _Player(facts, extra_block) if player is None else player.copy()
    p.intangible = p.intangible or _power(powers, "POWER.INTANGIBLE_POWER") > 0
    base_lost = p.lost
    unknown = any(_power(powers, k) for k in END_TURN_OPAQUE) or _power(powers, "POWER.THE_BOMB_POWER") == 1
    retaliation = _power(powers, "POWER.FLAME_BARRIER_POWER") + _power(powers, "POWER.THORNS_POWER")
    if any(c["modelId"] == "CARD.HOWL_FROM_BEYOND" for c in facts["cards"] if c["pile"] == "exhaust") \
            or played is not None and played["modelId"] == "CARD.HOWL_FROM_BEYOND":
        unknown = True                                       # auto-plays from the exhaust pile at turn end
    block_before = p.block
    # BeforeSideTurnEndVeryEarly / Early / BeforeSideTurnEnd (all Unpowered block).
    zero_block = p.block == 0
    p.block += _power(powers, "POWER.PLATING_POWER")
    if zero_block and "RELIC.ORICHALCUM" in relics: p.block += 6
    if zero_block and "RELIC.FAKE_ORICHALCUM" in relics: p.block += 3
    if "RELIC.CLOAK_CLASP" in relics: p.block += len(hand)
    if "RELIC.RIPPLE_BASIN" in relics and facts["combat"]["attacksPlayedTurn"] == 0 and not attack_played:
        p.block += 4
    # DoTurnEnd: OrbQueue.BeforeTurnEnd, in queue order, before the hand's end-of-turn effects.
    dealt = dict(enemy_damage)
    orbs = facts["player"].get("orbs", ())
    if orbs is None:                                     # legacy capture without the orb export
        unknown = True
    else:
        cables = "RELIC.GOLD_PLATED_CABLES" in relics    # the first orb triggers twice
        hittable = [e for e in facts["enemies"] if e["alive"] and e["hittable"]]
        random_hits = 0
        unknown |= bool(orbs) and _power(powers, "POWER.CONSUMING_SHADOW_POWER") > 0  # evokes after the hand
        for index, orb in enumerate(orbs):
            triggers = 1 + (cables and index == 0)
            if orb["modelId"] == "ORB.FROST_ORB":
                p.block += orb["passive"] * triggers
                unknown |= _power(powers, "POWER.HAILSTORM_POWER") > 0
            elif orb["modelId"] == "ORB.LIGHTNING_ORB":
                random_hits += orb["passive"] * triggers
            elif orb["modelId"] == "ORB.GLASS_ORB" and orb["passive"] > 0:
                unknown |= triggers > 1                  # its value falls between the two triggers
                for e in hittable:
                    dealt[e["order"]] = dealt.get(e["order"], 0) + orb["passive"]
                    unknown |= _reacts_on_hit(e)
        if random_hits and len(hittable) == 1:
            dealt[hittable[0]["order"]] = dealt.get(hittable[0]["order"], 0) + random_hits
            unknown |= _reacts_on_hit(hittable[0])
        elif random_hits:                                # random target: only matters if one can die or react
            unknown |= any(_reacts_on_hit(e) or e["hp"] + e["block"] - dealt.get(e["order"], 0) <= random_hits
                           for e in hittable)
    regret_count = len(hand)
    # DoTurnEnd: Ethereal (non turn-end) cards exhaust first -> Feel No Pain.
    fnp = _power(powers, "POWER.FEEL_NO_PAIN_POWER")
    turn_end = [c for c in hand if c["modelId"] in TURN_END_DAMAGE or c["modelId"] in TURN_END_HP_LOSS
                or c["modelId"] in ("CARD.REGRET", "CARD.DEBT", "CARD.DOUBT", "CARD.SHAME")]
    ethereal = [c for c in hand if c not in turn_end and "Ethereal" in c["keywords"]]
    p.block += fnp * len(ethereal)
    before = p.lost
    for card in turn_end:
        if card["modelId"] in TURN_END_DAMAGE:
            p.damage(int(_var(card, "Damage") or 0))
        elif card["modelId"] in TURN_END_HP_LOSS:
            p.damage(TURN_END_HP_LOSS[card["modelId"]], blockable=False)
        elif card["modelId"] == "CARD.REGRET":
            p.damage(regret_count, blockable=False)
        if "Ethereal" in card["keywords"]:
            p.block += fnp                                   # exhausted after its effect
    # Exhausted at turn end (Ethereal): Charon's Ashes 3 to every enemy, Forgotten Soul 1 to a random one.
    exhausted = len(ethereal) + sum("Ethereal" in c["keywords"] for c in turn_end)
    if exhausted and "RELIC.CHARONS_ASHES" in relics:
        for e in facts["enemies"]:
            if e["alive"] and e["hittable"]:
                dealt[e["order"]] = dealt.get(e["order"], 0) + 3 * exhausted
                unknown |= _reacts_on_hit(e)
    if exhausted and "RELIC.FORGOTTEN_SOUL" in relics:
        unknown |= any(e["alive"] and (_reacts_on_hit(e) or e["hp"] + e["block"] - dealt.get(e["order"], 0) <= exhausted)
                       for e in facts["enemies"])
    # AfterSideTurnEnd / Late.
    p.damage(_power(powers, "POWER.CONSTRICT_POWER"))
    p.damage(_power(powers, "POWER.DEMISE_POWER"), blockable=False)
    p.damage(_power(powers, "POWER.DISINTEGRATION_POWER"))
    self_damage = p.lost - before
    # Juggernaut: each end-of-turn block gain hits a random enemy (may kill an attacker).
    juggernaut = _power(powers, "POWER.JUGGERNAUT_POWER")
    if juggernaut and p.block > block_before and any(e["alive"] and _reacts_on_hit(e) for e in facts["enemies"]):
        unknown = True
    if juggernaut and p.block > block_before:
        reach = juggernaut * (len(hand) + 4 + 2 * len(orbs or ()))  # bound on the number of block gains
        if any(e["alive"] and e["hp"] + e["block"] - dealt.get(e["order"], 0) <= reach
               for e in facts["enemies"]):
            unknown = True
    # Enemy turn.
    incoming = 0
    for enemy in facts["enemies"]:
        if not enemy["alive"] or enemy["order"] in silenced:
            continue
        if dealt.get(enemy["order"], 0) >= enemy["hp"] + enemy["block"]:
            if dealt.get(enemy["order"], 0) > enemy_damage.get(enemy["order"], 0) and \
                    not {pw[0] for pw in enemy["powers"]} <= DEATH_QUIET_POWERS:
                unknown = True                               # its own defenses may keep it alive
            continue                                         # killed by this play / at turn end
        # PoisonPower.AfterSideTurnStart ticks before any enemy acts and ignores block.
        poison = _power(enemy["powers"], "POWER.POISON_POWER")
        if poison > 0:
            ticks = min(poison, 1 + _power(powers, "POWER.ACCELERANT_POWER"))
            hp_left = enemy["hp"] - max(0, dealt.get(enemy["order"], 0) - enemy["block"])
            if ticks * poison - ticks * (ticks - 1) // 2 >= hp_left:
                if not {pw[0] for pw in enemy["powers"]} <= DEATH_QUIET_POWERS | {"POWER.POISON_POWER"}:
                    unknown = True                           # its death may trigger something
                continue
        if not enemy["intentsVisible"]:
            unknown = True
            continue
        for kind, damage, hits in enemy["intents"]:
            if kind in HIDDEN_INTENTS:
                unknown = True
            if kind in ATTACK_INTENTS:
                left = enemy["hp"] + enemy["block"] - dealt.get(enemy["order"], 0)
                if retaliation and (left <= retaliation * max(1, hits) or _reacts_on_hit(enemy)):
                    unknown = True                           # Flame Barrier / Thorns may kill / provoke it
                for _ in range(max(1, hits)):
                    incoming += damage
                    p.damage(damage, powered=True)
    return p.lost - base_lost, unknown or p.unknown, self_damage, incoming

# ------------------------------------------------------------------------------- B
#
# One manual play resolved on the player's side, following CardModel.OnPlayWrapper:
# play count = enchanted replay count + 1, + One-Two Punch (Attack) / Duplication / Burst (Skill) /
# Throwing Axe (first card of the combat); every play runs BeforeCardPlayed, OnPlay and
# AfterCardPlayed; then the card goes to its result pile (Exhaust keyword, Corruption on a
# Skill -> AfterCardExhausted). The preview stops at the next decision (a selection screen the
# card opens ends it).
#
# Damage to enemies = the card's A1 value x hits plus the player's own relic / power damage,
# *before* enemy-specific defenses and reactions (Slippery, Skittish, Hardened Shell, Thorns,
# Curl Up, ...): those enemies' powers are encoded and left to the network. Everything on the
# player's side (energy, block, HP lost or healed, hand at turn end) is exact or unknown.

# Every card whose OnPlay (and turn-end / on-draw effect) was read against v0.111.0 for B:
# the Ironclad, colorless, event, curse, status and token pools. Any other card -> unknown.
REVIEWED = frozenset({
    "CARD.ABUNDANCE", "CARD.AGGRESSION", "CARD.ALCHEMIZE", "CARD.ANGER",
    "CARD.ANOINTED", "CARD.APOTHEOSIS", "CARD.APPARITION", "CARD.ARMAMENTS",
    "CARD.ASCENDERS_BANE", "CARD.ASHEN_STRIKE", "CARD.AUTOMATION", "CARD.BAD_LUCK",
    "CARD.BARRICADE", "CARD.BASH", "CARD.BATTLE_TRANCE", "CARD.BEACON_OF_HOPE",
    "CARD.BEAT_DOWN", "CARD.BECKON", "CARD.BELIEVE_IN_YOU", "CARD.BLAZE",
    "CARD.BLOODLETTING", "CARD.BLOOD_WALL", "CARD.BLUDGEON", "CARD.BODY_SLAM",
    "CARD.BOLAS", "CARD.BRAND", "CARD.BREAK", "CARD.BREAKTHROUGH",
    "CARD.BRIGHTEST_FLAME", "CARD.BULLY", "CARD.BURN", "CARD.BURNING_PACT",
    "CARD.BYRD_SWOOP", "CARD.CALAMITY", "CARD.CALTROPS", "CARD.CASCADE",
    "CARD.CATASTROPHE", "CARD.CINDER", "CARD.CLASH", "CARD.CLUMSY",
    "CARD.COLOSSUS", "CARD.CONFLAGRATION", "CARD.COORDINATE", "CARD.CORRUPTION",
    "CARD.CRIMSON_MANTLE", "CARD.CRUELTY", "CARD.CURSE_OF_THE_BELL", "CARD.DARK_EMBRACE",
    "CARD.DARK_SHACKLES", "CARD.DAZED", "CARD.DEBRIS", "CARD.DEBT",
    "CARD.DECAY", "CARD.DEFEND_IRONCLAD", "CARD.DEMONIC_SHIELD", "CARD.DEMON_FORM",
    "CARD.DISCOVERY", "CARD.DISINTEGRATION", "CARD.DISMANTLE", "CARD.DISTRACTION",
    "CARD.DOMINATE", "CARD.DOUBT", "CARD.DRAMATIC_ENTRANCE", "CARD.DRUM_OF_BATTLE",
    "CARD.DUAL_WIELD", "CARD.ENLIGHTENMENT", "CARD.ENTHRALLED", "CARD.ENTRENCH",
    "CARD.ENTROPY", "CARD.EQUILIBRIUM", "CARD.ETERNAL_ARMOR", "CARD.EVIL_EYE",
    "CARD.EXPECT_A_FIGHT", "CARD.EXTERMINATE", "CARD.FASTEN", "CARD.FEED",
    "CARD.FEEDING_FRENZY", "CARD.FEEL_NO_PAIN", "CARD.FIEND_FIRE", "CARD.FIGHT_ME",
    "CARD.FINESSE", "CARD.FISTICUFFS", "CARD.FLAME_BARRIER", "CARD.FLASH_OF_STEEL",
    "CARD.FOLLY", "CARD.FORGOTTEN_RITUAL", "CARD.FRANTIC_ESCAPE", "CARD.FUEL",
    "CARD.GANG_UP", "CARD.GIANT_ROCK", "CARD.GOLD_AXE", "CARD.GREED",
    "CARD.GUILTY", "CARD.HAND_OF_GREED", "CARD.HAVOC", "CARD.HEADBUTT",
    "CARD.HELLO_WORLD", "CARD.HELLRAISER", "CARD.HEMOKINESIS", "CARD.HIDDEN_GEM",
    "CARD.HOWL_FROM_BEYOND", "CARD.HUDDLE_UP", "CARD.IMPATIENCE", "CARD.IMPERVIOUS",
    "CARD.INFECTION", "CARD.INFERNAL_BLADE", "CARD.INFERNO", "CARD.INFLAME",
    "CARD.INJURY", "CARD.INTERCEPT", "CARD.IRON_WAVE", "CARD.JACKPOT",
    "CARD.JACK_OF_ALL_TRADES", "CARD.JUGGERNAUT", "CARD.JUGGLING", "CARD.KNOCKDOWN",
    "CARD.LIFT", "CARD.LUMINESCE", "CARD.MAD_SCIENCE", "CARD.MANGLE",
    "CARD.MASTER_OF_STRATEGY", "CARD.MAUL", "CARD.MAYHEM", "CARD.METAMORPHOSIS",
    "CARD.MIDNIGHT", "CARD.MIMIC", "CARD.MIND_BLAST", "CARD.MIND_ROT",
    "CARD.MINION_DIVE_BOMB", "CARD.MINION_SACRIFICE", "CARD.MINION_STRIKE", "CARD.MOLTEN_FIST",
    "CARD.NEOWS_FURY", "CARD.NORMALITY", "CARD.NOSTALGIA", "CARD.NOT_YET",
    "CARD.OFFERING", "CARD.OMNISLICE", "CARD.ONE_TWO_PUNCH", "CARD.OUTMANEUVER",
    "CARD.OUTRAGE", "CARD.PACTS_END", "CARD.PANACHE", "CARD.PANIC_BUTTON",
    "CARD.PECK", "CARD.PERFECTED_STRIKE", "CARD.PILLAGE", "CARD.POMMEL_STRIKE",
    "CARD.POOR_SLEEP", "CARD.PREP_TIME", "CARD.PRIMAL_FORCE", "CARD.PRODUCTION",
    "CARD.PROLONG", "CARD.PROWESS", "CARD.PURITY", "CARD.PYRE",
    "CARD.RAGE", "CARD.RALLY", "CARD.RAMPAGE", "CARD.REBOUND",
    "CARD.REGRET", "CARD.RELAX", "CARD.REND", "CARD.RESTLESSNESS",
    "CARD.RIP_AND_TEAR", "CARD.ROLLING_BOULDER", "CARD.RUPTURE", "CARD.SALVO",
    "CARD.SCRAWL", "CARD.SECOND_WIND", "CARD.SECRET_TECHNIQUE", "CARD.SECRET_WEAPON",
    "CARD.SEEKER_STRIKE", "CARD.SETUP_STRIKE", "CARD.SHAME", "CARD.SHIV",
    "CARD.SHOCKWAVE", "CARD.SHRUG_IT_OFF", "CARD.SLIMED", "CARD.SLOTH",
    "CARD.SOOT", "CARD.SOUL", "CARD.SOVEREIGN_BLADE", "CARD.SPITE",
    "CARD.SPLASH", "CARD.SPORE_MIND", "CARD.SQUASH", "CARD.STACK",
    "CARD.STAMPEDE", "CARD.STOKE", "CARD.STOMP", "CARD.STONE_ARMOR",
    "CARD.STRATAGEM", "CARD.STRIKE_IRONCLAD", "CARD.SWEEPING_GAZE", "CARD.SWORD_BOOMERANG",
    "CARD.TAG_TEAM", "CARD.TANK", "CARD.TAUNT", "CARD.TEAR_ASUNDER",
    "CARD.THE_BALL", "CARD.THE_BOMB", "CARD.THE_GAMBIT", "CARD.THINKING_AHEAD",
    "CARD.THRASH", "CARD.THRUMMING_HATCHET", "CARD.THUNDERCLAP", "CARD.TORIC_TOUGHNESS",
    "CARD.TOXIC", "CARD.TREMBLE", "CARD.TRUE_GRIT", "CARD.TWIN_STRIKE",
    "CARD.ULTIMATE_DEFEND", "CARD.ULTIMATE_STRIKE", "CARD.UNMOVABLE", "CARD.UNRELENTING",
    "CARD.UPPERCUT", "CARD.VICIOUS", "CARD.VOID", "CARD.VOLLEY",
    "CARD.WASTE_AWAY", "CARD.WHIRLWIND", "CARD.WHISTLE", "CARD.WISH",
    "CARD.WITHER", "CARD.WOUND", "CARD.WRITHE",
})
# CreatureCmd.Damage(owner, HpLoss, Unblockable | Unpowered | Move), first effect of OnPlay.
SELF_HP_LOSS = frozenset({
    "CARD.BLOODLETTING", "CARD.BLOOD_WALL", "CARD.BRAND", "CARD.BREAKTHROUGH",
    "CARD.HEMOKINESIS", "CARD.OFFERING",
})
# PlayerCmd.GainEnergy(Energy) unconditionally (Restlessness: only card in hand).
ENERGY_GAIN = frozenset({
    "CARD.BLOODLETTING", "CARD.BRIGHTEST_FLAME", "CARD.FORGOTTEN_RITUAL", "CARD.FUEL",
    "CARD.LUMINESCE", "CARD.OFFERING", "CARD.PRODUCTION",
})
# Effects not modelled: plays hidden draw-pile cards (Havoc, Cascade, Catastrophe, Beat Down,
# Uproar's extra attack); block equal to damage dealt (Fisticuffs); splash of dealt damage
# (Omnislice); random hand attack (Thrash); ally targets (Demonic Shield, Lift, Mimic, Believe in
# You, Rally); Mad Science (effects come from its Tinker Time riders); Feed's max HP (only on a
# kill, handled below).
OPAQUE = frozenset({
    "CARD.BEAT_DOWN", "CARD.BELIEVE_IN_YOU", "CARD.CASCADE", "CARD.CATASTROPHE",
    "CARD.DEMONIC_SHIELD", "CARD.FISTICUFFS", "CARD.HAVOC", "CARD.LIFT",
    "CARD.MAD_SCIENCE", "CARD.MIMIC", "CARD.OMNISLICE", "CARD.RALLY", "CARD.THRASH",
    "CARD.UPROAR",
})
# Draws, generates, retrieves, transforms or randomly / selectively exhausts hand cards: the hand at
# turn end is not known (Second Wind is exact and modelled).
HAND_CHANGE = frozenset({
    "CARD.ABUNDANCE", "CARD.ANOINTED", "CARD.ARMAMENTS", "CARD.BATTLE_TRANCE",
    "CARD.BRAND", "CARD.BRIGHTEST_FLAME", "CARD.BURNING_PACT", "CARD.CINDER",
    "CARD.DISCOVERY", "CARD.DISTRACTION", "CARD.DRUM_OF_BATTLE", "CARD.DUAL_WIELD",
    "CARD.FIEND_FIRE", "CARD.FINESSE", "CARD.FLASH_OF_STEEL", "CARD.HUDDLE_UP",
    "CARD.IMPATIENCE", "CARD.INFERNAL_BLADE", "CARD.JACKPOT", "CARD.JACK_OF_ALL_TRADES",
    "CARD.MASTER_OF_STRATEGY", "CARD.METAMORPHOSIS", "CARD.MINION_STRIKE", "CARD.NEOWS_FURY",
    "CARD.OFFERING", "CARD.OUTRAGE", "CARD.PILLAGE", "CARD.POMMEL_STRIKE",
    "CARD.PRIMAL_FORCE", "CARD.PURITY", "CARD.RESTLESSNESS", "CARD.SCRAWL",
    "CARD.SECRET_TECHNIQUE", "CARD.SECRET_WEAPON", "CARD.SEEKER_STRIKE", "CARD.SHRUG_IT_OFF",
    "CARD.SLIMED", "CARD.SOUL", "CARD.SPLASH", "CARD.STOKE",
    "CARD.THINKING_AHEAD", "CARD.TRUE_GRIT", "CARD.WISH",
})
# Changes what an enemy does this enemy turn (Weak / Strength / temporary Strength loss /
# Knockdown / Covered / Coordinate / Tag Team): the end-turn value after it is unknown.
ENEMY_TURN_CHANGE = frozenset({
    "CARD.BLAZE", "CARD.COORDINATE", "CARD.DARK_SHACKLES", "CARD.FIGHT_ME",
    "CARD.INTERCEPT", "CARD.KNOCKDOWN", "CARD.MANGLE", "CARD.SHOCKWAVE",
    "CARD.TAG_TEAM", "CARD.UPPERCUT",
})
# Apply a power to the player or change their own numbers on play: a replayed copy differs.
REPLAY_VARIES = frozenset({
    "CARD.AGGRESSION", "CARD.APPARITION", "CARD.ASHEN_STRIKE", "CARD.AUTOMATION",
    "CARD.BARRICADE", "CARD.BATTLE_TRANCE", "CARD.BEACON_OF_HOPE", "CARD.BODY_SLAM",
    "CARD.BRAND", "CARD.BULLY", "CARD.CALAMITY", "CARD.CALTROPS",
    "CARD.CASCADE", "CARD.COLOSSUS", "CARD.CORRUPTION", "CARD.CRIMSON_MANTLE",
    "CARD.CRUELTY", "CARD.DARK_EMBRACE", "CARD.DEMONIC_SHIELD", "CARD.DEMON_FORM",
    "CARD.DOMINATE", "CARD.ENTROPY", "CARD.EQUILIBRIUM", "CARD.ETERNAL_ARMOR",
    "CARD.EXPECT_A_FIGHT", "CARD.FASTEN", "CARD.FEEDING_FRENZY", "CARD.FEEL_NO_PAIN",
    "CARD.FIEND_FIRE", "CARD.FIGHT_ME", "CARD.FLAME_BARRIER", "CARD.FLASH_OF_STEEL",
    "CARD.GANG_UP", "CARD.GOLD_AXE", "CARD.HELLO_WORLD", "CARD.HELLRAISER",
    "CARD.HIDDEN_GEM", "CARD.INFERNO", "CARD.INFLAME", "CARD.JUGGERNAUT",
    "CARD.JUGGLING", "CARD.MAYHEM", "CARD.MIMIC", "CARD.MIND_BLAST",
    "CARD.NORMALITY", "CARD.NOSTALGIA", "CARD.ONE_TWO_PUNCH", "CARD.OUTMANEUVER",
    "CARD.PANACHE", "CARD.PANIC_BUTTON", "CARD.PERFECTED_STRIKE", "CARD.PREP_TIME",
    "CARD.PROWESS", "CARD.PYRE", "CARD.RAGE", "CARD.RAMPAGE",
    "CARD.REBOUND", "CARD.RELAX", "CARD.REND", "CARD.ROLLING_BOULDER",
    "CARD.RUPTURE", "CARD.SALVO", "CARD.SETUP_STRIKE", "CARD.SOVEREIGN_BLADE",
    "CARD.STACK", "CARD.STAMPEDE", "CARD.STONE_ARMOR", "CARD.STRATAGEM",
    "CARD.TANK", "CARD.TEAR_ASUNDER", "CARD.THE_BALL", "CARD.THE_BOMB",
    "CARD.THE_GAMBIT", "CARD.THRASH", "CARD.TORIC_TOUGHNESS", "CARD.UNMOVABLE",
    "CARD.UNRELENTING", "CARD.VICIOUS",
})

# Powers the card applies to the player that the end-turn value reads: (power, card variable).
SELF_POWER_END = {
    "CARD.STONE_ARMOR": ("POWER.PLATING_POWER", "PlatingPower"),
    "CARD.ETERNAL_ARMOR": ("POWER.PLATING_POWER", "PlatingPower"),
    "CARD.FEEL_NO_PAIN": ("POWER.FEEL_NO_PAIN_POWER", "Power"),
    "CARD.APPARITION": ("POWER.INTANGIBLE_POWER", "IntangiblePower"),
    "CARD.FLAME_BARRIER": ("POWER.FLAME_BARRIER_POWER", "DamageBack"),
    "CARD.CALTROPS": ("POWER.THORNS_POWER", "ThornsPower"),
    "CARD.THE_GAMBIT": ("POWER.THE_GAMBIT_POWER", None),
    "CARD.STAMPEDE": ("POWER.STAMPEDE_POWER", None),
    "CARD.JUGGERNAUT": ("POWER.JUGGERNAUT_POWER", "JuggernautPower"),
}
APPLIES_VULNERABLE = frozenset("CARD." + n for n in
    "BASH BREAK DOMINATE MOLTEN_FIST SHOCKWAVE SQUASH TAUNT THUNDERCLAP TREMBLE UPPERCUT".split())
# Player powers that react to drawn cards (Hellraiser auto-plays drawn Strikes).
ON_DRAW_POWERS = ("HELLRAISER_POWER", "AUTOMATION_POWER", "CACOPHONY_POWER", "CHAINS_OF_BINDING_POWER",
                  "CONFUSED_POWER", "CORROSIVE_WAVE_POWER", "PAGESTORM_POWER", "ITERATION_POWER", "SPEEDSTER_POWER")
# Cards applying a power to an enemy: a replayed copy hits a changed enemy (Bash -> Vulnerable).
APPLIES_ENEMY_POWER = frozenset("CARD." + n for n in
    "BASH BLAZE BREAK COORDINATE DARK_SHACKLES DOMINATE FIGHT_ME INTERCEPT KNOCKDOWN MANGLE MOLTEN_FIST "
    "PROLONG SHOCKWAVE SQUASH TAG_TEAM TAUNT THUNDERCLAP TREMBLE UPPERCUT WHISTLE".split())
# Exhaust one chosen hand card (CardSelectCmd.FromHand, min 1): auto-selected when it is the only one.
CHOOSE_ONE_EXHAUST = ("CARD.TRUE_GRIT", "CARD.BRAND", "CARD.BURNING_PACT")
# Random exhaust of one hand card (True Grit unupgraded; Cinder after its attack).
RANDOM_HAND_EXHAUST = ("CARD.TRUE_GRIT", "CARD.CINDER")
# Enemy-applied powers (on the player or an enemy) that react to the player's card plays:
# HP loss (Strangle, Haunt, Gravity, Galvanic), Strength / Dexterity changes (Enrage, Monologue,
# Tender), cards or afflictions added (Withering Presence, Smoggy, Chains of Binding, Vital Spark).
PLAY_REACTIVE_POWERS = frozenset("POWER." + n for n in
    "ENRAGE_POWER STRANGLE_POWER SMOGGY_POWER HAUNT_POWER TENDER_POWER WITHERING_PRESENCE_POWER "
    "CHAINS_OF_BINDING_POWER GALVANIC_POWER VITAL_SPARK_POWER GRAVITY_POWER MONOLOGUE_POWER".split())
# Enchantments whose card values change after a play (a replayed copy differs).
ENCHANT_VARIES = ("ENCHANTMENT.MOMENTUM", "ENCHANTMENT.GOOPY", "ENCHANTMENT.VIGOROUS")
# Relics / powers that change Strength or Dexterity after a play (later replays differ).
_MID_SERIES = ("RELIC.SHURIKEN", "RELIC.KUNAI", "RELIC.RAINBOW_RING", "RELIC.RED_SKULL")


def _hand_sensitive(facts, hand, removal=False):
    """True if the turn-end value depends on which cards are in hand beyond those known
    (cards may be added; with ``removal`` a random one of ``hand`` may also leave)."""
    if "RELIC.CLOAK_CLASP" in _relics(facts) or _power(facts["powers"], "POWER.FEEL_NO_PAIN_POWER") > 0:
        return True
    if any(c["modelId"] == "CARD.REGRET" for c in hand):
        return True
    special = TURN_END_DAMAGE | set(TURN_END_HP_LOSS) | {"CARD.REGRET"}
    pool = [c for c in facts["cards"] if c["pile"] in ("draw", "discard")] + (list(hand) if removal else [])
    return any(c["modelId"] in special or "Ethereal" in c["keywords"] for c in pool)


class _Play:
    """Player-side resolution of one play (see the section comment)."""

    def __init__(self, card, target, facts):
        self.facts, self.card, self.target = facts, card, target
        self.relics = {r["modelId"]: r for r in facts["relics"] if r["status"] != "Disabled"}
        self.powers = facts["powers"]
        self.hittable = {e["order"]: e for e in _hittable(facts)}
        self.player = _Player(facts, 0)
        self.hand = [c for c in facts["cards"] if c["pile"] == "hand" and c is not card]
        self.damage = {}
        self.block = 0
        self.heal = 0
        self.unknown = False          # this play's own numbers
        self.end_unknown = False      # only the end-turn value after it
        self.hand_change = False
        self.hand_removal = False
        self.random_damage = 0.0      # total randomly targeted damage (a kill is then uncertain)
        self.energy = _energy_after(card, facts)
        combat = facts["combat"]
        self.attacks, self.skills, self.cards = combat["attacksPlayedTurn"], combat["skillsPlayedTurn"], combat["cardsPlayedTurn"]

    def power(self, name):
        return _power(self.powers, "POWER." + name)

    def counter(self, relic):
        return self.relics[relic]["counter"]

    def deal(self, amount, orders):
        """Damage to orders (list of enemy orders; a random pick gets the expectation)."""
        for order in orders:
            self.damage[order] = self.damage.get(order, 0) + amount

    def deal_random(self, amount):
        self.random_damage += amount
        if self.hittable:
            self.deal(amount / len(self.hittable), list(self.hittable))

    def gain_block(self, amount):
        if amount <= 0:
            return
        self.player.block += amount
        self.block += amount
        juggernaut = self.power("JUGGERNAUT_POWER")      # JuggernautPower.AfterBlockGained
        if juggernaut:
            self.deal_random(juggernaut)

    def lose_hp(self, amount):
        hp = self.facts["player"]["hp"] - self.player.lost
        lost = self.player.damage(amount, blockable=False)
        half = self.facts["player"]["maxHp"] / 2
        if "RELIC.RED_SKULL" in self.relics and hp > half >= hp - lost and self.card["type"] == "Attack":
            self.unknown = True                           # RedSkull +Strength before this card's hits
        if lost > 0:
            inferno = self.power("INFERNO_POWER")         # InfernoPower.AfterDamageReceived (own turn)
            if inferno:
                self.deal(inferno, list(self.hittable))
            if "RELIC.DEMON_TONGUE" in self.relics:       # heal once per turn: trigger state not public
                self.unknown = True
            if "RELIC.CENTENNIAL_PUZZLE" in self.relics:  # draw 3 once per combat
                self.hand_change = True

    def exhausted(self, card):
        """AfterCardExhausted for one of the player's cards (``None``: a random hand card)."""
        self.gain_block(self.power("FEEL_NO_PAIN_POWER"))
        if card is None:
            if "RELIC.BURNING_STICKS" in self.relics or any(c["modelId"] == "CARD.DRUM_OF_BATTLE" for c in self.hand):
                self.unknown = True
            card = {"type": None, "modelId": None}
        if card["modelId"] == "CARD.DRUM_OF_BATTLE":     # DrumOfBattle.AfterCardExhausted: energy x play count
            if card["replay"] or card["enchantedReplay"] or self.power("DUPLICATION_POWER") or self.power("BURST_POWER") \
                    or "RELIC.THROWING_AXE" in self.relics:
                self.unknown = True
            self.energy += int(_var(card, "Energy") or 0)
        if self.power("DARK_EMBRACE_POWER") or "RELIC.JOSS_PAPER" in self.relics:
            self.hand_change = True
        if "RELIC.BURNING_STICKS" in self.relics and self.relics["RELIC.BURNING_STICKS"]["status"] == "Active"                 and card["type"] == "Skill":
            self.hand_change = True
        if "RELIC.CHARONS_ASHES" in self.relics:
            self.deal(3, list(self.hittable))
        if "RELIC.FORGOTTEN_SOUL" in self.relics:
            self.deal_random(1)

    def play_count(self):
        card, kind = self.card, self.card["type"]
        count = 1 + max(card["replay"], card["enchantedReplay"])
        count += kind == "Attack" and self.power("ONE_TWO_PUNCH_POWER") > 0
        count += self.power("DUPLICATION_POWER") > 0
        count += kind == "Skill" and self.power("BURST_POWER") > 0
        throwing_axe = self.relics.get("RELIC.THROWING_AXE")
        count += throwing_axe is not None and throwing_axe["status"] == "Active"
        if self.power("ECHO_FORM_POWER") or self.power("TAG_TEAM_POWER") or self.power("SIGNAL_BOOST_POWER"):
            self.unknown = True
        return count

    def run(self):
        card, facts, mid = self.card, self.facts, self.card["modelId"]
        if mid not in REVIEWED or mid in OPAQUE or card["previewUnsupported"]:
            self.unknown = True
        if any(a[0] != "AFFLICTION.HEXED" for a in card["afflictions"]):
            self.unknown = True                           # enemy afflictions act on play (Galvanized, Tainted, ...)
        if any(pw[0] in PLAY_REACTIVE_POWERS for pw in self.powers) or any(
                pw[0] in PLAY_REACTIVE_POWERS for e in facts["enemies"] if e["alive"] for pw in e["powers"]):
            self.unknown = True
        plays = self.play_count()
        if plays > 1 and (mid in REPLAY_VARIES or mid in APPLIES_ENEMY_POWER or mid in SELF_HP_LOSS and self.power("RUPTURE_POWER")
                          or any(r in self.relics for r in _MID_SERIES) or self.power("VIGOR_POWER")
                          or "RELIC.PEN_NIB" in self.relics or "RELIC.VAMBRACE" in self.relics
                          or "RELIC.THE_BOOT" in self.relics   # replays hit the block the last one left
                          or "RELIC.PAELS_LEGION" in self.relics):
            self.unknown = True
        enchant = card["enchantment"]
        if plays > 1 and enchant is not None and enchant[0] in ENCHANT_VARIES:
            self.unknown = True
        cost = _energy_cost(card, facts)
        for i in range(plays):
            self.before_played(cost)
            self.on_play()
            self.enchantment_played(enchant, first=i == 0)
            self.after_played()
        if card["type"] != "Power" and ("Exhaust" in card["keywords"] or card["exhaustOnNextPlay"]
                                        or card["type"] == "Skill" and self.power("CORRUPTION_POWER")):
            self.exhausted(card)
        if card["target"] == "RandomEnemy":
            self.random_damage += sum((play_damage(card, facts, self.target) or {}).values()) * plays
        if mid == "CARD.COLOSSUS" and any(e["alive"] and _power(e["powers"], "POWER.VULNERABLE_POWER") > 0
                                          for e in facts["enemies"]):
            self.end_unknown = True                       # halves what the Vulnerable enemies' intents show
        if mid in HAND_CHANGE:
            self.hand_change = True
        if mid in ENEMY_TURN_CHANGE:
            self.end_unknown = True
        self.on_kills()
        if any(self.damage.get(o, 0) >= e["hp"] + e["block"] and not {pw[0] for pw in e["powers"]} <= DEATH_QUIET_POWERS
               for o, e in self.hittable.items()):
            self.end_unknown = True                       # its own defenses may keep it alive
        if any(self.damage.get(o, 0) > 0 and _reacts_on_hit(e) for o, e in self.hittable.items()):
            self.end_unknown = True                       # its reaction (retaliation, waking, ...) is not modelled
        if self.hand_change and _hand_sensitive(facts, self.hand, self.hand_removal):
            self.end_unknown = True
        if self.random_damage and len(self.hittable) > 1 and any(
                self.damage.get(o, 0) - self.random_damage < e["hp"] + e["block"] <= self.damage.get(o, 0) + self.random_damage
                for o, e in self.hittable.items()):
            self.end_unknown = True                       # whether a random hit kills is a coin flip
        if self.power("COLOSSUS_POWER") and mid in APPLIES_VULNERABLE:
            self.end_unknown = True                       # ColossusPower halves a now-Vulnerable enemy's hits (DEVLOG 58)
        if self.power("VICIOUS_POWER") and mid in APPLIES_VULNERABLE:
            self.hand_change = True                       # ViciousPower: draw on applying Vulnerable
        if card["type"] == "Attack" and (self.power("CALAMITY_POWER") or self.power("JUGGLING_POWER")):
            self.hand_change = True                       # generated Attacks / copies to hand
        if self.power("PANACHE_POWER"):
            self.unknown = True                           # damage every 5 cards: count not public
        if self.hand_change and (any(c["modelId"] == "CARD.VOID" for c in facts["cards"] if c["pile"] in ("draw", "discard"))
                                 or any(self.power(name) for name in ON_DRAW_POWERS) or mid == "CARD.HELLRAISER"):
            self.unknown = True                           # drawn cards act (Void energy, Hellraiser ...)
        self.gained = {}
        if mid in SELF_POWER_END:
            power, var = SELF_POWER_END[mid]
            self.gained[power] = int(_var(card, var) or 0) if var else 1
        return self

    def on_kills(self):
        """Player-side AfterDeath reactions to the enemies this play kills."""
        kills, unsure = 0, False
        for order, e in self.hittable.items():
            dealt, pool = self.damage.get(order, 0), e["hp"] + e["block"]
            if self.random_damage and dealt - self.random_damage < pool <= dealt + self.random_damage \
                    and len(self.hittable) > 1:
                unsure = True
            elif dealt >= pool:
                kills += 1
        if "RELIC.GREMLIN_HORN" in self.relics and (kills or unsure):
            self.unknown |= unsure                        # GremlinHorn.AfterDeath: +Energy, draw
            self.energy += kills
            self.hand_change = True
        if (kills or unsure) and self.power("CONSTRICT_POWER"):
            self.end_unknown = True                       # Constrict ends if its applier dies

    def before_played(self, cost):
        if "RELIC.INTIMIDATING_HELMET" in self.relics and cost >= 2:
            self.gain_block(4)

    def on_play(self):
        card, facts, mid = self.card, self.facts, self.card["modelId"]
        if mid in SELF_HP_LOSS:
            self.lose_hp(int(_var(card, "HpLoss") or 0))
        dmg = play_damage(card, facts, self.target)
        if dmg is None:
            self.unknown = True
        else:
            for order, value in dmg.items():
                self.deal(value, [order])
        doubler = any(self.relics.get(r, {}).get("status") == "Active" for r in ("RELIC.VAMBRACE",)) or \
            "RELIC.PAELS_LEGION" in self.relics
        if doubler and (mid == "CARD.SECOND_WIND" or mid == "CARD.EVIL_EYE" and facts["combat"]["cardsExhaustedTurn"] > 0):
            self.unknown = True                           # the x2 applies to one GainBlock only
        if mid == "CARD.SECOND_WIND":                     # exhaust each non-Attack in hand, then block
            for other in [c for c in self.hand if c["type"] != "Attack"]:
                self.hand.remove(other)
                self.exhausted(other)
                self.gain_block(card["displayBlock"] or 0)
        elif mid == "CARD.EVIL_EYE":                      # second GainBlock if a card was exhausted this turn
            for _ in range(2 if facts["combat"]["cardsExhaustedTurn"] > 0 else 1):
                self.gain_block(card["displayBlock"] or 0)
        elif mid == "CARD.ENTRENCH":                      # GainBlock(current Block), Unpowered | Move
            # Move-flagged block: Vambrace, Pael's Legion and Unmovable may double it. Whether
            # Unmovable is still unused this turn (no card BlockGainedEntry yet) is not public
            # (DEVLOG 54: the audit found Entrench previewed 7 for an actual 14).
            if "RELIC.VAMBRACE" in self.relics or "RELIC.PAELS_LEGION" in self.relics or \
                    _power(facts["powers"], "POWER.UNMOVABLE_POWER") > 0:
                self.unknown = True
            # The card's own block enchantments add to this GainBlock too (Nimble +Amount, even at
            # 0 Block; Goopy's growing Amount is not tracked). displayBlock covers them for
            # ordinary block cards; Entrench reads the current Block instead (DEVLOG 54).
            ench = card.get("enchantment")
            extra = 0
            if ench:
                if ench[0] == "ENCHANTMENT.NIMBLE" and not ench[2]:
                    extra = ench[1]
                elif ench[0] in ("ENCHANTMENT.GOOPY",):
                    self.unknown = True
            self.gain_block(self.player.block + extra)
        else:
            self.gain_block(card["displayBlock"] or 0)
        if mid in RANDOM_HAND_EXHAUST and not (mid == "CARD.TRUE_GRIT" and card["upgrade"]) and self.hand:
            self.hand_removal = True                      # CombatCardSelection.NextItem(hand)
            self.exhausted(None)
        elif mid == "CARD.STOKE":                         # exhaust the whole hand, then generate as many
            for other in list(self.hand):
                self.hand.remove(other)
                self.exhausted(other)
        elif mid in CHOOSE_ONE_EXHAUST and len(self.hand) == 1:
            only = self.hand.pop()                        # only candidate: selected without a screen
            self.exhausted(only)
        if mid in ENERGY_GAIN or mid == "CARD.RESTLESSNESS" and not self.hand:
            self.energy += int(_var(card, "Energy") or 0)
        if mid == "CARD.NOT_YET":
            room = facts["player"]["maxHp"] - (facts["player"]["hp"] - self.player.lost + self.heal)
            self.heal += max(0, min(int(_var(card, "Heal") or 0), room))
        if mid == "CARD.BRIGHTEST_FLAME":                 # LoseMaxHp 2: current HP capped by the new max
            hp = facts["player"]["hp"] - self.player.lost + self.heal
            over = hp - (facts["player"]["maxHp"] - int(_var(card, "MaxHp") or 0))
            if over > 0:
                self.heal -= over
        if mid == "CARD.FEED" and any(self.damage.get(o, 0) >= e["hp"] + e["block"] for o, e in self.hittable.items()):
            self.unknown = True                           # max HP gain on a kill

    def enchantment_played(self, enchant, first):
        """EnchantmentModel.OnPlay, after the card's own OnPlay (Sown energy is in _energy_after)."""
        if enchant is None:
            return
        kind, amount, disabled = enchant[0], enchant[1], enchant[2]
        if kind == "ENCHANTMENT.CORRUPTED":               # 2 unblockable HP loss every play
            self.lose_hp(2)
        elif kind == "ENCHANTMENT.SWIFT" and first and not disabled:
            self.hand_change = True                       # draw Amount, then disabled
        elif kind == "ENCHANTMENT.ADROIT":
            self.unknown = True                           # Move block from the enchantment: modifiers not reviewed
        elif kind == "ENCHANTMENT.INKY":
            self.end_unknown = True                       # Weak on the target(s) changes their attacks

    def after_played(self):
        kind = self.card["type"]
        relics = self.relics
        if kind == "Attack":
            self.gain_block(self.power("RAGE_POWER"))     # RagePower.AfterCardPlayed
            self.attacks += 1
            if "RELIC.ORNAMENTAL_FAN" in relics and self.attacks % 3 == 0:
                self.gain_block(4)
            if "RELIC.KUSARIGAMA" in relics and self.attacks % 3 == 0:
                self.deal_random(6)
            if "RELIC.DAUGHTER_OF_THE_WIND" in relics:
                self.gain_block(1)
            if "RELIC.NUNCHAKU" in relics:
                self.relics["RELIC.NUNCHAKU"] = dict(self.relics["RELIC.NUNCHAKU"], counter=self.counter("RELIC.NUNCHAKU") + 1)
                if self.counter("RELIC.NUNCHAKU") % 10 == 0:
                    self.energy += 1
            if "RELIC.MUSIC_BOX" in relics:
                self.hand_change = True                   # Ethereal copy to hand (first Attack each turn)
        elif kind == "Skill":
            self.skills += 1
            if "RELIC.LETTER_OPENER" in relics and self.skills % 3 == 0:
                self.deal(5, list(self.hittable))
            if "RELIC.TUNING_FORK" in relics:
                self.relics["RELIC.TUNING_FORK"] = dict(self.relics["RELIC.TUNING_FORK"], counter=self.counter("RELIC.TUNING_FORK") + 1)
                if self.counter("RELIC.TUNING_FORK") >= 10:
                    self.gain_block(7)
                    self.relics["RELIC.TUNING_FORK"]["counter"] -= 10
        elif kind == "Power":
            if "RELIC.LOST_WISP" in relics:
                self.deal(8, list(self.hittable))
            if "RELIC.GAME_PIECE" in relics:
                self.hand_change = True
            if "RELIC.PERMAFROST" in relics:              # first Power of the combat: state not public
                self.unknown = True
        self.cards += 1
        if "RELIC.IRON_CLUB" in relics:
            self.relics["RELIC.IRON_CLUB"] = dict(self.relics["RELIC.IRON_CLUB"], counter=self.counter("RELIC.IRON_CLUB") + 1)
            if self.counter("RELIC.IRON_CLUB") % 4 == 0:
                self.hand_change = True


def action_preview(state):
    """{action index: dict} for plays and end_turn."""
    facts = state.facts
    out = {}
    current = end_turn(facts)
    hp = facts["player"]["hp"]
    for index, action in enumerate(state.actions):
        if action.key.kind == "end_turn":
            out[index] = dict(known=True, hp_damage=0, kills=0, total_damage=0, block=0,
                              energy_after=facts["player"]["energy"], end_turn_loss=current[0],
                              lethal_after=current[0] >= hp, unknown=current[1], self_hp_loss=0)
    for index, card, target in _plays(state):
        play = _Play(card, target, facts).run()
        dmg, enemies = play.damage, play.hittable
        target_loss, total, kills = 0, 0.0, 0.0
        for order, value in dmg.items():
            e = enemies[order]
            pool = e["hp"] + e["block"]
            taken = min(value, pool)
            total += taken
            if value >= pool:
                kills += 1
            if order == target:
                target_loss = taken
        unknown = play.unknown
        if kills and any(e["alive"] and dmg.get(e["order"], 0) < e["hp"] + e["block"]
                         and not {pw[0] for pw in e["powers"]} <= DEATH_QUIET_POWERS for e in facts["enemies"]):
            unknown = True                                   # survivors may react to the kill
        silenced = {target} if card["modelId"] == "CARD.WHISTLE" and target is not None else ()
        after = end_turn(facts, enemy_damage=dmg, attack_played=card["type"] == "Attack",
                         player=play.player, hand=play.hand, silenced=silenced, gained=play.gained)
        self_loss = play.player.lost - play.heal
        out[index] = dict(known=not unknown, hp_damage=target_loss, kills=kills, total_damage=total,
                          block=play.block, energy_after=play.energy, self_hp_loss=self_loss,
                          end_turn_loss=after[0], lethal_after=self_loss + after[0] >= hp,
                          unknown=unknown or play.end_unknown or after[1])
    return out
