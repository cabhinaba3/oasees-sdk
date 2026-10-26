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


def _check(args, results):
    """Run check-metrics with Thanos mocked to return `results` ({source: value}) for every query."""
    payload = {"data": {"result": [{"metric": {"source": s}, "value": [0, str(v)]} for s, v in results.items()]}}
    with mock.patch.object(telemetry, "get_thanos_endpoint", return_value="http://thanos/api/v1/query"), \
         mock.patch("requests.get") as get:
        get.return_value.json.return_value = payload
        return CliRunner().invoke(telemetry.check_metrics, args).output


def test_threshold_on_a_dotted_node_name_filters_the_output():
    out = _check(["swarm[cpu_temperature_celsius]", "cpu_temperature_celsius[node2.example.org]>80"],
                 {"node1.example.org": 61.5, "node2.example.org": 85.0})
    assert "node2.example.org | cpu_temperature_celsius = 85.0 | > 80.0" in out
    assert "node1.example.org | cpu_temperature_celsius = 61.5" in out          # no threshold for node1


def test_threshold_that_is_not_crossed_hides_the_line():
    out = _check(["swarm[cpu_temperature_celsius]", "cpu_temperature_celsius[node-2]>90"], {"node-2": 85.0})
    assert "node-2" not in out
