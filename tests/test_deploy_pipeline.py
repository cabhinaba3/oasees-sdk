from unittest import mock

from oasees_sdk.oasees_sdk import deploy_pipeline


def _load_job():
    api = mock.Mock()
    msg = deploy_pipeline.create_load_job(
        "http://ipfs:5001", api, "Qm1", "app.tar", "worker-1", "alice")
    return msg, api.create_namespaced_job.call_args.kwargs["body"]


def test_image_is_loaded_on_the_worker_that_will_run_the_app():
    # The job mounts the containerd socket of the node it runs on, so it has to run
    # on the target worker. On the master, the worker never gets the image.
    msg, job = _load_job()
    pod = job.spec.template.spec
    assert pod.node_selector == {"kubernetes.io/hostname": "worker-1"}
    assert msg == "Job image-loading-job-app.tar created"


def test_job_still_gets_the_worker_name_and_template_path():
    _, job = _load_job()
    pod = job.spec.template.spec
    env = {e.name: e.value for e in pod.containers[0].env}
    assert env["NODE_NAME"] == "worker-1"
    paths = [v.host_path.path for v in pod.volumes]
    assert "/home/alice/.oasees_sdk/template.yaml" in paths
