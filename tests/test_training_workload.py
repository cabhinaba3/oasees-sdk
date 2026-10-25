from unittest import mock

import pytest

from oasees_sdk.oasees_sdk import training_workload as tw


@pytest.fixture
def deploy(tmp_path, monkeypatch):
    """Call deploy_workload with IPFS and Kubernetes mocked; return (created objects, load_kube_config mock)."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "exp_1.zip").write_bytes(b"zip")
    resp = mock.Mock()
    resp.json.return_value = {"Hash": "QmHash"}
    created = []

    def run(node_name=None, **kw):
        with mock.patch.object(tw.requests, "post", return_value=resp), \
             mock.patch.object(tw.config, "load_kube_config") as load, \
             mock.patch.object(tw.client, "ApiClient"), \
             mock.patch.object(tw.client, "CustomObjectsApi"), \
             mock.patch.object(tw.utils, "create_from_dict", lambda c, obj: created.append(obj)):
            tw.deploy_workload("exp_1", "http://ipfs/api/v0/add", node_name, **kw)
        return created, load

    return run, tmp_path


def _pod_spec(created):
    (dep,) = [o for o in created if o["kind"] == "Deployment"]
    return dep["spec"]["template"]["spec"]


def test_node_is_a_selector_not_a_hard_node_name(deploy):
    run, _ = deploy
    spec = _pod_spec(run("worker-1")[0])
    assert spec["nodeSelector"] == {"kubernetes.io/hostname": "worker-1"}
    assert "nodeName" not in spec


def test_without_a_node_the_scheduler_chooses(deploy):
    run, _ = deploy
    spec = _pod_spec(run()[0])
    assert "nodeSelector" not in spec and "nodeName" not in spec


def test_the_rest_of_the_deployment_is_unchanged(deploy):
    run, _ = deploy
    created, _ = run("worker-1")
    (dep,) = [o for o in created if o["kind"] == "Deployment"]
    assert dep["metadata"]["name"] == "training-pod-exp-1"
    assert dep["spec"]["replicas"] == 1
    assert dep["spec"]["template"]["spec"]["containers"][0]["env"] == [{"name": "cid", "value": "QmHash"}]


def test_kubeconfig_uses_the_standard_locations(deploy):
    run, _ = deploy
    _, load = run("worker-1")
    load.assert_called_once_with(None)  # KUBECONFIG or ~/.kube/config


def test_a_config_file_next_to_the_caller_still_wins(deploy):
    run, tmp_path = deploy
    (tmp_path / "config").write_text("apiVersion: v1\n")
    _, load = run("worker-1")
    load.assert_called_once_with("./config")
