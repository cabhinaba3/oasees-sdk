import json
from unittest import mock

import pytest
from click.testing import CliRunner

from oasees_sdk.cli import cli as cli_module

NODES = json.dumps({"items": [
    {"metadata": {"name": "cpu-node", "labels": {"kubernetes.io/hostname": "cpu-node"}}},
    {"metadata": {"name": "gpu-node", "labels": {"nvidia.com/gpu.present": "true"}}},
]})


def _run(*args, input=None):
    """Run mlops-add-node with helm and the node list mocked; return (result, helm command or None)."""
    with mock.patch.object(cli_module, "get_nodes", return_value=NODES), \
         mock.patch.object(cli_module.subprocess, "run") as run:
        result = CliRunner().invoke(cli_module.mlops_add_node, list(args), input=input)
    return result, (run.call_args.args[0] if run.called else None)


def _helm_values(cmd):
    return {cmd[i + 1].split("=")[0]: cmd[i + 1].split("=")[1] for i, c in enumerate(cmd) if c == "--set"}


def test_all_flags_need_no_prompts():
    result, cmd = _run("--node", "gpu-node", "--gpu", "--venv-path", "/data/venv")
    assert result.exit_code == 0, result.output
    assert _helm_values(cmd) == {"nodeName": "gpu-node", "mountPath": "/data/venv", "gpu": "1"}


def test_no_gpu_flag_turns_it_off_on_a_gpu_node():
    _, cmd = _run("--node", "gpu-node", "--no-gpu", "--venv-path", "/v")
    assert _helm_values(cmd)["gpu"] == "0"


def test_a_cpu_node_never_asks_about_gpu():
    result, cmd = _run("--node", "cpu-node", "--venv-path", "/v")
    assert "GPU support" not in result.output
    assert _helm_values(cmd)["gpu"] == "0"


def test_gpu_flag_on_a_node_without_one_is_an_error():
    result, cmd = _run("--node", "cpu-node", "--gpu", "--venv-path", "/v")
    assert result.exit_code != 0 and "has no GPU" in result.output and cmd is None


def test_unknown_node_lists_the_real_ones():
    result, cmd = _run("--node", "nope", "--venv-path", "/v")
    assert result.exit_code != 0 and "cpu-node, gpu-node" in result.output and cmd is None


def test_without_flags_it_still_asks_like_before():
    # choose node 2 (the GPU node), accept GPU, then type the venv path
    result, cmd = _run(input="2\ny\n/home/me/venv\n")
    assert result.exit_code == 0, result.output
    assert "Available nodes:" in result.output
    assert _helm_values(cmd) == {"nodeName": "gpu-node", "mountPath": "/home/me/venv", "gpu": "1"}


def test_flags_and_prompts_can_be_mixed():
    result, cmd = _run("--node", "cpu-node", input="/typed/venv\n")
    assert _helm_values(cmd)["mountPath"] == "/typed/venv"
