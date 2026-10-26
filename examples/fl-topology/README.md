# Federated learning over different network topologies

Two far-edge devices train a model with a server on a cloud node. The same FL job runs three times,
each time over a different network between the nodes, declared in a topology file and applied with
`oasees-sdk topology apply`. The script reports how long training took and checks the model that
comes back.

## Topologies

The files are in [`../topologies`](../topologies). They assume four nodes: `node0` (cloud, runs the
FL server), `node1` (near-edge gateway), and `node2` and `node3` (far-edge devices, the FL clients).

| file | far-edge to cloud | gateway to cloud |
|---|---|---|
| `lan.yaml` | no impairment | no impairment |
| `edge-cloud.yaml` | 80 ms each way, 10 Mbit/s | 20 ms each way |
| `constrained-edge.yaml` | 150 ms (±20 ms) each way, 2 Mbit/s, 2% loss | 40 ms each way, 20 Mbit/s |

Write your own the same way; node names are your Kubernetes node names. See `oasees-sdk topology`
in the main README.

## Run it

You need kubectl access to a K3s cluster, the oasees-sdk CLI, and:

- an `oasees-ipfs` service. The OASEES stack has one; otherwise `kubectl apply -f kubo.yaml` starts
  a minimal IPFS node that does not join the public network,
- an image with safetensors for the FL pods:
  `export OASEES_ML_IMAGE=ccohitherewer/ml-base-image:safetensors` (see `docker/ml-base-image`).

```bash
cd examples/fl-topology
python run.py ../topologies/lan.yaml ../topologies/edge-cloud.yaml ../topologies/constrained-edge.yaml
```

The script puts the project (the server oasees-sdk generates plus [`client.py`](client.py)) and one
dataset per client into IPFS, pulls the image on the nodes once so that download time does not
count, and then for each topology:

1. applies it and prints the measured round-trip times between all nodes,
2. runs `oasees-sdk mlops start-fl` with three rounds; each client fetches its own dataset by CID,
3. waits for the server, reads the trained model back from IPFS and checks its values.

At the end it clears the topology. It exits with 1 if a run failed or a model is wrong.

The model is about 2 MB, so bandwidth limits show. The "training" is a stand-in: each client adds
the mean of its data (1 and 3) to every weight, so after three rounds every weight must be 6.

## What we measured

On a four-node K3s cluster (x86 servers, 4 cores each, on one LAN, iLab.t testbed), 26 October 2026:

| topology | round trip, far-edge to cloud | whole FL run | time per round | model |
|---|---|---|---|---|
| lan | 0.3 ms | 10 s | 0.2 s | correct |
| edge-cloud | 160 ms | 38 s | 6.3 s | correct |
| constrained-edge | 300 ms | 430 s | about 110 s | correct |

The edge-cloud rounds are close to what the bandwidth alone predicts: about three 2 MB transfers per
round at 10 Mbit/s is 5 s. The constrained rounds are about four times slower than the 2 Mbit/s
rate would suggest. Loss over a long round trip makes TCP back off, and NetEm's jitter also reorders
packets, which TCP handles badly. That gap is the point of testing over an emulated network rather
than estimating.
