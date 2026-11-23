"""Local atomic storage. Windows secrets are encrypted for the current user."""
from __future__ import annotations

import ctypes
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time


def protect(data: bytes, decrypt: bool = False) -> bytes:
    if os.name != "nt":
        return data
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_byte))]

    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    fn = crypt.CryptUnprotectData if decrypt else crypt.CryptProtectData
    fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                   ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    fn.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise OSError("Windows 无法解密本机授权，请使用保存授权时的 Windows 账号。")
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(ctypes.cast(target.data, ctypes.c_void_p))


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL, salt BLOB NOT NULL, password BLOB NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id),
                    csrf TEXT NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS documents (
                    user_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL,
                    body BLOB NOT NULL, PRIMARY KEY (user_id, name));
                CREATE TABLE IF NOT EXISTS extension_codes (
                    digest TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS extension_devices (
                    digest TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id),
                    origin TEXT NOT NULL, label TEXT NOT NULL, created REAL NOT NULL,
                    expires REAL NOT NULL, last_seen REAL NOT NULL);
            """)
        os.chmod(path, 0o600)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def register(self, username: str, password: str) -> int:
        username = username.strip()
        if not 3 <= len(username) <= 80 or not 10 <= len(password) <= 1024:
            raise ValueError("用户名需 3–80 个字符，密码需至少 10 个字符。")
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
        try:
            with self.connect() as db:
                result = db.execute("INSERT INTO users(username,display_name,salt,password) VALUES(?,?,?,?)",
                                    (username.casefold(), username, salt, digest))
                return result.lastrowid
        except sqlite3.IntegrityError:
            raise ValueError("这个用户名已被注册。") from None

    def login(self, username: str, password: str) -> int | None:
        with self.connect() as db:
            user = db.execute("SELECT * FROM users WHERE username=?", (username.strip().casefold(),)).fetchone()
        salt = user["salt"] if user else b"student-calendar"
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
        return user["id"] if user and hmac.compare_digest(digest, user["password"]) else None

    def user(self, user_id: int) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT id,display_name FROM users WHERE id=?", (user_id,)).fetchone()
        return {"id": row["id"], "name": row["display_name"]} if row else None

    def new_session(self, user_id: int | None = None) -> tuple:
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            db.execute("INSERT INTO sessions VALUES(?,?,?,?)", (digest, user_id, csrf, time.time() + 7 * 86400))
        return token, {"id": digest, "user_id": user_id, "csrf": csrf}

    def session(self, token: str) -> dict | None:
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self.connect() as db:
            row = db.execute("SELECT * FROM sessions WHERE id=? AND expires>?", (digest, time.time())).fetchone()
        return dict(row) if row else None

    def delete_session(self, session_id: str) -> None:
        with self.connect() as db:
            db.execute("DELETE FROM sessions WHERE id=?", (session_id,))

    def read(self, user_id: int, name: str, default: dict) -> dict:
        with self.connect() as db:
            row = db.execute("SELECT body FROM documents WHERE user_id=? AND name=?", (user_id, name)).fetchone()
        if not row:
            return json.loads(json.dumps(default))
        data = bytes(row["body"])
        return json.loads(protect(data, decrypt=True) if name == "secrets" else data)

    def write(self, user_id: int, name: str, value: dict) -> None:
        data = json.dumps(value, ensure_ascii=False).encode()
        if name == "secrets":
            data = protect(data)
        with self.connect() as db:
            db.execute("INSERT INTO documents(user_id,name,body) VALUES(?,?,?) "
                       "ON CONFLICT(user_id,name) DO UPDATE SET body=excluded.body", (user_id, name, data))

    def connected_users(self) -> list:
        with self.connect() as db:
            return [row[0] for row in db.execute("SELECT user_id FROM documents WHERE name='secrets'")]

    def pairing_code(self, user_id: int) -> str:
        code = secrets.token_urlsafe(18)
        with self.connect() as db:
            db.execute("DELETE FROM extension_codes WHERE user_id=? OR expires<?", (user_id, time.time()))
            db.execute("INSERT INTO extension_codes VALUES(?,?,?)",
                       (hashlib.sha256(code.encode()).hexdigest(), user_id, time.time() + 600))
        return code

    def pair_extension(self, code: str, origin: str) -> tuple:
        digest = hashlib.sha256(code.encode()).hexdigest()
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT user_id FROM extension_codes WHERE digest=? AND expires>?", (digest, now)).fetchone()
            if not row:
                raise ValueError("配对码已失效，请在网页重新生成。")
            uid = row["user_id"]
            db.execute("DELETE FROM extension_codes WHERE digest=?", (digest,))
            db.execute("INSERT INTO extension_devices VALUES(?,?,?,?,?,?,?)",
                       (hashlib.sha256(token.encode()).hexdigest(), uid, origin, "Chrome / Edge 插件", now, now + 90 * 86400, now))
        return token, uid

    def extension_device(self, token: str, origin: str) -> dict | None:
        with self.connect() as db:
            row = db.execute("SELECT * FROM extension_devices WHERE digest=? AND origin=? AND expires>?",
                             (hashlib.sha256(token.encode()).hexdigest(), origin, time.time())).fetchone()
            if row:
                db.execute("UPDATE extension_devices SET last_seen=? WHERE digest=?", (time.time(), row["digest"]))
        return dict(row) if row else None

    def extension_devices(self, user_id: int) -> list:
        with self.connect() as db:
            return [dict(row) for row in db.execute(
                "SELECT digest AS id,label,created,last_seen FROM extension_devices WHERE user_id=? AND expires>?",
                (user_id, time.time()))]

    def revoke_extension(self, user_id: int, device_id: str):
        with self.connect() as db:
            db.execute("DELETE FROM extension_devices WHERE user_id=? AND digest=?", (user_id, device_id))
