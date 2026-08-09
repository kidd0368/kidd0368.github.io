# -*- coding: utf-8 -*-
"""AES-256-GCM + PBKDF2-SHA256 加解密，格式與本站其他加密頁完全相容：
box = {"salt": b64, "iterations": int, "iv": b64, "ciphertext": b64}
頁面 payload 以 box JSON 切成 60000 字元一塊的 payload.enc.NN + payload-manifest.json。
"""
import base64
import json
import os
import secrets

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes

ITERATIONS = 310000
CHUNK = 60000


def _key(password: str, salt: bytes, iterations: int) -> bytes:
    kdf = PBKDF2HMAC(algorithm=hashes.SHA256(), length=32, salt=salt, iterations=iterations)
    return kdf.derive(password.encode("utf-8"))


def encrypt_to_box(plaintext: str, password: str) -> dict:
    salt = secrets.token_bytes(16)
    iv = secrets.token_bytes(12)
    key = _key(password, salt, ITERATIONS)
    ct = AESGCM(key).encrypt(iv, plaintext.encode("utf-8"), None)
    return {
        "salt": base64.b64encode(salt).decode(),
        "iterations": ITERATIONS,
        "iv": base64.b64encode(iv).decode(),
        "ciphertext": base64.b64encode(ct).decode(),
    }


def decrypt_from_box(box: dict, password: str) -> str:
    salt = base64.b64decode(box["salt"])
    iv = base64.b64decode(box["iv"])
    ct = base64.b64decode(box["ciphertext"])
    key = _key(password, salt, int(box["iterations"]))
    return AESGCM(key).decrypt(iv, ct, None).decode("utf-8")


# ---------- 加密資料庫（store.enc，單一 box JSON 檔） ----------

def load_store(path: str, password: str) -> dict:
    if not os.path.exists(path):
        return {"version": 1, "snapshots": [], "macro": {}, "quotes": [], "commentary": []}
    with open(path, "r", encoding="utf-8") as f:
        box = json.load(f)
    return json.loads(decrypt_from_box(box, password))


def save_store(path: str, store: dict, password: str) -> None:
    box = encrypt_to_box(json.dumps(store, ensure_ascii=False, separators=(",", ":")), password)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(box, f)


# ---------- 加密頁 payload（分塊 + manifest） ----------

def write_encrypted_page(html: str, password: str, out_dir: str) -> None:
    box_json = json.dumps(encrypt_to_box(html, password))
    files = []
    for i in range(0, len(box_json), CHUNK):
        name = "payload.enc.%02d" % (i // CHUNK)
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as f:
            f.write(box_json[i:i + CHUNK])
        files.append(name)
    # 清掉上次多出來的塊
    n = len(files)
    while True:
        stale = os.path.join(out_dir, "payload.enc.%02d" % n)
        if os.path.exists(stale):
            os.remove(stale)
            n += 1
        else:
            break
    with open(os.path.join(out_dir, "payload-manifest.json"), "w", encoding="utf-8") as f:
        json.dump({"files": files}, f)
