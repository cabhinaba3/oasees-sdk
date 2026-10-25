import json

import pytest

from oasees_sdk.oasees_sdk.mlops import templating_functions as tf


def test_reads_exec_params_literal():
    src = 'exec_params = {"ipfs_hash": "Qm1", "epochs": 3, "tags": ["a"]}\n'
    assert tf.read_exec_params(src) == {"ipfs_hash": "Qm1", "epochs": 3, "tags": ["a"]}


def test_never_runs_the_cell(tmp_path):
    marker = tmp_path / "ran"
    src = f'open({str(marker)!r}, "w").close()\nexec_params = {{"ipfs_hash": "Qm1"}}\n'
    assert tf.read_exec_params(src)["ipfs_hash"] == "Qm1"
    assert not marker.exists()


@pytest.mark.parametrize("src", [
    'exec_params = dict(ipfs_hash="Qm1")',            # a call, not a literal
    'import os\nexec_params = {"ipfs_hash": os.environ["X"]}',
    'other = {"ipfs_hash": "Qm1"}',                    # no exec_params at all
])
def test_rejects_anything_that_is_not_a_plain_literal(src, tmp_path):
    with pytest.raises(ValueError, match="plain values"):
        tf.read_exec_params(src)


def _cell(kind, source):
    cell = {"cell_type": kind, "metadata": {}, "source": source}
    if kind == "code":
        cell.update(execution_count=None, outputs=[])
    return cell


def test_modify_notebook_end_to_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "proj").mkdir()
    nb = {"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": [
        _cell("markdown", ["## Execution Parameters"]),
        _cell("code", ['exec_params = {"ipfs_hash": "QmData", "epochs": 50}']),
        _cell("markdown", ["## Imports"]),
        _cell("code", ["import torch"]),
        _cell("markdown", ["## Model Definition"]),
        _cell("code", ["class Net: pass"]),
    ]}
    (tmp_path / "proj" / "proj.ipynb").write_text(json.dumps(nb))

    assert tf.modify_notebook("proj") == "proj_exec_test.ipynb"

    # the test run is shrunk to 1 epoch, but the user's dataset hash is kept in the notebook...
    out = json.loads((tmp_path / "proj" / "proj_exec_test.ipynb").read_text())
    assert '"ipfs_hash": "QmData"' in "".join(out["cells"][1]["source"])
    assert '"epochs": 1' in "".join(out["cells"][1]["source"])
    # ...and blanked in exec_params.json
    assert json.loads((tmp_path / "proj" / "exec_params.json").read_text())["ipfs_hash"] == ""
    assert (tmp_path / "proj" / "exported.py").read_text() == "import torch\nclass Net: pass"
