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


def _build_job(**kw):
    api = mock.Mock()
    deploy_pipeline.create_job(api, "Qm1", "app", **kw)
    return api.create_namespaced_job.call_args.kwargs["body"]


def test_build_job_uses_the_old_ipfs_address_by_default():
    job = _build_job()
    command = job.spec.template.spec.containers[0].args[-1]
    assert "download_ipfs.py http://ipfs-kubo-service.default.svc.cluster.local:5002 Qm1 ." in command


def test_build_job_ipfs_address_can_be_set():
    job = _build_job(ipfs_api_url="http://oasees-ipfs:5001")
    assert "download_ipfs.py http://oasees-ipfs:5001 Qm1 ." in job.spec.template.spec.containers[0].args[-1]


def test_build_job_still_runs_on_the_master_and_reports_api_errors(capsys):
    job = _build_job()
    assert job.spec.template.spec.node_selector == {"node-role.kubernetes.io/master": "true"}
    api = mock.Mock()
    api.create_namespaced_job.side_effect = deploy_pipeline.ApiException(status=409, reason="exists")
    assert deploy_pipeline.create_job(api, "Qm1", "app") == "Error for Job image-build-job-app"
    assert "exists" in capsys.readouterr().out
