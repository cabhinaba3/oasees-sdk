"""Telemetry over different network topologies.

Every edge node gets a small "sensor" (a JSON endpoint with that node's readings) and a collector
deployed with `oasees-sdk telemetry deploy-collector`. The collectors push to the telemetry API on
the cloud node. For each topology file this script applies it with `oasees-sdk topology apply`,
reports how long each push took to be acknowledged, and checks that every node's readings reached
Prometheus with the right values.

    python run.py ../topologies/lan.yaml ../topologies/edge-cloud.yaml ../topologies/constrained-edge.yaml

Needs kubectl access, the oasees-sdk CLI and the telemetry services (stack.yaml has minimal ones).
"""
import argparse
import datetime
import json
import os
import statistics
import subprocess
import sys
import time
import urllib.parse

INDEX = "factory"
COLLECTOR_IMAGE = os.environ.get("OASEES_COLLECTOR_IMAGE", "ccohitherewer/oasees-collector:1.0")


def sh(*cmd, input=None, check=True):
    result = subprocess.run(cmd, input=input, capture_output=True, text=True)
    if check and result.returncode != 0:
        sys.exit(f"Failed: {' '.join(cmd)}\n{result.stderr.strip()}")
    return result.stdout


def readings(i, run):
    # `reading` changes with every topology, so a value in Prometheus can only come from this run
    return {"cpu_temperature_celsius": 55.0 + 10 * i, "vibration_mm_s": round(1.5 + 0.5 * i, 2), "reading": run}


def deploy_sensors(nodes, run):
    """(Re)start one sensor per node, serving readings(i, run)."""
    sh("kubectl", "delete", "pod", *[f"sensor-{n}" for n in nodes], "--ignore-not-found", "--wait=true")
    docs = []
    for i, node in enumerate(nodes):
        docs += [
            {"apiVersion": "v1", "kind": "ConfigMap", "metadata": {"name": f"sensor-{node}"},
             "data": {"metrics.json": json.dumps(readings(i, run))}},
            {"apiVersion": "v1", "kind": "Pod",
             "metadata": {"name": f"sensor-{node}", "labels": {"app": f"sensor-{node}"}},
             "spec": {"nodeName": node, "containers": [{
                 "name": "http", "image": "python:3.9-slim",
                 "command": ["python", "-m", "http.server", "8000", "-d", "/data"],
                 "volumeMounts": [{"name": "data", "mountPath": "/data"}]}],
                 "volumes": [{"name": "data", "configMap": {"name": f"sensor-{node}"}}]}},
            {"apiVersion": "v1", "kind": "Service", "metadata": {"name": f"sensor-{node}"},
             "spec": {"selector": {"app": f"sensor-{node}"}, "ports": [{"port": 8000}]}}]
    sh("kubectl", "apply", "-f", "-", input=json.dumps({"apiVersion": "v1", "kind": "List", "items": docs}))
    sh("kubectl", "wait", "--for=condition=Ready", *[f"pod/sensor-{n}" for n in nodes], "--timeout=300s")


def collector_pods():
    pods = json.loads(sh("kubectl", "get", "pods", "-l", "app=oasees-collector", "-o", "json"))["items"]
    return {p["metadata"]["labels"]["source"]: p["metadata"]["name"] for p in pods}


def remove_collectors():
    for pod in collector_pods().values():
        sh("oasees-sdk", "telemetry", "delete-collector", pod, check=False)
    for _ in range(60):
        if not collector_pods():
            return
        time.sleep(2)


def ack_latencies(pod):
    """Milliseconds from each 'Pushing data' line to the 'Success' line after it."""
    def ts(line):
        stamp = line.split(" ", 1)[0].rstrip("Z")
        return datetime.datetime.fromisoformat(stamp[:26]).timestamp()
    pushed, latencies = None, []
    for line in sh("kubectl", "logs", "--timestamps", pod).splitlines():
        if " Pushing data: " in line:
            pushed = ts(line)
        elif " Success: " in line and pushed is not None:
            latencies.append((ts(line) - pushed) * 1000)
            pushed = None
    return latencies


def prometheus(query):
    url = "http://localhost:9090/api/v1/query?query=" + urllib.parse.quote(query)
    out = sh("kubectl", "exec", "prometheus", "--", "wget", "-qO-", url)
    return {r["metric"].get("source"): float(r["value"][1]) for r in json.loads(out)["data"]["result"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("topologies", nargs="+")
    parser.add_argument("--edge-nodes", default="node1,node2,node3")
    parser.add_argument("--seconds", type=int, default=40, help="how long the collectors run per topology")
    args = parser.parse_args()
    nodes = args.edge_nodes.split(",")

    results = []
    for run, path in enumerate(args.topologies, start=1):
        name = os.path.splitext(os.path.basename(path))[0]
        print(f"\n=== {name} ===")
        remove_collectors()
        deploy_sensors(nodes, run)
        sh("oasees-sdk", "topology", "apply", "-f", path)
        print(sh("oasees-sdk", "topology", "measure").rstrip())

        for node in nodes:
            sh("oasees-sdk", "telemetry", "deploy-collector", "-i", INDEX, "-s", node,
               "-se", f"http://sensor-{node}.default.svc.cluster.local:8000/metrics.json", "--image", COLLECTOR_IMAGE)
        time.sleep(args.seconds)

        pods = collector_pods()
        seen = {m: prometheus(f'oasees_{m}{{metric_index="{INDEX}"}}')
                for m in ("cpu_temperature_celsius", "vibration_mm_s", "reading")}
        for i, node in enumerate(nodes):
            lat = ack_latencies(pods[node]) if node in pods else []
            expected = readings(i, run)
            correct = all(seen[m].get(node) == v for m, v in expected.items())
            median = statistics.median(lat) if lat else float("nan")
            p95 = sorted(lat)[int(0.95 * (len(lat) - 1))] if lat else float("nan")
            print(f"{node}: {len(lat)} pushes acknowledged, median {median:.0f} ms, p95 {p95:.0f} ms; "
                  f"in Prometheus: " + ", ".join(f"{m} {seen[m].get(node)}" for m in expected) + " "
                  f"({'OK' if correct else 'WRONG'})")
            results.append((name, node, len(lat), median, p95, correct))

    remove_collectors()
    sh("oasees-sdk", "topology", "clear")
    print("\ntopology            node    pushes   median ack   p95 ack   values")
    for name, node, n, median, p95, correct in results:
        print(f"{name:<19} {node:<7} {n:>6}   {median:>7.0f} ms  {p95:>5.0f} ms   {'OK' if correct else 'WRONG'}")
    print("\nOn a cluster node you can now query the same data with the SDK, e.g.\n"
          f"  oasees-sdk telemetry metrics-list -i {INDEX}\n"
          f"  oasees-sdk telemetry check-metrics '{INDEX}[cpu_temperature_celsius]' 'cpu_temperature_celsius[node3]>70'")
    if not all(r[5] and r[2] > 0 for r in results):
        sys.exit(1)


if __name__ == "__main__":
    main()
