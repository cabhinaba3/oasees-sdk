"""Federated learning with a client that stops answering, on one machine.

Runs the FL server that oasees-sdk generates, plus three clients: two that train and one that hangs
forever in its first round. The server should drop the hung client after the round timeout, finish
both rounds with the other two, and save the model as safetensors.

    python run.py

Exit code 0 means everything happened as described; anything else prints what went wrong.
"""
import os
import socket
import subprocess
import sys
import tempfile
import time

import numpy as np
from safetensors.numpy import load_file

from oasees_sdk.cli.commands.jupyter_templating import fl_server

ROUNDS, TIMEOUT, PORT = 2, 5, 9999   # the generated server always listens on 9999

CLIENT = '''
import sys, time, numpy as np, flwr as fl

data_mean, hang = float(sys.argv[1]), sys.argv[2] == "hang"

class Client(fl.client.NumPyClient):
    def get_parameters(self, config):
        return [np.zeros((2, 2), np.float32), np.zeros(3, np.float32)]

    def fit(self, parameters, config):
        if hang:
            time.sleep(3600)                 # never answers
        # stand-in for training: move every weight by this client's data mean
        return [p + data_mean for p in parameters], 10, {"train_accuracy": 0.5, "train_loss": 1.0}

    def evaluate(self, parameters, config):
        return 0.1, 10, {"accuracy": 0.5}

address = "127.0.0.1:%d"
if len(sys.argv) > 3:
    open(sys.argv[3], "w").close()           # imports done, about to connect
if hasattr(fl.client, "start_numpy_client"):
    fl.client.start_numpy_client(server_address=address, client=Client())
else:
    fl.client.start_client(server_address=address, client=Client().to_client())
''' % PORT


def wait_for_port(port, seconds=30):
    deadline = time.time() + seconds
    while time.time() < deadline:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.5)
    return False


def main():
    work = tempfile.mkdtemp(prefix="oasees-fl-example-")
    with open(os.path.join(work, "fl_server.py"), "w") as f:
        f.write(fl_server)
    with open(os.path.join(work, "client.py"), "w") as f:
        f.write(CLIENT)

    print(f"Working in {work}")
    print(f"Server: {ROUNDS} rounds, needs 2 clients, round timeout {TIMEOUT}s")
    server = subprocess.Popen(
        [sys.executable, "fl_server.py", "--NUM_ROUNDS", str(ROUNDS), "--MIN_CLIENTS", "2",
         "--MODEL_NAME", "example", "--ROUND_TIMEOUT", str(TIMEOUT)],
        cwd=work, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if not wait_for_port(PORT):
        server.kill()
        sys.exit(f"The server did not start listening on port {PORT}:\n{server.stdout.read()}")

    def client(mean, mode, *extra):
        return subprocess.Popen([sys.executable, "client.py", mean, mode, *extra], cwd=work,
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # The hung client connects first. The server starts a round as soon as 2 clients are there,
    # so a hung client that connected last could miss every round and nothing would be tested.
    ready = os.path.join(work, "hung-client-ready")
    clients = [client("0.0", "hang", ready)]
    deadline = time.time() + 60
    while not os.path.exists(ready) and time.time() < deadline:
        time.sleep(0.2)
    time.sleep(2)                                # let its connection reach the server
    started = time.time()
    clients += [client("2.0", "train"), client("2.0", "train")]
    print("Clients: one that hangs (connected first), then two that train")

    try:
        output, _ = server.communicate(timeout=10 * TIMEOUT * ROUNDS + 60)
    except subprocess.TimeoutExpired:
        server.kill()
        sys.exit("FAIL: the server is still running. It should have dropped the hung client.")
    finally:
        for c in clients:
            c.kill()
    elapsed = time.time() - started

    rounds_done = output.count("Training Results ===")
    print(f"Server finished in {elapsed:.1f}s with exit code {server.returncode}, "
          f"{rounds_done} of {ROUNDS} rounds trained")

    model_path = os.path.join(work, "example.safetensors")
    if server.returncode != 0 or not os.path.exists(model_path):
        sys.exit(f"FAIL: no model was saved.\n{output}")

    model = load_file(model_path)
    print(f"Saved model {model_path}: " + ", ".join(f"{k} {v.shape} = {v.ravel()[0]:g}" for k, v in model.items()))

    # A round that waited for the hung client takes at least the timeout. If the run was quicker,
    # the hung client never got into a round and the example proved nothing.
    if elapsed < TIMEOUT:
        sys.exit(f"FAIL: finished in {elapsed:.1f}s, under the {TIMEOUT}s timeout, so the hung client "
                 "was never part of a round.")
    # Both trainers add 2 to every weight, so whichever of them answer, a round moves the weights by 2.
    # Two rounds from 0 give 4; anything else means a round was lost or the hung client was counted.
    if rounds_done == ROUNDS and all(np.allclose(v, 4.0) for v in model.values()):
        print(f"OK: the server waited {TIMEOUT}s for the hung client, dropped it, and finished both "
              "rounds with the other two.")
    else:
        sys.exit("FAIL: unexpected model values; see the server output above.")


if __name__ == "__main__":
    main()
