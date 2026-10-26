"""Federated learning over different network topologies.

For each topology file: apply it with `oasees-sdk topology apply`, show the measured round-trip
times, run `oasees-sdk mlops start-fl` with the two far-edge nodes as clients (each with its own
dataset, fetched from IPFS by CID), and report how long training took. The trained model is read
back from IPFS and checked.

    python run.py ../topologies/lan.yaml ../topologies/edge-cloud.yaml ../topologies/constrained-edge.yaml

Needs kubectl access to the cluster, the oasees-sdk CLI, an `oasees-ipfs` service (kubo.yaml has a
minimal one) and OASEES_ML_IMAGE set to an image with safetensors.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile
import time

import numpy as np
from safetensors.numpy import load

from oasees_sdk.cli.commands.jupyter_templating import fl_server

HERE = os.path.dirname(os.path.abspath(__file__))
MFS = "/oasees-ml-ops/projects/ml"


def sh(*cmd, input=None, check=True):
    result = subprocess.run(cmd, input=input, capture_output=True)
    if check and result.returncode != 0:
        sys.exit(f"Failed: {' '.join(cmd)}\n{result.stderr.decode().strip()}")
    return result.stdout


def kubectl(*args, **kw):
    return sh("kubectl", *args, **kw).decode()


def ipfs_pod():
    selector = json.loads(kubectl("get", "svc", "oasees-ipfs", "-o", "jsonpath={.spec.selector}"))
    labels = ",".join(f"{k}={v}" for k, v in selector.items())
    return kubectl("get", "pods", "-l", labels, "-o", "jsonpath={.items[0].metadata.name}").strip()


def ipfs(pod, *args, **kw):
    return sh("kubectl", "exec", "-i", pod, "--", "ipfs", *args, **kw)


def upload(pod, project, clients):
    """Put the project in MFS and one dataset per client in IPFS. Returns {node: (data cid, target cid)}."""
    work = tempfile.mkdtemp(prefix="oasees-fl-topology-")
    os.makedirs(os.path.join(work, project))
    with open(os.path.join(work, project, "fl_server.py"), "w") as f:
        f.write(fl_server)
    with open(os.path.join(HERE, "client.py")) as src, open(os.path.join(work, project, f"{project}_client.py"), "w") as dst:
        dst.write(src.read())
    kubectl("exec", pod, "--", "rm", "-rf", "/tmp/oasees-example")
    kubectl("exec", pod, "--", "mkdir", "-p", "/tmp/oasees-example")
    kubectl("cp", os.path.join(work, project), f"{pod}:/tmp/oasees-example/{project}")
    cid = ipfs(pod, "add", "-Q", "-r", f"/tmp/oasees-example/{project}").decode().strip()
    ipfs(pod, "files", "mkdir", "-p", MFS)
    ipfs(pod, "files", "rm", "-r", f"{MFS}/{project}", check=False)
    ipfs(pod, "files", "cp", f"/ipfs/{cid}", f"{MFS}/{project}")

    cids = {}
    for node, mean in clients.items():
        for kind, array in (("data", np.full((64, 8), mean, np.float32)), ("target", np.zeros(64, np.int64))):
            path = os.path.join(work, f"{kind}-{node}.npy")
            np.save(path, array)
            kubectl("cp", path, f"{pod}:/tmp/oasees-example/{kind}-{node}.npy")
        cids[node] = tuple(ipfs(pod, "add", "-Q", f"/tmp/oasees-example/{kind}-{node}.npy").decode().strip()
                           for kind in ("data", "target"))
    return cids


def prepull(image, nodes):
    """Pull the ML image on every node first, so download time doesn't count as training time."""
    for node in nodes:
        kubectl("delete", "pod", f"prepull-{node}", "--ignore-not-found")
        kubectl("run", f"prepull-{node}", f"--image={image}", "--restart=Never",
                f'--overrides={{"spec":{{"nodeName":"{node}"}}}}', "--command", "--", "true")
    for node in nodes:
        for _ in range(180):
            if kubectl("get", "pod", f"prepull-{node}", "-o", "jsonpath={.status.phase}") in ("Succeeded", "Failed"):
                break
            time.sleep(5)
        kubectl("delete", "pod", f"prepull-{node}", "--ignore-not-found")


def wait_for_server(project, timeout):
    deadline = time.time() + timeout
    while time.time() < deadline:
        pods = json.loads(kubectl("get", "pods", "-l", f"component=server,project={project}", "-o", "json"))["items"]
        if pods and pods[0]["status"].get("phase") in ("Succeeded", "Failed"):
            return pods[0]
        time.sleep(5)
    sys.exit(f"The FL server did not finish within {timeout}s")


def seconds(timestamp):
    return datetime.datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%SZ").timestamp()


def round_times(project):
    """Seconds between successive rounds, from the FIT_START times the clients print."""
    starts = []
    for name in kubectl("get", "pods", "-l", f"component=client,project={project}", "-o", "name").split():
        starts.append([float(l.split()[1]) for l in kubectl("logs", name).splitlines() if l.startswith("FIT_START")])
    per_round = [min(s[r] for s in starts if len(s) > r) for r in range(max(map(len, starts), default=0))]
    return [b - a for a, b in zip(per_round, per_round[1:])]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("topologies", nargs="+")
    parser.add_argument("--project", default="fltopology")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--server-node", default="node0")
    parser.add_argument("--clients", default="node2,node3", help="client nodes; each gets a dataset with its own mean")
    args = parser.parse_args()

    image = os.environ.get("OASEES_ML_IMAGE")
    if not image:
        sys.exit("Set OASEES_ML_IMAGE to an image with safetensors, e.g. ccohitherewer/ml-base-image:safetensors")
    clients = {node: float(i * 2 + 1) for i, node in enumerate(args.clients.split(","))}   # means 1, 3, 5, ...
    expected = args.rounds * sum(clients.values()) / len(clients)

    pod = ipfs_pod()
    cids = upload(pod, args.project, clients)
    data_files = ":".join(f"{d},{t},{node}" for node, (d, t) in cids.items())
    print(f"Project {args.project} and {len(cids)} datasets are in IPFS. Pulling {image} on the nodes...")
    prepull(image, [args.server_node] + list(clients))

    results = []
    for path in args.topologies:
        name = os.path.splitext(os.path.basename(path))[0]
        print(f"\n=== {name} ===")
        sh("oasees-sdk", "topology", "apply", "-f", path)
        print(sh("oasees-sdk", "topology", "measure").decode().rstrip())
        kubectl("delete", "pods,services", "-l", f"project={args.project}", "--wait=true")

        sh("oasees-sdk", "mlops", "start-fl", "--project-name", args.project, "--data-files", data_files,
           "--num-rounds", str(args.rounds), "--min-clients", str(len(clients)), "--round-timeout", "300")
        server = wait_for_server(args.project, timeout=1800)
        state = server["status"]["containerStatuses"][0]["state"].get("terminated", {})
        total = seconds(state["finishedAt"]) - seconds(state["startedAt"]) if state else float("nan")
        rounds = round_times(args.project)

        models = sorted(l for l in ipfs(pod, "files", "ls", f"{MFS}/{args.project}").decode().split()
                        if l.endswith(".safetensors"))
        weights = load(ipfs(pod, "files", "read", f"{MFS}/{args.project}/{models[-1]}")) if models else {}
        correct = bool(weights) and all(np.allclose(w, expected) for w in weights.values())
        print(f"server {server['status']['phase']} in {total:.0f}s; time between rounds: "
              + ", ".join(f"{r:.1f}s" for r in rounds) + f"; model {'OK' if correct else 'WRONG'} ({models[-1] if models else 'none'})")
        results.append((name, server["status"]["phase"], total, rounds, correct))
        kubectl("delete", "pods,services", "-l", f"project={args.project}", "--wait=false")

    sh("oasees-sdk", "topology", "clear")
    print("\ntopology            server     total   time between rounds    model")
    for name, phase, total, rounds, correct in results:
        print(f"{name:<19} {phase:<10} {total:>4.0f}s   {', '.join(f'{r:.1f}s' for r in rounds):<20}  {'OK' if correct else 'WRONG'}")
    if not all(phase == "Succeeded" and correct for _, phase, _, _, correct in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
