import json
import os

import requests

url = "http://localhost:4000/v1/chat/completions"
# Use LITELLM_MASTER_KEY for direct gateway access
env_path = "/home/jlapenna/.openclaw/.env"
gateway_token = None
if os.path.exists(env_path):
    with open(env_path) as f:
        for line in f:
            if line.startswith("LITELLM_MASTER_KEY="):
                gateway_token = line.split("=")[1].strip().strip('"').strip("'")

print(f"Using token: {gateway_token}")

headers = {"Content-Type": "application/json", "Authorization": f"Bearer {gateway_token}"}
data = {
    "model": "main",
    "messages": [{"role": "user", "content": "Explain step by step why 2+2=4."}],
}

response = requests.post(url, headers=headers, json=data)
print(json.dumps(response.json(), indent=2))
