# Telemetry over different network topologies

Three edge nodes report sensor readings to the OASEES telemetry API on a cloud node. Each edge node
runs a small sensor and a collector deployed with `oasees-sdk telemetry deploy-collector`. The
script runs the same setup over three networks, declared in topology files and applied with
`oasees-sdk topology apply`, and reports how long each reading took to be acknowledged and whether
it reached Prometheus.

## Topologies

The same files as the FL example, in [`../topologies`](../topologies): `node0` is the cloud node
(telemetry API and Prometheus), `node1` a near-edge gateway, `node2` and `node3` far-edge devices.
All three edge nodes run a sensor and a collector.

| file | far-edge to cloud | gateway to cloud |
|---|---|---|
| `lan.yaml` | no impairment | no impairment |
| `edge-cloud.yaml` | 80 ms each way, 10 Mbit/s | 20 ms each way |
| `constrained-edge.yaml` | 150 ms (±20 ms) each way, 2 Mbit/s, 2% loss | 40 ms each way, 20 Mbit/s |

## Run it

You need kubectl access to a K3s cluster, the oasees-sdk CLI, and the telemetry services the SDK
talks to. The OASEES stack has them; otherwise `kubectl apply -f stack.yaml` starts the OASEES
telemetry API and Prometheus behind a `thanos-query` service (the SDK only uses the query endpoint,
which both serve).

```bash
cd examples/telemetry-topology
python run.py ../topologies/lan.yaml ../topologies/edge-cloud.yaml ../topologies/constrained-edge.yaml
```

For each topology the script:

1. applies it and prints the measured round-trip times between all nodes,
2. starts a sensor on each edge node with new readings, including a `reading` number that changes
   with every topology, so a value in Prometheus can only have come from this run,
3. deploys a collector per edge node with `oasees-sdk telemetry deploy-collector`, using the
   prebuilt `ccohitherewer/oasees-collector:1.0` image (`OASEES_COLLECTOR_IMAGE` to change it),
4. after 40 seconds, reads the collectors' logs for the time from each push to its acknowledgement,
   and checks that Prometheus holds every node's readings.

It exits with 1 if a collector pushed nothing or a value is wrong. Afterwards, on a cluster node,
the SDK's own queries show the same data:

```bash
oasees-sdk telemetry metrics-list -i factory
oasees-sdk telemetry check-metrics 'factory[cpu_temperature_celsius]' 'cpu_temperature_celsius[node3]>70'
```

These two need to run on a cluster node because `thanos-query` is a cluster-internal address.

## What we measured

On a four-node K3s cluster (x86 servers, 4 cores each, on one LAN, iLab.t testbed), 26 October 2026,
collectors scraping every second for 40 seconds:

| topology | node | round trip to cloud | median push to ack | pushes in 40 s | values in Prometheus |
|---|---|---|---|---|---|
| lan | all three | 0.3 ms | 7 ms | 41 to 42 | correct |
| edge-cloud | node1 (gateway) | 40 ms | 102 ms | 34 | correct |
| edge-cloud | node2, node3 | 160 ms | 343 ms | 22 | correct |
| constrained-edge | node1 (gateway) | 80 ms | 182 ms | 29 | correct |
| constrained-edge | node2, node3 | 300 ms | about 650 ms | 3 to 7 | correct |

An acknowledgement takes a little over two round trips. The collector image does not include the
`websocket-client` package, so Socket.IO falls back to HTTP long-polling, which costs extra round
trips per push. (The collector behaved the same way before, when it installed its packages at start
up.) On the constrained link the far-edge collectors got only a handful of readings through in 40
seconds. Every reading that arrived was correct, but far fewer arrived, which a deployment with
slow uplinks would need to plan for.
