from unittest import mock

from oasees_sdk.oasees_sdk.mlops import templating_functions as tf

PIPREQS = ["numpy==1.26.4\n", "torch>=2.1.0\n", "opencv_python==4.8.0\n", "requests\n", "\n"]


def test_versions_are_dropped_by_default():
    assert tf.clean_requirements(PIPREQS) == ["numpy", "torch", "requests", ""]


def test_pins_can_be_kept():
    assert tf.clean_requirements(PIPREQS, keep_pins=True) == ["numpy==1.26.4", "torch>=2.1.0", "requests", ""]


def test_opencv_python_is_left_out_either_way():
    assert "opencv_python" not in " ".join(tf.clean_requirements(["opencv_python==4.8\n"], keep_pins=True))
    assert tf.clean_requirements(["opencv_python==4.8\n"]) == []
    assert tf.clean_requirements(["opencv_python_headless==4.8\n"], keep_pins=True) == ["opencv_python_headless==4.8"]


def _convert(tmp_path, monkeypatch, keep_pins, write_requirements=True):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "proj").mkdir()
    req = tmp_path / "proj" / "requirements.txt"

    def run(cmd, **kw):
        if cmd[0] == "pipreqs" and write_requirements:
            req.write_text("numpy==1.26.4\n")
        return mock.Mock(stdout="", stderr="")

    with mock.patch.object(tf, "modify_notebook", return_value="proj_exec_test.ipynb"), \
         mock.patch.object(tf.subprocess, "run", run):
        tf.convert_to_pipeline("proj", keep_pins=keep_pins)
    return req


def test_convert_writes_requirements_without_pins_by_default(tmp_path, monkeypatch):
    assert _convert(tmp_path, monkeypatch, keep_pins=False).read_text() == "numpy\n"


def test_convert_can_keep_pins(tmp_path, monkeypatch):
    assert _convert(tmp_path, monkeypatch, keep_pins=True).read_text() == "numpy==1.26.4\n"


def test_missing_pipreqs_is_reported_instead_of_crashing(tmp_path, monkeypatch, capsys):
    req = _convert(tmp_path, monkeypatch, keep_pins=False, write_requirements=False)
    assert not req.exists()
    assert "pipreqs did not create requirements.txt" in capsys.readouterr().out
