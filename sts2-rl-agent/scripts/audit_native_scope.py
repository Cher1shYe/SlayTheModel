"""Bounded native content audit; no optimizer, training runner, or promotion."""
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    import torch
    from sts2_env.az import all_runner as runner
    from sts2_env.az.config import atomic_json, content_hash
    from sts2_env.az.native_generic_backend import NativeBackend, frozen_protocol, make_recipe, single_player_card_tokens
    from sts2_env.az.native_generic import encode, GenericReplay
    from scripts.check_native_collection import sha
    out = Path(sys.argv[1]).resolve()
    if (out/'report.json').exists():
        raise ValueError('Audit already completed; use a fresh output directory')
    torch.set_num_threads(1)
    catalog = json.loads((out/'catalog.json').read_text())
    cards = single_player_card_tokens(catalog)
    assert all(c['pool'] in ('IroncladCardPool', 'ColorlessCardPool') for c in catalog['cards'])
    old = json.loads(Path('configs/az_all_xs_v1/protocol.json').read_text())
    requested = sorted({r['encounter'].removeprefix('setup_').upper() for r in old['validation']})
    available = {e['id'] for e in catalog['encounters']}
    encounters = [e for e in requested if e in available]
    protocol = frozen_protocol(cards, encounters, len(encounters))
    atomic_json(out/'protocol.json', protocol)
    config = json.loads(Path('configs/az_native_generic_v1/config.json').read_text())
    config['backend']['budget_ms'] = 250
    config['search'].update(budget=250, leaf_mode='mixed', value_mix=.5)
    atomic_json(out/'config.json', config)
    model = runner.fresh_model(config, 1907)
    checkpoint = out/'initial.pt'
    runner.save_transformer_checkpoint(checkpoint, model, config=config)
    backend = NativeBackend(config['backend'], protocol, out)
    backend.configure_search('mixed', .5)
    backend.built = True  # caller's catalog launch has just built this worker
    report = dict(formal_training_started=False, updates=0, cards=len(cards),
                  requested_encounters=len(requested), missing_encounters=sorted(set(requested)-available),
                  preflight=[], collection=[], provenance=backend.provenance)

    def save(stage):
        atomic_json(out/'progress.json', dict(stage=stage, preflight_completed=len(report['preflight']),
                    preflight_total=len(encounters), collection_completed=len(report['collection']), collection_total=8))
        atomic_json(out/'partial-report.json', report)

    recipes = [make_recipe(19070000+i, e, cards, 'train') for i,e in enumerate(encounters)]
    atomic_json(out/'recipes.json', recipes)
    for i, recipe in enumerate(recipes):
        directory = out/'preflight'/f'{i:03d}'
        directory.mkdir(parents=True)
        target = directory/'root.json'
        spec = dict(recipe=recipe, seed=recipe['seed'], hp=recipe['hp'], encounter=recipe['encounter'],
                    deck=recipe['deck'], split='train', arm='puct', output=str(target))
        job = directory/'job.json'
        atomic_json(job, dict(format=backend.format, source=str(Path.cwd()), checkpoint=str(checkpoint),
            identity=content_hash(recipe), modelSha256=sha(checkpoint), budgetMs=250,
            cases=[spec], preflightOnly=True, **backend.search_job))
        result = dict(recipe=recipe, log=str(directory/'worker.log'))
        try:
            backend._execute(job, directory/'worker.log')
            raw = json.loads(target.read_text())
            packed = encode(raw['observation'])
            result.update(ok=True, legal_actions=raw['legalActions'], entities=len(packed['entities']))
        except Exception as error:
            # Audit failures are evidence, never accepted replay or silently skipped.
            result.update(ok=False, error=f'{type(error).__name__}: {error}')
        report['preflight'].append(result)
        save('preflight')
        print('preflight', i+1, recipe['encounter'], result['ok'], flush=True)
    passed = [r['recipe'] for r in report['preflight'] if r['ok']]
    selected = random.Random(1907).sample(passed, min(8,len(passed)))
    atomic_json(out/'collection-plan.json', selected)
    replay = GenericReplay(out/'replay', leaf_mode='mixed', value_mix=.5)
    for i, recipe in enumerate(selected):
        directory = out/'collection'/f'{i:03d}'
        result = dict(recipe=recipe, log=str(directory/'worker.log'))
        try:
            episodes = backend.collect(checkpoint, [recipe], directory)
            for episode in episodes:
                replay.commit(episode)
            raw = json.loads((directory/f"{recipe['scenario_id']}.json").read_text())
            result.update(ok=True, outcome=raw['outcome'])
        except Exception as error:
            result.update(ok=False, error=f'{type(error).__name__}: {error}')
        report['collection'].append(result)
        save('collection')
        print('collection', i+1, recipe['encounter'], result['ok'], flush=True)
    report['replay_rows'] = replay.size
    report['random_deck_distinct_cards'] = len({c for r in recipes for c in r['deck']})
    atomic_json(out/'report.json', report)
    save('completed')


if __name__ == '__main__':
    main()
