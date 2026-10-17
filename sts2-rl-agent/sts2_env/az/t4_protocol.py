"""Frozen pilot combinations / whole-card-ID holdout. No training side effects."""
from dataclasses import replace
from .config import content_hash
from .scenarios import CombatScenario, DeckEntry, validate_manifest
from .transformer_course import generate
from .expanded_mechanics import describe_card
from .natural_course import seal, checked, normalized

VERSION='transformer-t4-combinations-v1'
HELDOUT_ID='BLUDGEON'
ENCOUNTERS=('setup_shrinker_beetle_weak','setup_bygone_effigy_elite','setup_test_subject_boss')


def signature(recipe):
    # HP, seed, order, scenario label and split cannot disguise the same combination.
    return content_hash([recipe.encounter_id,sorted((x.card_id,x.upgraded,x.count) for x in recipe.deck)])


def base_ids(recipe):
    return {x.card_id for x in recipe.deck}


def generate_protocol():
    groups={name:[] for name in ('train','validation','unseen_combination','unseen_id')}
    counter=0
    for family in ('block','strength'):
        for variant in range(6):
            if family=='block':
                counts=dict(BODY_SLAM=1+variant%2,IRON_WAVE=1,IMPERVIOUS=1,ARMAMENTS=1,
                            EQUILIBRIUM=1,PURITY=1,SHRUG_IT_OFF=2+variant//2)
            else:
                counts=dict(INFLAME=1,POMMEL_STRIKE=1,STOMP=1,PRIMAL_FORCE=1,
                            STRIKE_IRONCLAD=2+variant%2,DEFEND_IRONCLAD=2,SHRUG_IT_OFF=2+variant//2)
            for encounter in ENCOUNTERS:
                for hp in (40,80):
                    assignments=['train','validation'] if variant<4 else ['unseen_combination']
                    if family=='strength' and variant<4: assignments+=['unseen_id']
                    for group in assignments:
                        current=dict(counts)
                        if group=='unseen_id': current[HELDOUT_ID]=1
                        deck=tuple(DeckEntry(k, hp==80 if k==HELDOUT_ID else True,v) for k,v in sorted(current.items()))
                        split=group if group in ('train','validation') else 'test'
                        recipe=replace(generate(42,0,90),family_id='ironclad-'+family,deck=deck,
                            scenario_id=f'{VERSION}-{group}-{counter}',split=split,player_hp=hp,
                            encounter_id=encounter,environment_seed=1_500_000_000+counter)
                        # Semantic admission is explicit; unknown mechanics fail here.
                        for card in deck: describe_card(card.card_id+('+' if card.upgraded else ''))
                        groups[group].append(recipe.to_dict()); counter+=1
    templates=list(groups['validation'])
    for i in range(len(templates),256):
        template=CombatScenario.from_dict(templates[i%len(templates)])
        groups['validation'].append(replace(template,scenario_id=f'{VERSION}-validation-{counter}',
                                            environment_seed=1_500_000_000+counter).to_dict())
        counter+=1
    document=seal(dict(version=VERSION,heldout_base_ids=[HELDOUT_ID],groups=groups,
        initialization='fresh-only-no-t3-weights-or-replay',reward='risk-terminal-v7',
        primary_metric='network-mean-original-battle-terminal-utility',
        promotion='network-utility-v1',snapshot_results='diagnostic-only-not-main-gate',
        quality_claim=False,training_authorized=False,
        protocol_note='Pilot engineering freeze; no independent general-quality claim or new training budget authorized.'))
    validate_protocol(document)
    return normalized(document)


def validate_protocol(document,late_entries=(),initial_checkpoint=None):
    data=checked(document)
    if (data['version']!=VERSION or data['heldout_base_ids']!=[HELDOUT_ID]
            or data['initialization']!='fresh-only-no-t3-weights-or-replay'
            or data['reward']!='risk-terminal-v7'
            or data['primary_metric']!='network-mean-original-battle-terminal-utility'
            or data['promotion']!='network-utility-v1'
            or data['snapshot_results']!='diagnostic-only-not-main-gate'
            or initial_checkpoint is not None):
        raise ValueError('Incompatible/contaminated T4 protocol')
    if set(data['groups'])!={'train','validation','unseen_combination','unseen_id'}:
        raise ValueError('Missing evaluation group')
    groups={g:[CombatScenario.from_dict(r) for r in rows] for g,rows in data['groups'].items()}
    if any(not rows for rows in groups.values()): raise ValueError('Empty protocol group')
    validate_manifest([r for rows in groups.values() for r in rows])
    for group,recipes in groups.items():
        for recipe in recipes:
            split=group if group in ('train','validation') else 'test'
            if recipe.split!=split: raise ValueError('Split/group mismatch')
            if (HELDOUT_ID in base_ids(recipe))!=(group=='unseen_id'):
                raise ValueError('Whole ID leakage (including upgrades)')
    learned=groups['train']+groups['validation']
    for entry in late_entries:
        checked(entry)
        recipe=CombatScenario.from_dict(entry['recipe'])
        if recipe.split!='train' or HELDOUT_ID in base_ids(recipe): raise ValueError('Late course ID leakage')
        # All generated/public tokens are also checked (not merely initial deck).
        from .entity_transition import public_from_dict
        info=public_from_dict(entry['public'])
        tokens=info.hand+info.draw_composition+info.discard+info.exhaust+info.known_deck
        if any(t.removesuffix('+')==HELDOUT_ID for t in tokens): raise ValueError('Generated heldout ID leakage')
        learned.append(recipe)
    seen={signature(r) for r in learned}
    if seen & {signature(r) for r in groups['unseen_combination']}:
        raise ValueError('Combination leakage')
    train_ids=set().union(*(base_ids(r) for r in groups['train']))
    if any(not base_ids(r)<=train_ids for r in groups['unseen_combination']):
        raise ValueError('Combination group contains unseen ID')
    # BLUDGEON has one on-play damage operation, already present on Strike.
    def semantics(token):
        return {(o.kind,o.target,o.timing,o.condition) for o in describe_card(token).effects}
    known=set().union(*(semantics(c.card_id+('+' if c.upgraded else ''))
                       for r in groups['train'] for c in r.deck))
    for token in (HELDOUT_ID,HELDOUT_ID+'+'):
        if not semantics(token)<=known: raise ValueError('Unseen ID introduces unknown mechanism')
    return {g:len(rows) for g,rows in groups.items()}


def training_recipes(document):
    validate_protocol(document)
    return tuple(CombatScenario.from_dict(r) for r in document['groups']['train'])


def network_gate(document,initial,final,*,mode):
    """Only complete first-form validation outcomes can drive the frozen gate."""
    validate_protocol(document)
    if mode!='network': raise ValueError('Only network utility decides promotion')
    ids={r['scenario_id'] for r in document['groups']['validation']}
    if len(ids)!=256: raise ValueError('Frozen paired gate requires 256 validation battles')
    for rows in (initial,final):
        if len(rows)!=256 or {r.get('scenario_id') for r in rows}!=ids:
            raise ValueError('Wrong/late/heldout evaluation population')
    from .evaluation import promotion_gate
    from .rewards import V7
    return promotion_gate(initial,final,required_count=256,reward_version=V7,
                          criterion='utility-only-v1')
