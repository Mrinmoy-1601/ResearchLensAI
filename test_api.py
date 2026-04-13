"""
Test script: uploads the PDF to the local API and prints the summary + chat response.
"""
import json
import urllib.request
import sys

PDF_PATH = r"C:\Users\mrinm\Downloads\BTP-2\59_Do_we_really_need_Foundatio.pdf"
BASE_URL = "http://localhost:8000"
SESSION_FILE = r"C:\Users\mrinm\Downloads\BTP-2\session_id.txt"


def multipart_upload(url: str, pdf_path: str) -> dict:
    """Upload a PDF via multipart/form-data."""
    with open(pdf_path, "rb") as f:
        pdf_data = f.read()

    boundary = b"----PythonBoundary7F3A9B"
    filename = pdf_path.split("\\")[-1].encode()

    body = (
        b"--" + boundary + b"\r\n"
        b'Content-Disposition: form-data; name="file"; filename="' + filename + b'"\r\n'
        b"Content-Type: application/pdf\r\n\r\n"
        + pdf_data
        + b"\r\n--" + boundary + b"--\r\n"
    )

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", f"multipart/form-data; boundary={boundary.decode()}")

    print(f"Uploading {len(pdf_data)/1024:.1f} KB to {url} ...")
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(resp.read())


def chat(session_id: str, message: str) -> dict:
    """Send a chat message."""
    payload = json.dumps({"session_id": session_id, "message": message}).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/chat", data=payload, method="POST"
    )
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


# ── Upload ────────────────────────────────────────────────────────────────────
try:
    result = multipart_upload(f"{BASE_URL}/upload", PDF_PATH)
except Exception as e:
    print(f"UPLOAD ERROR: {e}")
    sys.exit(1)

print("\n=== UPLOAD SUCCESS ===")
print(f"Session ID : {result.get('session_id')}")
print(f"Title      : {result.get('title')}")
print(f"Pages      : {result.get('num_pages')}")
print(f"Chunks     : {result.get('num_chunks')}")
print("\n--- SUMMARY (first 800 chars) ---")
print(result.get("summary", "")[:800])

session_id = result.get("session_id", "")
with open(SESSION_FILE, "w") as sf:
    sf.write(session_id)
print(f"\nSession ID saved to {SESSION_FILE}")

# ── Chat test ─────────────────────────────────────────────────────────────────
print("\n=== CHAT TEST ===")
try:
    chat_result = chat(session_id, "What is the main contribution of this paper?")
    print("Chat reply (first 600 chars):\n")
    print(chat_result.get("reply", "")[:600])
    print("\nPage refs:", chat_result.get("page_refs", []))
except Exception as e:
    print(f"CHAT ERROR: {e}")
