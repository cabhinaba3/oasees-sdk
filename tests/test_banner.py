import subprocess
from unittest import mock

from oasees_sdk.cli.commands import display_banner as db


def test_banner_prints_without_starting_a_subprocess(capsys):
    with mock.patch.object(subprocess, "run", side_effect=AssertionError("spawned a process")):
        db.display_banner()
    out = capsys.readouterr().out
    assert "| |_| / ___ \\ ___) |" in out      # a line of the logo
    assert "\x1b" not in out                   # click drops colours when not on a terminal


def test_every_colour_placeholder_is_filled_in():
    sent = []
    with mock.patch.object(db.click, "echo", side_effect=sent.append):
        db.display_banner()
    assert "${" not in sent[0] and "\x1b[38;2;" in sent[0]
