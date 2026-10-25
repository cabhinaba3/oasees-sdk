import json
import subprocess
from unittest import mock

from click.testing import CliRunner

from oasees_sdk.cli.commands import telemetry


def _kubectl(returncode=0, stdout="", stderr=""):
    return lambda cmd, **kw: subprocess.CompletedProcess(cmd, returncode, stdout=stdout, stderr=stderr)


def test_missing_thanos_service_gives_a_clear_error():
    with mock.patch.object(telemetry.subprocess, "run", _kubectl(1, "", "NotFound")):
        result = CliRunner().invoke(telemetry.metrics_index, [])
    assert result.exit_code == 1
    assert "Could not find the thanos-query service" in result.output and "NotFound" in result.output


def test_thanos_url_is_built_when_the_service_exists():
    with mock.patch.object(telemetry.subprocess, "run", _kubectl(0, "10.43.0.9\n")):
        assert telemetry.get_thanos_endpoint() == "http://10.43.0.9:9090/api/v1/query"


def test_configure_agents_says_so_when_there_are_no_agent_pods(tmp_path):
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"actions_map": {}}))
    with mock.patch.object(subprocess, "run", _kubectl(0, json.dumps({"items": []}))), \
         mock.patch.object(telemetry.requests, "post") as post:
        result = CliRunner().invoke(telemetry.configure_agents, [str(cfg)])
    post.assert_not_called()
    assert "No running oasees-agent pods found" in result.output
