import subprocess
from unittest import mock

import pytest
from click.testing import CliRunner

from oasees_sdk.cli.commands import jupyter_templating, mlops
from oasees_sdk.oasees_sdk.mlops import util_files


def _start_fl(*extra, clients=3):
    """Run `start-fl` with kubectl mocked; return the server manifest it would have applied."""
    files = ":".join(f"d{i}.npy,t{i}.npy,node{i}" for i in range(clients))
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
            mlops.start_fl, ["--project-name", "p", "--data-files", files, *extra])
    assert result.exit_code == 0, result.output
    return applied[0]  # the first apply is the server


def _env(manifest, name):
    lines = manifest.splitlines()
    i = lines.index(f"      - name: {name}")
    return lines[i + 1].split('"')[1]


def test_default_min_clients_is_70_percent_rounded_down():
    # one lost client must not freeze training, so the default can't be "all of them"
    assert _env(_start_fl(clients=3), "MIN_CLIENTS") == "2"
    assert _env(_start_fl(clients=10), "MIN_CLIENTS") == "7"
    assert _env(_start_fl(clients=1), "MIN_CLIENTS") == "1"


def test_min_clients_flag_still_wins():
    assert _env(_start_fl("--min-clients", "3", clients=3), "MIN_CLIENTS") == "3"


def test_round_timeout_reaches_the_server_pod():
    default = _start_fl()
    assert _env(default, "ROUND_TIMEOUT") == "60"
    assert "--ROUND_TIMEOUT ${ROUND_TIMEOUT}" in default
    assert _env(_start_fl("--round-timeout", "900"), "ROUND_TIMEOUT") == "900"


@pytest.mark.parametrize("template", [jupyter_templating.fl_server, util_files.fl_server],
                         ids=["jupyter_templating", "util_files"])
def test_server_templates_apply_the_round_timeout(template):
    assert "'--ROUND_TIMEOUT', type=float, default=60" in template
    assert "round_timeout=ROUND_TIMEOUT" in template
