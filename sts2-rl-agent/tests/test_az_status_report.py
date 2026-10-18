"""The consolidated status document must stay consistent with the frozen evidence."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

from report_all_xs_status import build  # noqa: E402


def test_status_document_has_frozen_sections():
    text = build()
    assert text.startswith('# AZ All-Content Status')
    assert 'ironclad-colorless-all-v6' in text
    assert 'risk-terminal-v7' in text
    assert '| Admitted encounters | 76 |' in text
    assert '| Admitted card pool | 146 |' in text
    assert '| Robust encounters | 76/76 |' in text
    assert '| ready | | | True |' in text
    assert '| Paired gain on 60 common recipes | **0.131**' in text
    assert 'explicit authorization' in text
    assert 'python scripts/summarize_all_xs_run.py' in text
