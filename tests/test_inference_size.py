import io
import sys
from unittest import mock

import numpy as np
import pytest

from oasees_sdk.oasees_sdk.mlops import util_files

pytest.importorskip("flask")  # the templates need it; the SDK itself does not

TEMPLATES = pytest.mark.parametrize(
    "template", [util_files.deploy_ml, util_files.deploy_fl], ids=["deploy_ml", "deploy_fl"])


class _Out:
    def argmax(self, dim):
        return self

    def item(self):
        return 3


class _Model:
    def eval(self):
        return self

    def load_state_dict(self, state):
        pass

    def __call__(self, image):
        return _Out(), None


def _load(template):
    """Run a template with torch/cv2 and the model stubbed. Returns (Flask test client, cv2 stub)."""
    torch, cv2 = mock.MagicMock(), mock.MagicMock()
    torch.cuda.is_available.return_value = False
    torch.load.return_value = _Model()
    cv2.imdecode.return_value = np.zeros((10, 12), np.uint8)
    cv2.resize.side_effect = lambda image, size: image
    stubs = {name: mock.MagicMock() for name in (
        "torch.optim", "torch.utils", "torch.utils.data", "torch.nn", "torch.autograd",
        "requests", "exported", "FlModel")}
    stubs.update(torch=torch, cv2=cv2)
    stubs["FlModel"].Net.return_value.to.return_value = _Model()   # deploy_fl builds its model this way
    namespace = {"__name__": "template"}
    with mock.patch.dict(sys.modules, stubs):
        exec(template, namespace)
    return namespace["app"].test_client(), cv2


def _numpy(client, shape, **kw):
    return client.post("/predict_numpy", json={"image": np.zeros(shape).tolist()}, **kw)


@TEMPLATES
def test_default_is_still_28_by_28(template):
    client, _ = _load(template)
    assert _numpy(client, (28, 28)).get_json() == {"prediction": 3}
    bad = _numpy(client, (32, 32))
    assert bad.status_code == 400 and bad.get_json()["error"] == "Invalid image shape, expected (28, 28)"


@TEMPLATES
def test_header_sets_the_size_as_height_by_width(template):
    client, _ = _load(template)
    assert _numpy(client, (32, 48), headers={"X-Image-Size": "32x48"}).get_json() == {"prediction": 3}
    assert _numpy(client, (16, 16), headers={"X-Image-Size": "16"}).get_json() == {"prediction": 3}
    assert _numpy(client, (48, 32), headers={"X-Image-Size": "32x48"}).status_code == 400


@TEMPLATES
def test_environment_variable_sets_the_default(template, monkeypatch):
    monkeypatch.setenv("IMAGE_SIZE", "64")
    client, _ = _load(template)
    assert _numpy(client, (64, 64)).get_json() == {"prediction": 3}
    # a header still wins over the environment
    assert _numpy(client, (8, 8), headers={"X-Image-Size": "8"}).get_json() == {"prediction": 3}


@TEMPLATES
def test_invalid_size_is_a_400_with_a_message(template):
    client, _ = _load(template)
    response = _numpy(client, (28, 28), headers={"X-Image-Size": "big"})
    assert response.status_code == 400 and "Invalid image size 'big'" in response.get_json()["error"]


def _upload(client, **kw):
    return client.post("/output", data={"file": (io.BytesIO(b"img"), "a.png")},
                       content_type="multipart/form-data", **kw)


@TEMPLATES
def test_uploaded_images_are_resized_to_the_requested_size(template):
    client, cv2 = _load(template)
    assert _upload(client).get_json() == {"prediction": 3}
    assert cv2.resize.call_args.args[1] == (28, 28)
    _upload(client, headers={"X-Image-Size": "32x48"})
    assert cv2.resize.call_args.args[1] == (48, 32)      # cv2 wants (width, height)


@TEMPLATES
def test_a_file_that_is_not_an_image_is_a_400_not_a_crash(template):
    client, cv2 = _load(template)
    cv2.imdecode.return_value = None          # what OpenCV returns for data it can't decode
    response = _upload(client)
    assert response.status_code == 400 and response.get_json() == {"error": "The file is not an image"}
