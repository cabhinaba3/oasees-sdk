import subprocess
from unittest import mock

import pytest
import yaml
from click.testing import CliRunner

from oasees_sdk.cli.commands import mlops

CID0 = "Qm" + "a" * 44
CID1 = "bafy" + "a" * 55


def _client_pods(data_files):
    """Run `start-fl` with kubectl mocked and return the client pods it would have applied."""
    applied = []

    def fake_run(cmd, **kw):
        out = ""
        if cmd[:2] == ["kubectl", "apply"]:
            applied.append(open(cmd[3]).read())
        elif "containerStatuses[0].ready}" in cmd[-1]:
            out = "true"
        elif "status.phase" in cmd[-1]:
            out = "Running"
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    with mock.patch.object(mlops, "get_ipfs_api", return_value="/ip4/10.0.0.1/tcp/5001/http"), \
         mock.patch.object(mlops.subprocess, "run", fake_run):
        result = CliRunner().invoke(
            mlops.start_fl, ["--project-name", "p", "--data-files", data_files])
    assert result.exit_code == 0, result.output
    return [d for d in yaml.safe_load_all(applied[1]) if d]  # applied[0] is the server


def _env(pod, name):
    return next(e["value"] for e in pod["spec"]["containers"][0]["env"] if e["name"] == name)


def _script(pod):
    return pod["spec"]["containers"][0]["args"][0]


def test_plain_file_names_still_use_host_path():
    (pod,) = _client_pods("d.npy,t.npy,node1")
    host = {v["name"]: v["hostPath"] for v in pod["spec"]["volumes"] if "hostPath" in v}
    assert host == {"data-files": {"path": "/var/tmp/d.npy", "type": "File"},
                    "target-files": {"path": "/var/tmp/t.npy", "type": "File"}}
    assert _env(pod, "DATA_PATH") == "/var/tmp/d.npy"
    assert "ipfs --api=/ip4/${IPFS_IP}/tcp/5001/http get Qm" not in _script(pod)


def test_cids_are_downloaded_in_the_pod_and_need_no_host_path():
    (pod,) = _client_pods(f"{CID0},{CID1},node1")
    assert not [v for v in pod["spec"]["volumes"] if "hostPath" in v]
    assert _env(pod, "DATA_PATH") == "/data/data.npy"
    assert _env(pod, "TARGET_PATH") == "/data/target.npy"
    script = _script(pod)
    assert f"get {CID0} -o /data/data.npy &&" in script
    assert f"get {CID1} -o /data/target.npy &&" in script
    # the downloads happen before training starts
    assert script.index(f"get {CID0}") < script.index("_client.py")
    assert {"name": "scratch", "mountPath": "/data"} in pod["spec"]["containers"][0]["volumeMounts"]


def test_a_cid_and_a_local_file_can_be_mixed():
    (pod,) = _client_pods(f"{CID0},t.npy,node1")
    assert _env(pod, "DATA_PATH") == "/data/data.npy"
    assert _env(pod, "TARGET_PATH") == "/var/tmp/t.npy"
    assert [v["name"] for v in pod["spec"]["volumes"] if "hostPath" in v] == ["target-files"]


def test_each_client_gets_its_own_source():
    pods = _client_pods(f"{CID0},{CID1},node1:d.npy,t.npy,node2")
    assert [_env(p, "DATA_PATH") for p in pods] == ["/data/data.npy", "/var/tmp/d.npy"]


@pytest.mark.parametrize("name", ["d.npy", "iris_data.npy", "Qmshort", "bafy123", "Qm" + "a" * 43])
def test_only_real_cids_are_treated_as_cids(name):
    assert mlops.client_data_source("data", name) == (f"/var/tmp/{name}", False)
