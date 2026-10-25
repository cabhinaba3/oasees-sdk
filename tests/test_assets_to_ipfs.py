import json
import os
from unittest import mock

import pytest

from oasees_sdk.oasees_sdk import cluster_ipfs_upload as up


def _upload(directory):
    """Run assets_to_ipfs with IPFS mocked. Returns (result, the multipart body that would have been sent)."""
    sent = {}

    def post(url, headers, data, stream):
        sent["url"] = url
        sent["body"] = data.read()          # what requests would stream to the server
        resp = mock.Mock()
        resp.iter_lines.return_value = [json.dumps({"Name": "", "Hash": "QmRoot"}).encode()]
        return resp

    with mock.patch.object(up.requests, "post", post):
        result = up.assets_to_ipfs("http://ipfs:5001", str(directory))
    return result, sent["body"], sent["url"]


def test_subdirectories_are_uploaded_with_their_paths(tmp_path):
    (tmp_path / "top.txt").write_bytes(b"TOP")
    (tmp_path / "sub" / "deep").mkdir(parents=True)
    (tmp_path / "sub" / "a.bin").write_bytes(b"\x00\x01AAA")
    (tmp_path / "sub" / "deep" / "b.txt").write_bytes(b"BEE")
    result, body, url = _upload(tmp_path)
    assert result == "QmRoot" and url == "http://ipfs:5001/api/v0/add?wrap-with-directory=true"
    for name, content in (("top.txt", b"TOP"), ("sub/a.bin", b"\x00\x01AAA"), ("sub/deep/b.txt", b"BEE")):
        assert f'filename="{name}"'.encode() in body and content in body


def test_a_flat_directory_is_sent_as_before(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"A")
    (tmp_path / "b.txt").write_bytes(b"B")
    _, body, _ = _upload(tmp_path)
    assert b'filename="a.txt"' in body and b'filename="b.txt"' in body and b"/" not in b"".join(
        line for line in body.split(b"\r\n") if line.startswith(b"Content-Disposition"))


def test_empty_files_are_uploaded(tmp_path):
    (tmp_path / "empty.txt").write_bytes(b"")
    (tmp_path / "full.txt").write_bytes(b"data")
    _, body, _ = _upload(tmp_path)
    assert b'filename="empty.txt"' in body and b"data" in body


def test_an_empty_directory_does_not_crash(tmp_path):
    empty = tmp_path / "nothing_here"
    empty.mkdir()
    assert _upload(empty)[0] == "QmRoot"


def test_large_files_are_sent_whole(tmp_path):
    payload = os.urandom(3 * 1024 * 1024 + 17)
    (tmp_path / "big.bin").write_bytes(payload)
    _, body, _ = _upload(tmp_path)
    assert payload in body


def _open_fds():
    return len(os.listdir("/dev/fd"))


def test_a_directory_with_more_files_than_the_open_file_limit(tmp_path):
    resource = pytest.importorskip("resource")
    for i in range(400):
        d = tmp_path / f"d{i % 20}"
        d.mkdir(exist_ok=True)
        (d / f"f{i}.txt").write_bytes(b"x" * 10)

    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    before = _open_fds()
    resource.setrlimit(resource.RLIMIT_NOFILE, (min(128, hard), hard))
    try:
        result, body, _ = _upload(tmp_path)           # opening 400 files at once would fail here
    finally:
        resource.setrlimit(resource.RLIMIT_NOFILE, (soft, hard))
    assert result == "QmRoot" and body.count(b"Content-Disposition") == 400
    assert _open_fds() == before                      # and none are left open


def test_files_are_closed_when_the_upload_fails(tmp_path):
    (tmp_path / "a.txt").write_bytes(b"A" * 100)
    before = _open_fds()

    def post(url, headers, data, stream):
        data.read(10)                                  # starts reading, which opens the file
        raise ConnectionError("server went away")

    with mock.patch.object(up.requests, "post", post), pytest.raises(ConnectionError):
        up.assets_to_ipfs("http://ipfs:5001", str(tmp_path))
    assert _open_fds() == before
