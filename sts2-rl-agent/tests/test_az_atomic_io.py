import ctypes
import json
import os
import threading
import pytest
from sts2_env.az import config


def conflict(code=5):
    error = PermissionError("simulated Windows sharing conflict")
    error.winerror = code
    return error


@pytest.mark.parametrize("code", [5, 32, 33])
def test_transient_conflict_preserves_original_until_commit(tmp_path, monkeypatch, code):
    path = tmp_path / "manifest.json"
    config.atomic_json(path, {"old": True})
    replace = os.replace
    attempts, sleeps = [], []
    def flaky(source, destination):
        attempts.append(source)
        assert json.loads(path.read_text()) == {"old": True}
        if len(attempts) < 4:
            raise conflict(code)
        replace(source, destination)
    monkeypatch.setattr(config.os, "replace", flaky)
    monkeypatch.setattr(config.time, "sleep", sleeps.append)
    config.atomic_json(path, {"new": True})
    assert json.loads(path.read_text()) == {"new": True}
    assert len(set(attempts)) == 1 and sleeps == [0.05, 0.1, 0.2]
    assert not list(tmp_path.glob("*.tmp"))


def test_permanent_conflict_bounded_and_no_partial_commit(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    config.atomic_json(path, {"old": True})
    sleeps = []
    def denied(*args): raise conflict()
    monkeypatch.setattr(config.os, "replace", denied)
    monkeypatch.setattr(config.time, "sleep", sleeps.append)
    with pytest.raises(PermissionError): config.atomic_json(path, {"new": True})
    assert len(sleeps) == 15 and sum(sleeps) == pytest.approx(11.55)
    assert json.loads(path.read_text()) == {"old": True}
    assert not list(tmp_path.glob("*.tmp"))


def test_other_errors_fail_without_retry(tmp_path, monkeypatch):
    def denied(*args): raise PermissionError("non-Windows permissions")
    monkeypatch.setattr(config.os, "replace", denied)
    monkeypatch.setattr(config.time, "sleep", lambda _: pytest.fail("unexpected retry"))
    with pytest.raises(PermissionError): config.atomic_json(tmp_path / "manifest.json", {})


@pytest.mark.skipif(os.name != "nt", reason="Windows sharing semantics")
def test_real_windows_handle_released_during_retry(tmp_path):
    from ctypes import wintypes
    path = tmp_path / "manifest.json"
    config.atomic_json(path, {"old": True})
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    # Allow other readers, but not FILE_SHARE_DELETE: replacement must fail until close.
    handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0, None)
    assert handle != ctypes.c_void_p(-1).value
    timer = threading.Timer(0.2, lambda: kernel.CloseHandle(handle))
    timer.start()
    try:
        config.atomic_json(path, {"new": True})
        assert json.loads(path.read_text()) == {"new": True}
    finally:
        timer.join()


def test_checkpoint_uses_same_retry(tmp_path, monkeypatch):
    from sts2_env.az.network import PolicyValueNetwork, save_checkpoint, load_checkpoint
    replace = os.replace
    attempts = []
    def flaky(source, destination):
        attempts.append(source)
        if len(attempts) == 1: raise conflict()
        replace(source, destination)
    monkeypatch.setattr(config.os, "replace", flaky)
    monkeypatch.setattr(config.time, "sleep", lambda _: None)
    path = tmp_path / "model.pt"
    save_checkpoint(path, PolicyValueNetwork("observable"), "test", {}, {})
    _, payload = load_checkpoint(path, "observable")
    assert payload["model_version"] == "test" and len(attempts) == 2
