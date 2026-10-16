"""T3 keeps G2.3e recipe composition, with isolated experiment RNG coordinates."""
from dataclasses import replace
from . import boss_search_curriculum as previous

VERSION = 'transformer-g23e-course-v1'
SMOKE_VERSION = 'transformer-g23e-smoke-v1'


def configuration(smoke=False):
    return dict(previous.configuration(),version=SMOKE_VERSION if smoke else VERSION,
        initial_weights='independent random S Transformer; no transfer or distillation',
        train_master_offset=None,
        environment_seed_formula='7*2**27 + namespace*2**20 + iteration*1024 + job',
        train_namespaces={'42':96} if smoke else {'42':97,'43':98},
        heldout_master_seeds={'validation':190 if smoke else 189,'test':None if smoke else 287},
        final_test_policy='reserve coordinates only; materialize after both champions freeze')


def generate(master, iteration, job, split='train', *, smoke=False):
    allowed = (42,) if smoke else (42,43)
    rounds = 2 if smoke else 3
    if (type(master)is not int or type(iteration)is not int or type(job)is not int
            or split not in ('train','validation','test')
            or (split=='train' and (master not in allowed or not 0<=iteration<rounds))
            or (split!='train' and iteration!=0) or (smoke and split=='test')):
        raise ValueError('Invalid frozen T3 coordinates')
    if split=='train':
        source_master=master
        namespace=96 if smoke else {42:97,43:98}[master]
        seed=7*2**27+namespace*2**20+iteration*1024+job
    else:
        # Same heldout composition generator coordinates as G2.3e; new env RNG.
        source_master=188 if split=='validation' else 286
        expected=190 if smoke else 189 if split=='validation' else 287
        if master!=expected: raise ValueError('Invalid heldout master')
        seed=2**30+(1_000_000 if split=='test' else 0)+master*1024+job
    recipe=previous.generate(source_master,iteration,job,split)
    # Preserve existing focus/retained prefix classification in result audits.
    return replace(recipe,environment_seed=seed,
                   scenario_id=recipe.scenario_id+'-'+(SMOKE_VERSION if smoke else VERSION))


def preparation_manifest(smoke=False):
    """No final test recipes are generated, loaded or persisted here."""
    return ([generate(42,0,j,smoke=smoke) for j in range(180)]
            +[generate(190 if smoke else 189,0,j,'validation',smoke=smoke) for j in range(256)])
