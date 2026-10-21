from copy import deepcopy
import pytest
from scripts.run_native_az_self_evolution import recipes_for, AlphaZeroBackend
from sts2_env.az.native_generic_backend import NativeBackend


def test_direct_promotion_never_calls_validation(monkeypatch):
    import scripts.run_native_az_self_evolution as runner
    monkeypatch.setattr(runner, 'summary', lambda raws: {'fights': len(raws)})
    state = dict(champion='old.pt', learner='old.pt', champion_rows=[{'old': True}],
                 pending={'update_checkpoint': 'new.pt'}, history=[])
    def forbidden():
        pytest.fail('Direct promotion must not run validation')
    record = runner.complete_candidate({'promotion_mode': 'direct-no-validation'},
        state, 'new.pt', [1, 2], [1, 2, 3], 1, forbidden)
    assert state['champion'] == state['learner'] == 'new.pt'
    assert state['champion_rows'] is None and state['pending'] is None
    assert state['history'] == [record]
    assert record['promoted'] and record['validation'] is None and record['paired'] is None
    assert record['updates'] == 3
    assert runner.validation_enabled({})
    assert not runner.validation_enabled({'promotion_mode': 'direct-no-validation'})
    with pytest.raises(ValueError):
        runner.validation_enabled({'promotion_mode': 'typo'})


def test_eight_workers_supported_without_relaxing_bounds():
    backend = NativeBackend.__new__(NativeBackend)
    backend.configure_workers(8)
    assert backend.workers == 8
    for value in (0, 9, True, 8.0):
        with pytest.raises(ValueError):
            backend.configure_workers(value)


def test_1024_recipes_rounds_disjoint_and_stable():
    config = dict(training=dict(episodes_per_iteration=1024), training_seed_base=4_000_000)
    protocol = dict(cards=['STRIKE_IRONCLAD', 'DEFEND_IRONCLAD'], encounters=['JAW_WORM_NORMAL'])
    first = recipes_for(config, protocol, 0)
    second = recipes_for(config, protocol, 1)
    assert first == recipes_for(deepcopy(config), protocol, 0)
    assert len({r['scenario_id'] for r in first + second}) == 2048
    assert all(r['split'] == 'train' and r['seed'] < 1_000_000_000 for r in first + second)


def test_root_only_learned_search_is_rejected():
    backend = AlphaZeroBackend.__new__(AlphaZeroBackend)
    with pytest.raises(ValueError, match='all-node'):
        backend.raw_validator(dict(leafMode='learned', valueMix=1.,
                                   searchMode='root-prior-uniform-tree-leaf-v1'))


def test_platform_executable_names(tmp_path):
    from sts2_env.az.native_platform import worker_executable
    assert worker_executable(tmp_path, 'nt').name == 'NativeWorker.exe'
    assert worker_executable(tmp_path, 'posix').name == 'NativeWorker.x86_64'


def test_linux_runtime_identity_includes_executable_and_shared_libraries(tmp_path):
    from scripts.run_native_az_self_evolution import runtime_hashes
    stage = tmp_path/'artifacts/native-host'
    stage.mkdir(parents=True)
    for name in ('NativeWorker.x86_64', 'libhostfxr.so', 'NativeWorker.runtimeconfig.json'):
        (stage/name).write_bytes(b'first')
    first = runtime_hashes(tmp_path)
    (stage/'NativeWorker.x86_64').write_bytes(b'second')
    assert runtime_hashes(tmp_path) != first
    assert len(first) == 3


def test_build_fails_before_publish_on_missing_game(tmp_path):
    from scripts.build_native_runtime import build
    with pytest.raises(ValueError, match='Missing licensed'):
        build(tmp_path/'native', tmp_path/'game', tmp_path/'ritsu')
    assert not (tmp_path/'native/artifacts').exists()


def test_run_lock_excludes_second_process(tmp_path):
    import subprocess
    import sys
    from sts2_env.az.native_platform import lock_run
    path = tmp_path/'runner.lock'
    held = lock_run(path)
    command = [sys.executable, '-c',
               'from sts2_env.az.native_platform import lock_run; import sys; lock_run(sys.argv[1])', str(path)]
    try:
        assert subprocess.run(command, capture_output=True).returncode != 0
    finally:
        held.close()
    assert subprocess.run(command, capture_output=True).returncode == 0
