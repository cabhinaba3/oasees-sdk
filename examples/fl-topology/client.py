"""FL client for the topology example. oasees-sdk start-fl runs it in each client pod with
--SERVER_ADDRESS, --DATA_PATH, --TARGET_PATH, --EPOCHS and --CLIENT_ID."""
import argparse
import time

import flwr as fl
import numpy as np

parser = argparse.ArgumentParser()
for name in ("--SERVER_ADDRESS", "--DATA_PATH", "--TARGET_PATH", "--EPOCHS", "--CLIENT_ID"):
    parser.add_argument(name)
args = parser.parse_args()

data, target = np.load(args.DATA_PATH), np.load(args.TARGET_PATH)
print(f"client {args.CLIENT_ID}: data {data.shape}, mean {data.mean():g}, from {args.DATA_PATH}", flush=True)


class Client(fl.client.NumPyClient):
    # about 2 MB of weights, so the link bandwidth matters
    def get_parameters(self, config):
        return [np.zeros((512, 1024), np.float32), np.zeros(10, np.float32)]

    def fit(self, parameters, config):
        print(f"FIT_START {time.time():.3f}", flush=True)
        # stand-in for training: move every weight by the mean of this client's data
        return [p + float(data.mean()) for p in parameters], len(data), {"train_accuracy": 0.5, "train_loss": 1.0}

    def evaluate(self, parameters, config):
        return 0.1, len(data), {"accuracy": 0.5}


fl.client.start_numpy_client(server_address=args.SERVER_ADDRESS, client=Client())
