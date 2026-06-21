import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_bili_note.py"


def test_run_bili_note_help_exposes_pipeline_options():
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "--archive-dir" in result.stdout
    assert "--browser-target" in result.stdout
    assert "--subtitle-mode" in result.stdout
    assert "--dry-run" in result.stdout
