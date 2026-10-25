from unittest import mock

import pytest

from oasees_sdk.oasees_sdk.mlops import env_vars, templating_functions as tf


@pytest.fixture(autouse=True)
def clean(monkeypatch, tmp_path):
    """Run in an empty directory with neither variable set, and restore the singleton afterwards."""
    monkeypatch.chdir(tmp_path)
    for name in ("IPFS_ENDPOINT", "INDEXER_ENDPOINT"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(env_vars, "Envs", env_vars.ENVs())
    monkeypatch.setattr(tf, "Envs", env_vars.Envs)
    return tmp_path


def test_empty_when_nothing_is_configured():
    assert env_vars.Envs.ipfs_endpoint == "" and env_vars.Envs.indexer_endpoint == ""


def test_read_from_environment_variables(monkeypatch):
    monkeypatch.setenv("IPFS_ENDPOINT", "http://1.2.3.4:5001/api/v0")
    monkeypatch.setenv("INDEXER_ENDPOINT", "http://1.2.3.4:31007")
    assert env_vars.Envs.ipfs_endpoint == "http://1.2.3.4:5001/api/v0"
    assert env_vars.Envs.indexer_endpoint == "http://1.2.3.4:31007"


def test_read_from_a_dotenv_file_in_the_working_directory(clean):
    (clean / ".env").write_text("IPFS_ENDPOINT=http://from-dotenv:5001/api/v0\n")
    assert env_vars.Envs.ipfs_endpoint == "http://from-dotenv:5001/api/v0"


def test_a_real_environment_variable_beats_the_dotenv_file(clean, monkeypatch):
    (clean / ".env").write_text("IPFS_ENDPOINT=http://from-dotenv\n")
    monkeypatch.setenv("IPFS_ENDPOINT", "http://from-env")
    assert env_vars.Envs.ipfs_endpoint == "http://from-env"


def test_set_envs_still_wins(monkeypatch):
    monkeypatch.setenv("IPFS_ENDPOINT", "http://from-env")
    env_vars.Envs.set_envs("http://explicit", "http://explicit-indexer")
    assert env_vars.Envs.ipfs_endpoint == "http://explicit"
    assert env_vars.Envs.indexer_endpoint == "http://explicit-indexer"


def test_upload_without_an_endpoint_says_which_variable_to_set(clean):
    (clean / "proj").mkdir()
    with mock.patch.object(tf.requests, "post") as post:
        with pytest.raises(RuntimeError, match="IPFS_ENDPOINT"):
            tf.upload_to_ipfs(str(clean / "proj"), env_vars.Envs.ipfs_endpoint, "ML")
        with pytest.raises(RuntimeError, match="INDEXER_ENDPOINT"):
            tf.upload_to_indexer("proj", "Qm1", "ML")
    post.assert_not_called()


def test_upload_uses_the_endpoint_it_is_given(clean):
    folder = clean / "proj"; folder.mkdir(); (folder / "a.txt").write_text("x")
    resp = mock.Mock(status_code=200)
    resp.iter_lines.return_value = [b'{"Name": "", "Hash": "QmFolder"}']
    env_vars.Envs.set_envs("http://unused", "http://indexer")
    with mock.patch.object(tf.requests, "post", return_value=resp) as post, \
         mock.patch.object(tf, "upload_to_indexer") as indexer:
        assert tf.upload_to_ipfs(str(folder), "http://given:5001/api/v0", "ML") == "QmFolder"
    assert post.call_args.args[0].startswith("http://given:5001/api/v0/add")
    indexer.assert_called_once_with("proj", "QmFolder", "ML")
