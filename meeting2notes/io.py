"""
I/O helpers for saving notes and ensuring output directories.
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from .utils import markdown_to_text


def ensure_output_dir(subpath: str) -> Path:
    out_dir = Path.home() / "Documents" / subpath
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def save_notes(
    out_dir: Path,
    base_name: str,
    notes_md: str,
    transcript: str,
    cost_lines: List[str],
    fmt: str = "md",
) -> Path:
    """
    Compose final output (notes + transcript + cost footer) and write to disk.
    Returns the Path written.
    """
    cost_footer = (
        "\n\n---\n\n"
        "## Generation cost\n"
        + "\n".join(f"- {l}" for l in cost_lines)
        + f"\n- **Total:** £{sum(float(l.split()[-1].lstrip('£')) for l in cost_lines):.4f}\n"
    )

    final_md = (
        notes_md.rstrip()
        + "\n\n---\n\n## Transcript\n"
        + transcript.strip()
        + cost_footer
    )

    if fmt == "txt":
        output_text = markdown_to_text(final_md)
        out_path = out_dir / f"{base_name}.txt"
    else:
        output_text = final_md
        out_path = out_dir / f"{base_name}.md"

    out_path.write_text(output_text, encoding="utf-8")
    return out_path
