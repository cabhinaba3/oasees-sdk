import json
import subprocess
from types import SimpleNamespace as NS
from unittest import mock

import pytest
from click.testing import CliRunner

from oasees_sdk.cli.commands import update


@pytest.mark.parametrize("latest, current, expected", [
    ("0.10.0", "0.9.0", True),
    ("0.9.0", "0.10.0", False),
    ("1.0.0", "1.0.0", False),
    ("1.0.0", "1.1.0.dev1", False),     # a local build ahead of PyPI is not "outdated"
    ("1.0.0", "not-a-version", False),  # unparseable: never reported as newer
])
def test_is_newer(latest, current, expected):
    assert update.is_newer(latest, current) is expected


def test_helm_checks_the_requested_namespace_and_survives_odd_versions():
    seen = []

    def run(cmd, **kw):
        seen.append(cmd)
        out = ""
        if cmd[1] == "list":
            out = json.dumps([{"name": "a", "namespace": "ns1", "chart": "good-1.0.0"},
                              {"name": "b", "namespace": "ns1", "chart": "odd-banana"}])
        elif cmd[1] == "search":
            out = json.dumps([{"version": "2.0.0"}])
        return subprocess.CompletedProcess(cmd, 0, stdout=out)

    with mock.patch.object(update.subprocess, "run", run):
        outdated = update.check_helm_updates("ns1")

    assert ["helm", "list", "--namespace", "ns1", "-o", "json"] in seen
    assert [c["name"] for c in outdated] == ["a"]  # the unparseable chart is skipped, not a crash


def _pod(name="p", pull="Always", statuses=True):
    status = [NS(name="c", image="docker.io/oasees/x:latest", image_id="docker.io/oasees/x@sha256:old")]
    return NS(metadata=NS(name=name), spec=NS(containers=[NS(image_pull_policy=pull)]),
              status=NS(container_statuses=status if statuses else None))


def _kube(pods):
    api = mock.Mock()
    api.list_namespaced_pod.return_value = NS(items=pods)
    return api


def test_running_digests_lists_the_requested_namespace():
    api = _kube([_pod()])
    with mock.patch.object(update.config, "load_kube_config"), \
         mock.patch.object(update.client, "CoreV1Api", return_value=api):
        running = update.get_running_digests("ns1")
    api.list_namespaced_pod.assert_called_once_with("ns1")
    assert list(running) == ["docker.io/oasees/x"]


def test_pod_that_has_not_started_is_skipped_instead_of_crashing():
    api = _kube([_pod("pending", statuses=False), _pod("up")])
    with mock.patch.object(update.config, "load_kube_config"), \
         mock.patch.object(update.client, "CoreV1Api", return_value=api):
        running = update.get_running_digests("default")
    assert [p.metadata.name for p, _, _ in running["docker.io/oasees/x"]] == ["up"]


def test_update_deletes_pods_in_the_namespace_it_listed():
    api = _kube([_pod("old-pod")])
    pypi = mock.Mock()
    pypi.json.return_value = {"info": {"version": "1.0.0"}}
    with mock.patch.object(update, "version", return_value="1.0.0"), \
         mock.patch.object(update.requests, "get", return_value=pypi), \
         mock.patch.object(update, "check_helm_updates", return_value=[]) as helm, \
         mock.patch.object(update, "get_latest_digests", return_value={"docker.io/oasees/x": "sha256:new"}), \
         mock.patch.object(update.config, "load_kube_config"), \
         mock.patch.object(update.client, "CoreV1Api", return_value=api):
        result = CliRunner().invoke(update.update, ["--namespace", "ns1"], input="y\n")

    assert result.exit_code == 0, result.output
    helm.assert_called_once_with("ns1")
    api.list_namespaced_pod.assert_called_once_with("ns1")
    api.delete_namespaced_pod.assert_called_once_with("old-pod", "ns1")


def test_a_newer_local_sdk_is_not_told_to_upgrade():
    pypi = mock.Mock()
    pypi.json.return_value = {"info": {"version": "0.7.5"}}
    with mock.patch.object(update, "version", return_value="0.8.0.dev1"), \
         mock.patch.object(update.requests, "get", return_value=pypi), \
         mock.patch.object(update, "check_helm_updates", return_value=[]), \
         mock.patch.object(update, "get_latest_digests", return_value={}), \
         mock.patch.object(update, "get_running_digests", return_value={}):
        result = CliRunner().invoke(update.update, [])
    assert "up to date" in result.output and "newer version" not in result.output
