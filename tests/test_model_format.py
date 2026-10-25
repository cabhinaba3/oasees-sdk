import re
import textwrap
from pathlib import Path

import numpy as np
import pytest
from safetensors.numpy import load_file, save_file

from oasees_sdk.cli.commands import jupyter_templating
from oasees_sdk.oasees_sdk.mlops import util_files

MLOPS = Path(__file__).parent.parent / "src/oasees_sdk/cli/commands/mlops.py"


def _loaders():
    """The load_fl_model source from each notebook cell in mlops.py, ready to exec."""
    src = MLOPS.read_text()
    blocks = re.findall(r"( *def load_fl_model\(model_path\):.*?return model)\n", src, re.S)
    return [textwrap.dedent(b) for b in blocks]


@pytest.mark.parametrize("template", [jupyter_templating.fl_server, util_files.fl_server])
def test_fl_server_templates_do_not_use_pickle(template):
    assert "pickle" not in template and ".pkl" not in template
    assert "save_file(" in template and "param.copy()" in template


def test_mlops_has_no_pickle_loader_left():
    assert "pickle" not in MLOPS.read_text()
    assert len(_loaders()) == 3  # one per notebook flavour


def test_parameters_round_trip_through_safetensors(tmp_path):
    # Same two expressions the server template and the loaders use.
    params = [np.random.rand(3, 4).astype(np.float32),
              np.arange(5, dtype=np.int64),
              np.random.rand(4, 3).astype(np.float32).T]  # non-contiguous
    path = tmp_path / "m.safetensors"
    save_file({f'p{i}': p.copy() for i, p in enumerate(params)}, str(path))

    tensors = load_file(str(path))
    restored = [tensors[f'p{i}'] for i in range(len(tensors))]
    assert len(restored) == 3
    for a, b in zip(params, restored):
        assert a.dtype == b.dtype and np.array_equal(a, b)


@pytest.mark.parametrize("loader", _loaders())
def test_loader_rejects_pickled_models(loader, tmp_path):
    ns = {"load_file": load_file, "model_definition": lambda: None}
    exec(loader, ns)
    with pytest.raises(ValueError, match="Re-run FL training"):
        ns["load_fl_model"](str(tmp_path / "old.pkl"))


def test_keras_loader_assigns_weights_in_order(tmp_path):
    # Only the keras-style loader (uses model.get_weights) runs without torch/tensorflow.
    loader = next(l for l in _loaders() if "get_weights" in l)

    class Weight:
        def assign(self, value):
            self.value = value

    class Model:
        def __init__(self):
            self.w = [Weight(), Weight()]
        def get_weights(self):
            return self.w

    model = Model()
    ns = {"load_file": load_file, "model_definition": lambda: model}
    exec(loader, ns)

    arrays = [np.ones((2, 2), dtype=np.float32), np.zeros(3, dtype=np.float32)]
    path = tmp_path / "m.safetensors"
    save_file({f'p{i}': a for i, a in enumerate(arrays)}, str(path))

    assert ns["load_fl_model"](str(path)) is model
    assert all(np.array_equal(w.value, a) for w, a in zip(model.w, arrays))
