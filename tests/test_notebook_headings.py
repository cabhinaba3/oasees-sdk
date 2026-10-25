import json
import subprocess
import sys
from unittest import mock

import pytest

from oasees_sdk.oasees_sdk.mlops import templating_functions as tf, util_files


def _cell(kind, source):
    cell = {"cell_type": kind, "metadata": {}, "source": source}
    if kind == "code":
        cell.update(execution_count=None, outputs=[])
    return cell


@pytest.mark.parametrize("cell, expected", [
    (_cell("markdown", ["## Imports"]), "imports"),
    (_cell("markdown", ["#  imports  "]), "imports"),
    (_cell("markdown", "### Model   Definition"), "model definition"),            # source as one string
    (_cell("markdown", ["## Execution Parameters\n", "notes under the heading"]), "execution parameters"),
    (_cell("markdown", ["plain text, not a heading"]), ""),
    (_cell("code", ["## Imports"]), ""),                                            # only markdown cells count
])
def test_cell_heading(cell, expected):
    assert tf.cell_heading(cell) == expected


def _notebook(cells):
    return json.dumps({"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": cells})


EDITED_HEADINGS = [
    _cell("markdown", ["#  execution PARAMETERS "]),
    _cell("code", ['exec_params = {"ipfs_hash": "QmData", "epochs": 50}']),
    _cell("markdown", "### imports"),
    _cell("code", ["import torch"]),
    _cell("markdown", ["## Model Definition\n", "the network"]),
    _cell("code", ["class Net: pass"]),
]


def test_modify_notebook_finds_headings_that_were_edited(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "proj").mkdir()
    (tmp_path / "proj" / "proj.ipynb").write_text(_notebook(EDITED_HEADINGS))
    tf.modify_notebook("proj")
    assert json.loads((tmp_path / "proj" / "exec_params.json").read_text())["epochs"] == 1
    assert (tmp_path / "proj" / "exported.py").read_text() == "import torch\nclass Net: pass"


def test_a_heading_as_the_last_cell_does_not_crash(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "proj").mkdir()
    cells = [_cell("markdown", ["## Imports"]), _cell("code", ["import os"]), _cell("markdown", ["## Model Definition"])]
    (tmp_path / "proj" / "proj.ipynb").write_text(_notebook(cells))
    tf.modify_notebook("proj")
    assert (tmp_path / "proj" / "exported.py").read_text() == "import os\n"


def test_fl_converter_finds_edited_headings(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "fl").mkdir()
    cells = [_cell("markdown", ["# federated learning MODEL"]), _cell("code", ["model = 1"]),
             _cell("markdown", "## Federated Learning Server"), _cell("code", ["server = 2"]),
             _cell("markdown", ["##  Federated Learning Client "]), _cell("code", ["client = 3"])]
    (tmp_path / "fl" / "fl.ipynb").write_text(_notebook(cells))
    with mock.patch.object(tf, "upload_to_ipfs"):
        tf.convert_fl_template("fl")
    assert (tmp_path / "fl" / "FlModel.py").read_text() == "model = 1"
    assert (tmp_path / "fl" / "flower_server.py").read_text() == "server = 2"
    assert (tmp_path / "fl" / "flower_client.py").read_text() == "client = 3"


def test_runtime_script_in_the_pod_finds_edited_headings(tmp_path):
    # the template is a script that is written into the project and run there, so run it
    (tmp_path / "runtime_params.py").write_text(util_files.runtime_params)
    (tmp_path / "exec_params.json").write_text(json.dumps({"ipfs_hash": ""}))
    (tmp_path / "nb.ipynb").write_text(_notebook(EDITED_HEADINGS))
    subprocess.run([sys.executable, "runtime_params.py", "nb", "3", "0.5", "QmX", "0", "1", "8", "QmSrc"],
                   cwd=tmp_path, check=True, capture_output=True)
    assert (tmp_path / "exported.py").read_text() == "import torch\nclass Net: pass"
    assert json.loads((tmp_path / "exec_params.json").read_text())["epochs"] == 3
