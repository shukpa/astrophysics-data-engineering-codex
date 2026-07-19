"""Structural guards for the Phase 3 notebooks (no kernel execution in CI).

Full top-to-bottom execution is verified out-of-band with nbconvert; here we
only assert the committed notebooks are valid, carry their required deliverable
cells, and hold no stored error outputs. ``nbformat`` is a dev dependency, so
this runs in CI without a Jupyter kernel.
"""

from __future__ import annotations

from pathlib import Path

import nbformat
import pytest

NOTEBOOKS = Path("notebooks")
NB_3A = NOTEBOOKS / "combined_probe_constraints.ipynb"
NB_3B = NOTEBOOKS / "euclid_lens_statistics.ipynb"


@pytest.mark.parametrize("path", [NB_3A, NB_3B])
def test_notebook_is_valid(path: Path) -> None:
    assert path.exists(), f"missing notebook: {path}"
    nb = nbformat.read(path, as_version=4)
    nbformat.validate(nb)
    assert nb.cells, "notebook has no cells"


@pytest.mark.parametrize("path", [NB_3A, NB_3B])
def test_notebook_has_no_stored_errors(path: Path) -> None:
    nb = nbformat.read(path, as_version=4)
    for cell in nb.cells:
        if cell.cell_type != "code":
            continue
        for out in cell.get("outputs", []):
            assert (
                out.get("output_type") != "error"
            ), f"{path} has a stored error output: {out.get('ename')}"


def test_combined_probe_has_verdict_cell() -> None:
    nb = nbformat.read(NB_3A, as_version=4)
    src = "\n".join(c.source for c in nb.cells)
    assert "Verdict" in src
    assert "constraint, not a detection" in src


def test_lens_notebook_has_sensitivity_floor() -> None:
    nb = nbformat.read(NB_3B, as_version=4)
    src = "\n".join(c.source for c in nb.cells)
    assert "detectable_fraction" in src
    assert "sensitivity floor" in src.lower()
    assert "40000" not in src
    assert "3.6%" in src
