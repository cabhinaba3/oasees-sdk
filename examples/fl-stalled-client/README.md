# Federated learning with a client that stops answering

In a real edge deployment some devices go quiet in the middle of training: they crash, lose power or
lose the network. This example shows what the OASEES FL server does about it. One of three clients
hangs in its first round. The server gives up on it after the round timeout, finishes training with
the other two, and saves the model as a safetensors file.

## On one machine

```bash
pip install .                      # from the repository root
pip install -r examples/fl-stalled-client/requirements.txt
python examples/fl-stalled-client/run.py
```

The script writes the server that oasees-sdk generates to a temporary folder, starts it with a 5
second round timeout, and starts three clients: two that train and one that never answers. Expected
output:

```
Server finished in 6.4s with exit code 0, 2 of 2 rounds trained
Saved model .../example.safetensors: p0 (2, 2) = 4, p1 (3,) = 4
OK: the hung client was dropped and the other two trained both rounds.
```

The "training" is a stand-in: each client adds the mean of its data (1.0 or 3.0) to every weight.
The server averages the two answers each round, so after two rounds every weight is 4. Any other
value would mean a round was missed or the hung client was counted. The script exits with 1 and
says what went wrong if the result is not this one.

## On a K3s cluster

The same scenario with `oasees-sdk mlops start-fl`. It needs:

- a cluster with the `oasees-ipfs` service,
- the project in IPFS at `/oasees-ml-ops/projects/ml/<project>`, holding `fl_server.py` and
  `<project>_client.py`,
- an image with safetensors in it. The stock `oasees/ml-base-image` does not have it, so set
  `OASEES_ML_IMAGE` (see `docker/ml-base-image`).

```bash
export OASEES_ML_IMAGE=ccohitherewer/ml-base-image:safetensors
oasees-sdk mlops start-fl --project-name <project> \
  --data-files "<data CID>,<target CID>,<node1>:<data CID>,<target CID>,<node2>" \
  --num-rounds 2 --round-timeout 60
```

Each client downloads its data by CID, the server runs on the master node, and the trained model is
copied back into the project folder in IPFS as `<project>_<timestamp>.safetensors`. A client that
stops answering is dropped after `--round-timeout` seconds; by default the server carries on as long
as 70% of the clients (rounded down) are still connected.
