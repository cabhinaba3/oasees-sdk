import ast

import pytest

from oasees_sdk.cli.commands import jupyter_templating
from oasees_sdk.oasees_sdk.mlops import util_files

TEMPLATES = pytest.mark.parametrize(
    "template", [jupyter_templating.fl_server, util_files.fl_server], ids=["jupyter_templating", "util_files"])


def _aggregate_fit(template):
    return template[template.index("def aggregate_fit"):template.index("def aggregate_evaluate")]


@TEMPLATES
def test_template_is_valid_python(template):
    ast.parse(template)


@TEMPLATES
def test_the_model_is_not_saved_from_inside_aggregate_fit(template):
    # An exception raised there leaves the gRPC threads running, so the process hangs.
    assert "_save_parameters(" not in _aggregate_fit(template)


@TEMPLATES
def test_every_good_round_is_kept_not_only_the_last(template):
    body = _aggregate_fit(template)
    assert "NUM_ROUNDS and parameters" not in body
    assert "if parameters is not None:" in body and "self.final_parameters = parameters" in body


@TEMPLATES
def test_model_is_saved_after_the_server_stops_and_missing_results_fail(template):
    main = template[template.index("def main"):]
    assert main.index("start_server(") < main.index("sys.exit(") < main.index("_save_parameters(strategy.final_parameters)")
    assert "import sys" in template
