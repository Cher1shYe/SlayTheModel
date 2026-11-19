from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from parity.compare import (
    HostClient, HostError, compare_decision, decode_json_response, load_actions,
    run_comparison, verify_native_identity, wait_for_ready,
)
from parity.semantic import ActionKey, project_native
from parity.tests.test_semantic import native_frame, simulator_projection


class FakeClock:
    now = 0.0

    def monotonic(self):
        return self.now

    def wait(self, seconds):
        self.now += seconds


class FakeClient:
    timeout = 10

    def __init__(self, states):
        self.states = list(states)
        self.reads = 0
        self.posts = []

    def state(self, *, timeout=None):
        index = min(self.reads, len(self.states) - 1)
        self.reads += 1
        return deepcopy(self.states[index])

    def request(self, method, path, payload):
        self.posts.append((method, path, payload))
        raise HostError("test HTTP failure after request; not retried")


class CompareClientTests(unittest.TestCase):
    def test_full_interface_checks_additional_public_facts_and_encoded_inputs(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "train"))
        from spire_rl import public_obs
        import numpy as np
        frame=native_frame()
        native=project_native(frame)
        simulator=simulator_projection(native)
        left=public_obs.PublicState({"visibleCounter": 2}, (), "simulator")
        right=public_obs.PublicState({"visibleCounter": 3}, (), "native")
        # These facts are deliberately absent from the old public subset.
        with patch("parity.compare.project_simulator",return_value=simulator), \
             patch.object(public_obs,"from_simulator",return_value=left), \
             patch.object(public_obs,"from_native",return_value=right), \
             patch.object(public_obs,"encode",side_effect=lambda state:SimpleNamespace(
                 num=np.array([state.facts["visibleCounter"]],dtype=np.float32))):
            report,_,_=compare_decision(frame,object(),object(),None,observation_schema="spire.public/1")
        self.assertEqual(report["status"],"mismatch")
        self.assertEqual(report["public_state_diff"],{})
        self.assertEqual(report["model_state_diff"][0][0],"public.visibleCounter")
        self.assertEqual(report["model_input_diff"]["num"]["count"],1)
        json.dumps(report)

    def test_full_interface_missing_field_stops_before_action(self):
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "train"))
        from spire_rl import public_obs
        frame=native_frame()
        simulator=simulator_projection(project_native(frame))
        with tempfile.TemporaryDirectory() as directory, \
             patch("parity.compare.project_simulator",return_value=simulator), \
             patch("parity.compare.wait_for_ready",return_value=frame), \
             patch.object(public_obs,"from_native",side_effect=public_obs.ObservationCoverageError("public.missing")), \
             patch.object(public_obs,"from_simulator",return_value=public_obs.PublicState({},(),"simulator")):
            client=FakeClient([frame])
            report=run_comparison(client,object(),object(),Path(directory),steps=1,
                diagnostic_policy="first-legal",observation_schema="spire.public/1")
            self.assertEqual(report["status"],"unsupported")
            self.assertEqual(client.posts,[])

    def test_run_identity_requires_all_six_expected_fields(self):
        expected = {"seed": "PAR1TY0001", "character": "IRONCLAD", "ascension": 10,
                    "gameVersion": "v0.111.0", "gameCommit": "41cef1ea",
                    "gameDllSha256": "target-sha256"}
        frame = native_frame()
        with self.assertRaisesRegex(HostError, "runIdentity is missing"):
            verify_native_identity(frame, expected)
        frame["runIdentity"] = dict(expected)
        verify_native_identity(frame, expected)
        for field in expected:
            with self.subTest(field=field):
                changed = deepcopy(frame)
                changed["runIdentity"][field] = "wrong"
                with self.assertRaisesRegex(HostError, "identity mismatch") as caught:
                    verify_native_identity(changed, expected)
                self.assertIn(field, caught.exception.details["identity_diff"])

    def test_different_seed_cannot_pass_an_identical_initial_public_state(self):
        frame = native_frame()
        frame["runIdentity"] = {"seed": "WRONGSEED"}
        simulator = simulator_projection(project_native(frame))
        client = FakeClient([frame])
        with tempfile.TemporaryDirectory() as directory, \
             patch("parity.compare.project_simulator", return_value=simulator), \
             patch("parity.compare.wait_for_ready", return_value=frame):
            result = run_comparison(client, object(), object(), Path(directory),
                                    steps=1, diagnostic_policy="first-legal",
                                    expected_identity={"seed": "PAR1TY0001"})
            self.assertEqual(result["status"], "host_error")
            self.assertEqual(client.posts, [])
            self.assertEqual(result["aligned_decisions"], 0)

    def test_poll_requires_changed_revision_and_repeated_ready_snapshot(self):
        client = FakeClient([
            {"revision": 8, "status": "ready"},
            {"revision": 9, "status": "busy"},
            {"revision": 10, "status": "ready", "actions": [1]},
            {"revision": 11, "status": "ready", "actions": [2]},
            {"revision": 11, "status": "ready", "actions": [2]},
        ])
        clock = FakeClock()
        result = wait_for_ready(client, after_revision=8, timeout=2, poll_interval=0.15,
                                monotonic=clock.monotonic, wait=clock.wait)
        self.assertEqual(result["revision"], 11)
        self.assertEqual(client.reads, 5)

    def test_unchanged_ready_revision_times_out_with_last_state(self):
        client = FakeClient([{"revision": 8, "status": "ready"}])
        clock = FakeClock()
        with self.assertRaisesRegex(HostError, "ready-state timeout") as caught:
            wait_for_ready(client, after_revision=8, timeout=0.3, poll_interval=0.1,
                           monotonic=clock.monotonic, wait=clock.wait)
        self.assertEqual(caught.exception.last_state["revision"], 8)
        self.assertAlmostEqual(clock.now, 0.3)

    def test_ready_with_async_action_error_is_not_success(self):
        frame = {"revision": 9, "status": "ready", "error": "card play failed"}
        with self.assertRaisesRegex(HostError, "card play failed"):
            wait_for_ready(FakeClient([frame]))
        full_frame = native_frame()
        full_frame["error"] = "card play failed"
        with self.assertRaisesRegex(ValueError, "card play failed"):
            project_native(full_frame)

    def test_non_json_and_malformed_json_have_distinct_errors(self):
        with self.assertRaisesRegex(HostError, "expected application/json") as html:
            decode_json_response(b"<html>gateway failed</html>", "text/html", "http://local/api/state")
        self.assertIn("gateway failed", html.exception.details["response_excerpt"])
        with self.assertRaisesRegex(HostError, "malformed JSON at line"):
            decode_json_response(b"{broken", "application/json", "http://local/api/state")

    def test_http_error_preserves_status_and_body_without_json_parse(self):
        client = HostClient("http://127.0.0.1:18779")
        failure = HTTPError(client.url, 409, "Conflict", {}, io.BytesIO(b"not json: stale revision"))
        with patch.object(client.opener, "open", side_effect=failure):
            with self.assertRaisesRegex(HostError, "HTTP 409") as caught:
                client.request("POST", "/api/action", {"revision": 8, "actionId": "a0"})
        self.assertEqual(caught.exception.details["http_status"], 409)
        self.assertIn("stale revision", caught.exception.details["response_excerpt"])

    def test_explicit_sequence_keeps_semantic_key_not_candidate_index(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "actions.json"
            path.write_text(json.dumps([{"kind": "move", "args": [5, 1]},
                                       {"kind": "play", "args": [[0, "BASH", 0, 2], ["NIBBIT", 40, 40, 0]]}]))
            actions = load_actions(path)
            self.assertEqual(actions[0], ActionKey("move", (5, 1)))
            self.assertIsInstance(actions[1].args[0], tuple)

    def test_mismatch_is_saved_before_any_action_submission(self):
        frame = native_frame()
        native = project_native(frame)
        simulator = simulator_projection(native)
        simulator.public_state["hp"] = 63
        client = FakeClient([frame])
        with tempfile.TemporaryDirectory() as directory, \
             patch("parity.compare.project_simulator", return_value=simulator), \
             patch("parity.compare.wait_for_ready", return_value=frame):
            result = run_comparison(client, object(), object(), Path(directory),
                                    steps=1, diagnostic_policy="first-legal")
            self.assertEqual(result["status"], "mismatch")
            self.assertEqual(client.posts, [])
            saved = json.loads((Path(directory) / "decision-0000-comparison.json").read_text())
            self.assertEqual(saved["public_state_diff"]["hp"], {"simulator": 63, "native": 64})
            self.assertTrue((Path(directory) / "decision-0000-native.json").exists())

    def test_unsupported_frame_never_submits_an_action(self):
        frame = native_frame()
        simulator = simulator_projection(project_native(frame))
        del frame["entities"][0]["slotIndex"]
        client = FakeClient([frame])
        with tempfile.TemporaryDirectory() as directory, \
             patch("parity.compare.project_simulator", return_value=simulator), \
             patch("parity.compare.wait_for_ready", return_value=frame):
            result = run_comparison(client, object(), object(), Path(directory),
                                    steps=1, diagnostic_policy="first-legal")
            self.assertEqual(result["status"], "unsupported")
            self.assertEqual(client.posts, [])

    def test_failed_post_does_not_advance_simulator_or_retry(self):
        frame = native_frame()
        simulator = simulator_projection(project_native(frame))
        client = FakeClient([frame])
        # No step_combat method: a mistaken advance would raise AttributeError.
        rc = object()
        with tempfile.TemporaryDirectory() as directory, \
             patch("parity.compare.project_simulator", return_value=simulator), \
             patch("parity.compare.wait_for_ready", return_value=frame):
            result = run_comparison(client, rc, object(), Path(directory),
                                    steps=1, diagnostic_policy="first-legal")
            self.assertEqual(result["status"], "host_error")
            self.assertEqual(len(client.posts), 1)
            self.assertEqual(result["actions_submitted"], 0)
            saved = json.loads((Path(directory) / "decision-0000-comparison.json").read_text())
            self.assertEqual(saved["native_request"], {"revision": 8, "actionId": "a7"})

    def test_native_accepted_but_simulator_rejected_stops_and_records_failure(self):
        frame = native_frame()
        simulator = simulator_projection(project_native(frame))

        class AcceptingClient(FakeClient):
            def request(self, method, path, payload):
                self.posts.append((method, path, payload))
                return {"revision": 9, "status": "busy"}

        class RejectingSimulator:
            def __init__(self, raises):
                self.raises = raises
                self.steps = 0

            def step_combat(self, *action):
                self.steps += 1
                if self.raises:
                    raise RuntimeError("simulated rejection")
                return False

        for raises in (False, True):
            with self.subTest(raises=raises), tempfile.TemporaryDirectory() as directory, \
                 patch("parity.compare.project_simulator", return_value=simulator), \
                 patch("parity.compare.wait_for_ready", return_value=frame) as wait_ready:
                client = AcceptingClient([frame])
                rc = RejectingSimulator(raises)
                result = run_comparison(client, rc, object(), Path(directory),
                                        steps=1, diagnostic_policy="first-legal")
                self.assertEqual(result["status"], "simulator_error")
                self.assertEqual(result["actions_submitted"], 1)
                self.assertEqual(len(client.posts), 1)
                self.assertEqual(rc.steps, 1)
                self.assertEqual(wait_ready.call_count, 1)
                saved = json.loads((Path(directory) / "summary.json").read_text())
                self.assertEqual(saved["status"], "simulator_error")


if __name__ == "__main__":
    unittest.main()
