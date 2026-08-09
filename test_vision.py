from pathlib import Path
from ollama import chat

image_path = Path("img.jpg")

print("Sending image...", flush=True)

response = chat(
    model="qwen3-vl:4b-instruct",
    messages=[
        {
            "role": "user",
            "content": "Describe this image briefly and directly.",
            "images": [str(image_path.resolve())],
        }
    ],
)

print("\nDONE REASON:")
print(response.done_reason)

print("\nCONTENT:")
print(response.message.content)