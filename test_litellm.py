import requests

payload = {
    "model": "main",
    "messages": [
        {"role": "developer", "content": "You are a helpful assistant."},
        {"role": "user", "content": "test message"},
    ],
    "tools": [
        {
            "type": "function",
            "function": {
                "name": "test_tool",
                "description": "test",
                "parameters": {"type": "object", "properties": {}},
            },
        }
    ],
}

r = requests.post(
    "http://localhost:4000/v1/chat/completions",
    json=payload,
    headers={"Authorization": "Bearer fake", "Content-Type": "application/json"},
    timeout=10,
)
print(r.status_code)
print(r.text)
