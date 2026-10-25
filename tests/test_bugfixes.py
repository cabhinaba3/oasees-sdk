import json
import subprocess
from unittest import mock

from oasees_sdk.cli import ipfs_client
from oasees_sdk.cli.commands import update
from oasees_sdk.oasees_sdk import cluster_ipfs_upload


def _helm(installed, latest):
    """Fake subprocess.run: `helm list` returns one chart, `helm search` returns `latest`."""
    def run(cmd, **kw):
        out = ""
        if cmd[1] == "list":
            out = json.dumps([{"name": "app", "namespace": "ns", "chart": f"mychart-{installed}"}])
        elif cmd[1] == "search":
            out = json.dumps([{"version": latest}])
        return subprocess.CompletedProcess(cmd, 0, stdout=out)
    return run


def test_helm_update_uses_semver_not_string_order():
    # As strings "0.9.0" > "0.10.0", so the old code missed this update.
    with mock.patch.object(update.subprocess, "run", _helm("0.9.0", "0.10.0")):
        assert [c["latest"] for c in update.check_helm_updates()] == ["0.10.0"]
    # ...and "0.9.0" < "0.10.0" as strings is False the other way round: no false positive.
    with mock.patch.object(update.subprocess, "run", _helm("0.10.0", "0.9.0")):
        assert update.check_helm_updates() == []


def test_ipfs_get_returns_binary_unchanged():
    payload = bytes([0x80, 0xFF, 0x00, 0xFE])  # not valid UTF-8
    resp = mock.Mock(content=payload)
    with mock.patch.object(ipfs_client.requests, "post", return_value=resp):
        assert ipfs_client.ipfs_get("cid", "1.2.3.4") == payload


def test_ipfs_upload_accepts_bytes_and_str():
    resp = mock.Mock()
    resp.json.return_value = {"Hash": "Qm123"}
    with mock.patch.object(ipfs_client.requests, "post", return_value=resp) as post:
        assert ipfs_client.ipfs_upload(b"\x80\xff", "ip") == "Qm123"
        assert ipfs_client.ipfs_upload("text", "ip") == "Qm123"
        assert post.call_args.kwargs["files"]["file"][1] == b"text"


def test_assets_to_ipfs_closes_every_file(tmp_path):
    for name in ("a.bin", "b.bin"):
        (tmp_path / name).write_bytes(b"\x00\x01")
    opened = []
    real_open = open

    def tracking_open(*a, **kw):
        f = real_open(*a, **kw)
        opened.append(f)
        return f

    resp = mock.Mock()
    resp.iter_lines.return_value = [json.dumps({"Name": "", "Hash": "QmDir"}).encode()]
    with mock.patch("builtins.open", tracking_open), \
         mock.patch.object(cluster_ipfs_upload.requests, "post", return_value=resp):
        assert cluster_ipfs_upload.assets_to_ipfs("http://x", str(tmp_path)) == "QmDir"

    assert len(opened) == 2 and all(f.closed for f in opened)
