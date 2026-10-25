import os
from dotenv import load_dotenv, find_dotenv


class ENVs():
    """Endpoints used to upload projects.

    set_envs() wins if it was called. Otherwise the values come from the IPFS_ENDPOINT and
    INDEXER_ENDPOINT environment variables, or from a .env file in the working directory (or above):

        IPFS_ENDPOINT=http://<ip>:5001/api/v0
        INDEXER_ENDPOINT=http://<ip>:31007
    """
    def __init__(self):
        self._ipfs_endpoint = None
        self._indexer_endpoint = None

    @staticmethod
    def _from_environment(name):
        load_dotenv(find_dotenv(usecwd=True))  # never overrides a variable that is already set
        return os.environ.get(name, "")

    @property
    def ipfs_endpoint(self):
        if self._ipfs_endpoint is not None:
            return self._ipfs_endpoint
        return self._from_environment("IPFS_ENDPOINT")

    @property
    def indexer_endpoint(self):
        if self._indexer_endpoint is not None:
            return self._indexer_endpoint
        return self._from_environment("INDEXER_ENDPOINT")

    def set_envs(self,ipfs_endpoint,indexer_endpoint):
        self._ipfs_endpoint = ipfs_endpoint
        self._indexer_endpoint = indexer_endpoint

Envs = ENVs()
