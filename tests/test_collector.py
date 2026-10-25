import subprocess
from pathlib import Path
from unittest import mock

import yaml
from click.testing import CliRunner

from oasees_sdk.cli.commands import telemetry

DOCKERFILE = Path(__file__).parent.parent / "docker/collector/Dockerfile"


def _deploy(*extra):
    """Run `deploy-collector` with kubectl mocked; return (ConfigMap, Pod) it would have applied."""
    applied = []

    def fake_run(cmd, **kw):
        if cmd[:2] == ["kubectl", "apply"]:
            applied.append(open(cmd[3]).read())
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    with mock.patch.object(telemetry, "get_telemetry_api", return_value="http://10.0.0.1:5005"), \
         mock.patch.object(subprocess, "run", fake_run):
        result = CliRunner().invoke(telemetry.deploy_collector, [
            "-i", "0", "-s", "node1", "-se", "http://node1:9100/metrics", *extra])
    assert result.exit_code == 0, result.output
    configmap, pod = [d for d in yaml.safe_load_all(applied[0]) if d]
    return configmap, pod


def _container(pod):
    return pod["spec"]["containers"][0]


def test_default_still_installs_packages_but_with_pinned_versions():
    _, pod = _deploy()
    assert _container(pod)["image"] == "python:3.9-slim"
    script = _container(pod)["args"][0]
    assert f"pip install {telemetry.COLLECTOR_REQUIREMENTS} &&" in script
    assert script.rstrip().endswith("python /app/collector.py")


def test_prepared_image_skips_pip_install():
    _, pod = _deploy("--image", "myrepo/oasees-collector:1")
    assert _container(pod)["image"] == "myrepo/oasees-collector:1"
    assert _container(pod)["args"][0].strip() == "python /app/collector.py"


def test_the_collector_script_is_still_mounted_from_the_configmap():
    configmap, pod = _deploy("--image", "myrepo/oasees-collector:1")
    assert "import socketio" in configmap["data"]["collector.py"]
    assert _container(pod)["volumeMounts"] == [{"name": "script-volume", "mountPath": "/app"}]


def test_dockerfile_pins_the_same_versions_as_the_code():
    install = next(l for l in DOCKERFILE.read_text().splitlines() if "pip install" in l)
    assert install.endswith(telemetry.COLLECTOR_REQUIREMENTS)
