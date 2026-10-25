import ast
import subprocess
from pathlib import Path
from unittest import mock

from oasees_sdk.cli.commands import mlops
from oasees_sdk.oasees_sdk import sdk

SRC = Path(__file__).parent.parent / "src/oasees_sdk"


def _kubectl(returncode, stdout="", stderr=""):
    def run(cmd, **kw):
        if returncode:
            raise subprocess.CalledProcessError(returncode, cmd, stderr=stderr)
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
    return run


def test_there_is_one_definition():
    defs = [p for p in SRC.rglob("*.py")
            for n in ast.walk(ast.parse(p.read_text())) if isinstance(n, ast.FunctionDef) and n.name == "get_ipfs_api"]
    assert defs == [SRC / "cli/commands/mlops.py"]
    assert sdk.get_ipfs_api is mlops.get_ipfs_api


def test_returns_the_multiaddr_without_printing_the_ip(capsys):
    with mock.patch.object(mlops.subprocess, "run", _kubectl(0, "10.43.0.7\n")):
        assert mlops.get_ipfs_api() == "/ip4/10.43.0.7/tcp/5001/http"
    assert capsys.readouterr().out == ""


def test_reports_the_error_and_returns_none(capsys):
    with mock.patch.object(mlops.subprocess, "run", _kubectl(1, stderr="NotFound")):
        assert sdk.get_ipfs_api() is None
    assert "NotFound" in capsys.readouterr().err
