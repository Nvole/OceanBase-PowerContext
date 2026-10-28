#!/usr/bin/env python3
import hashlib
import json
import os
import pathlib
import sys
import tempfile
import time
import urllib.request

MODEL_ID = "Xenova/all-MiniLM-L6-v2"
REVISION = "751bff37182d3f1213fa05d7196b954e230abad9"
BASE = f"https://huggingface.co/{MODEL_ID}/resolve/{REVISION}"
ROOT = pathlib.Path(__file__).resolve().parents[1]
MODEL_ROOT = ROOT / "models" / MODEL_ID
FILES = {
    "config.json": 650,
    "tokenizer.json": 711661,
    "tokenizer_config.json": 366,
    "special_tokens_map.json": 125,
    "vocab.txt": 231508,
    "onnx/model.onnx": 90387606,
    "onnx/model_quantized.onnx": 22972370,
}
EXPECTED_SHA256 = {
    "config.json": "7135149f7cffa1a573466c6e4d8423ed73b62fd2332c575bf738a0d033f70df7",
    "tokenizer.json": "da0e79933b9ed51798a3ae27893d3c5fa4a201126cef75586296df9b4d2c62a0",
    "tokenizer_config.json": "9261e7d79b44c8195c1cada2b453e55b00aeb81e907a6664974b4d7776172ab3",
    "special_tokens_map.json": "b6d346be366a7d1d48332dbc9fdf3bf8960b5d879522b7799ddba59e76237ee3",
    "vocab.txt": "07eced375cec144d27c900241f3e339478dec958f92fddbc551f295c992038a3",
    "onnx/model.onnx": "759c3cd2b7fe7e93933ad23c4c9181b7396442a2ed746ec7c1d46192c469c46e",
    "onnx/model_quantized.onnx": "afdb6f1a0e45b715d0bb9b11772f032c399babd23bfc31fed1c170afc848bdb1",
}

def url_for(name):
    return f"{BASE}/{name}"

def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def download(name, expected_size):
    target = MODEL_ROOT / name
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size == expected_size and sha256(target) == EXPECTED_SHA256[name]:
        return {"path": name, "bytes": expected_size, "sha256": sha256(target), "source": url_for(name)}
    last_error = None
    for attempt in range(1, 4):
        temp_name = None
        try:
            request = urllib.request.Request(url_for(name), headers={"User-Agent": "stepfun-local-verifier/1.0"})
            with urllib.request.urlopen(request, timeout=120) as response:
                with tempfile.NamedTemporaryFile(prefix=".download-", dir=target.parent, delete=False) as temp:
                    temp_name = pathlib.Path(temp.name)
                    copied = 0
                    while True:
                        block = response.read(1024 * 1024)
                        if not block:
                            break
                        temp.write(block)
                        copied += len(block)
            if copied != expected_size:
                raise RuntimeError(f"{name}: expected {expected_size} bytes, received {copied}")
            if sha256(temp_name) != EXPECTED_SHA256[name]:
                raise RuntimeError(f"{name}: SHA256 mismatch against pinned asset")
            os.replace(temp_name, target)
            return {"path": name, "bytes": copied, "sha256": sha256(target), "source": url_for(name)}
        except Exception as error:
            last_error = error
            if temp_name and temp_name.exists():
                temp_name.unlink()
            if attempt < 3:
                time.sleep(attempt * 2)
    raise RuntimeError(f"failed to download {name}: {last_error}")

def main():
    entries = [download(name, size) for name, size in FILES.items()]
    manifest = {
        "model_id": MODEL_ID,
        "revision": REVISION,
        "license": "Apache-2.0",
        "source": f"https://huggingface.co/{MODEL_ID}/tree/{REVISION}",
        "dimension": 384,
        "pooling": "mean",
        "normalization": "l2",
        "files": entries,
        "fp32_bytes": FILES["onnx/model.onnx"],
        "q8_bytes": FILES["onnx/model_quantized.onnx"],
        "q8_compression_ratio": round(FILES["onnx/model.onnx"] / FILES["onnx/model_quantized.onnx"], 4),
        "fp32_bundle_bytes": sum(size for name, size in FILES.items() if name != "onnx/model_quantized.onnx"),
        "q8_bundle_bytes": sum(size for name, size in FILES.items() if name != "onnx/model.onnx"),
    }
    (ROOT / "models").mkdir(exist_ok=True)
    (ROOT / "models" / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (ROOT / "model-manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()
