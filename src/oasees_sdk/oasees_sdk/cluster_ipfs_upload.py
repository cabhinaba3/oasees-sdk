import os
import requests
import json
from contextlib import ExitStack
from requests_toolbelt.multipart.encoder import MultipartEncoder

def assets_to_ipfs(api_url, directory_path):
    paths = [os.path.join(directory_path, f) for f in os.listdir(directory_path) if os.path.isfile(os.path.join(directory_path, f))]

    # ExitStack closes every opened file once the upload is done (or fails).
    with ExitStack() as stack:
        m = MultipartEncoder(
            fields={os.path.basename(p): (os.path.basename(p), stack.enter_context(open(p, "rb")), 'text/plain') for p in paths}
        )

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
