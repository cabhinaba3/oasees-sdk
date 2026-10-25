import os
import requests
import json
from contextlib import ExitStack
from requests_toolbelt.multipart.encoder import MultipartEncoder


class _LazyFile:
    """File-like object for MultipartEncoder that opens its file on the first read and closes it
    when everything has been read, so a large directory never has all its files open at once.

    len() is the number of bytes not read yet, which is how the encoder tells a part is finished."""
    def __init__(self, path):
        self.path = path
        self._left = os.path.getsize(path)
        self._file = None

    def __len__(self):
        return self._left

    def read(self, size=-1):
        if self._left <= 0:
            return b""
        if self._file is None:
            self._file = open(self.path, "rb")
        data = self._file.read(self._left if size is None or size < 0 else min(size, self._left))
        self._left -= len(data)
        if self._left <= 0 or not data:   # finished, or the file got shorter while uploading
            self._left = 0
            self.close()
        return data

    def close(self):
        if self._file is not None:
            self._file.close()
            self._file = None


def _files_under(directory_path):
    """(path on disk, path relative to directory_path with / separators) for every file below it."""
    found = []
    for root, dirs, files in os.walk(directory_path):
        dirs.sort()
        for name in sorted(files):
            path = os.path.join(root, name)
            found.append((path, os.path.relpath(path, directory_path).replace(os.sep, "/")))
    return found


def assets_to_ipfs(api_url, directory_path):
    """Upload a directory, subdirectories included, and return the CID of the wrapping directory.

    Empty directories are not uploaded: IPFS only learns about a directory from the files in it."""
    with ExitStack() as stack:
        fields = {}
        for path, relative in _files_under(directory_path):
            lazy = _LazyFile(path)
            stack.callback(lazy.close)   # closes it if the upload fails half way
            fields[relative] = (relative, lazy, 'text/plain')
        m = MultipartEncoder(fields=fields)

        headers = {'Content-Type': m.content_type}
        response = requests.post(f"{api_url}/api/v0/add?wrap-with-directory=true", headers=headers, data=m, stream=True)
        response.raise_for_status()

        result=""
        for line in response.iter_lines():
            if line:
                decoded_line = line.decode('utf-8')
                j=json.loads(decoded_line)
                if(j["Name"]==''):
                    result= j["Hash"]

    return result
