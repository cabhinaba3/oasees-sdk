import importlib

import pytest

from oasees_sdk.cli.commands import mlops
from test_client_data import _client_pods
from test_fl_stragglers import _start_fl

DEFAULT = "oasees/ml-base-image:latest"


@pytest.fixture
def reload_mlops(monkeypatch):
    """Reload mlops after the environment changes, then restore it for the other tests."""
    yield lambda: importlib.reload(mlops)
    monkeypatch.undo()
    importlib.reload(mlops)


def test_default_image_is_unchanged(monkeypatch, reload_mlops):
    monkeypatch.delenv("OASEES_ML_IMAGE", raising=False)
    reload_mlops()
    assert mlops.ML_IMAGE == DEFAULT
    assert f"image: {DEFAULT}" in _start_fl()
    assert _client_pods("d.npy,t.npy,node1")[0]["spec"]["containers"][0]["image"] == DEFAULT


def test_env_var_changes_the_image_of_server_and_client_pods(monkeypatch, reload_mlops):
    monkeypatch.setenv("OASEES_ML_IMAGE", "me/ml-base-image:safetensors")
    reload_mlops()
    assert "image: me/ml-base-image:safetensors" in _start_fl()
    assert _client_pods("d.npy,t.npy,node1")[0]["spec"]["containers"][0]["image"] == "me/ml-base-image:safetensors"
