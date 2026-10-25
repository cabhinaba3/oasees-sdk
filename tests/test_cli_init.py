from unittest import mock

import pytest
from click.testing import CliRunner

from oasees_sdk.cli import cli as cli_module


def _init(monkeypatch, tmp_path, *args):
    """Run `init` with the installers mocked; return the k3s install command it built."""
    monkeypatch.setenv("HOME", str(tmp_path))
    run = mock.Mock(return_value=b"")
    with mock.patch.object(cli_module, "check_required_tools", return_value=True), \
         mock.patch.object(cli_module, "helm_add_oasees_repo"), \
         mock.patch.object(cli_module, "helm_install_oasees"), \
         mock.patch.object(cli_module.subprocess, "Popen"), \
         mock.patch.object(cli_module.subprocess, "check_output", run):
        result = CliRunner().invoke(cli_module.init, list(args))
    assert result.exit_code == 0, result.output
    return run.call_args.args[0]


def test_kubeconfig_goes_to_the_users_real_home(monkeypatch, tmp_path):
    cmd = _init(monkeypatch, tmp_path)
    assert cmd[cmd.index("--write-kubeconfig") + 1] == str(tmp_path / ".kube/config")
    assert "/home/" not in " ".join(cmd)


def test_iface_is_added_only_when_given(monkeypatch, tmp_path):
    assert "--flannel-iface" not in _init(monkeypatch, tmp_path)
    cmd = _init(monkeypatch, tmp_path, "--iface", "eno1")
    assert cmd[cmd.index("--flannel-iface") + 1] == "eno1"


def test_other_k3s_flags_are_unchanged(monkeypatch, tmp_path):
    cmd = _init(monkeypatch, tmp_path)
    assert cmd[:5] == ["sh", "-s", "-", "--write-kubeconfig-mode", "644"]
    assert any(c.startswith("user=") for c in cmd)
