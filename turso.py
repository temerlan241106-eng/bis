"""Минимальный клиент Turso (облачный SQLite) поверх HTTPS — протокол Hrana v2 /v2/pipeline.

Работает через обычный HTTPS, поэтому подходит для бесплатного PythonAnywhere
(домен .turso.io есть в их белом списке). Интерфейс похож на sqlite3.Connection,
чтобы остальной код не менялся: execute(sql, params) -> курсор с fetchone/fetchall,
строки доступны и по индексу, и по имени колонки (как sqlite3.Row).
"""
import base64
import sqlite3
import time

import requests

_session = requests.Session()  # keep-alive между запросами: меньше задержка


class Row(tuple):
    """Аналог sqlite3.Row: r[0], r["name"], dict(r), r.keys()."""

    def __new__(cls, cols, values):
        obj = super().__new__(cls, values)
        obj._cols = cols
        obj._idx = {c: i for i, c in enumerate(cols)}
        return obj

    def __getitem__(self, key):
        if isinstance(key, str):
            return tuple.__getitem__(self, self._idx[key])
        return tuple.__getitem__(self, key)

    def keys(self):
        return list(self._cols)


class Cursor:
    def __init__(self, result):
        cols = [c.get("name") for c in result.get("cols", [])]
        self._rows = [Row(cols, [_decode(v) for v in r]) for r in result.get("rows", [])]
        self._pos = 0
        self.rowcount = result.get("affected_row_count", -1)
        rid = result.get("last_insert_rowid")
        self.lastrowid = int(rid) if rid is not None else None

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        self._pos += 1
        return self._rows[self._pos - 1]

    def fetchall(self):
        rest = self._rows[self._pos:]
        self._pos = len(self._rows)
        return rest

    def __iter__(self):
        return iter(self.fetchall())


def _encode(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray)):
        return {"type": "blob", "base64": base64.b64encode(v).decode().rstrip("=")}
    return {"type": "text", "value": str(v)}


def _decode(v):
    t = v.get("type")
    if t == "null":
        return None
    if t == "integer":
        return int(v["value"])
    if t == "float":
        return float(v["value"])
    if t == "blob":
        b = v.get("base64", "")
        return base64.b64decode(b + "=" * (-len(b) % 4))
    return v.get("value")


def _stmt(sql, params=()):
    stmt = {"sql": sql, "want_rows": True}
    if isinstance(params, dict):
        stmt["named_args"] = [{"name": ":" + k, "value": _encode(v)} for k, v in params.items()]
    elif params:
        stmt["args"] = [_encode(v) for v in params]
    return stmt


def _raise(err):
    msg = err.get("message", "Turso error")
    code = err.get("code", "") or ""
    if "CONSTRAINT" in code or "constraint" in msg.lower():
        raise sqlite3.IntegrityError(msg)
    raise sqlite3.OperationalError(msg)


class Connection:
    def __init__(self, url, token, timeout=20):
        url = url.strip()
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        self.base = url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token.strip()}"}
        self.timeout = timeout
        self.baton = None  # идентификатор потока: нужен, пока открыта транзакция
        self.in_transaction = False

    def _pipeline(self, stmts, keep_open):
        reqs = [{"type": "execute", "stmt": s} for s in stmts]
        if not keep_open:
            reqs.append({"type": "close"})
        body = {"baton": self.baton, "requests": reqs}
        # при сбое сети (DNS, обрыв соединения) повторяем; внутри транзакции — нет,
        # чтобы не выполнить её часть дважды
        attempts = 3 if self.baton is None else 1
        for i in range(attempts):
            try:
                r = _session.post(f"{self.base}/v2/pipeline", headers=self.headers,
                                  timeout=self.timeout, json=body)
                break
            except requests.ConnectionError as e:
                if i == attempts - 1:
                    raise sqlite3.OperationalError(f"Нет связи с Turso: {e}") from e
                time.sleep(0.4 * (i + 1))
        if r.status_code != 200:
            raise sqlite3.OperationalError(f"Turso HTTP {r.status_code}: {r.text[:300]}")
        data = r.json()
        self.baton = data.get("baton") if keep_open else None
        if data.get("base_url"):
            self.base = data["base_url"].rstrip("/")
        out = []
        for res in data["results"][:len(stmts)]:
            if res.get("type") == "error":
                _raise(res.get("error", {}))
            out.append(res["response"]["result"])
        return out

    def execute(self, sql, params=()):
        head = sql.lstrip().split(None, 1)[0].upper() if sql.strip() else ""
        starting = head == "BEGIN"
        ending = head in ("COMMIT", "ROLLBACK", "END")
        keep_open = (self.in_transaction or starting) and not ending
        try:
            result = self._pipeline([_stmt(sql, params)], keep_open)[0]
        except Exception:
            if ending or not self.in_transaction:
                self.in_transaction, self.baton = False, None
            raise
        if starting:
            self.in_transaction = True
        if ending:
            self.in_transaction = False
        return Cursor(result)

    def batch(self, statements):
        """Несколько запросов за один HTTP-запрос: [(sql, params), ...] -> [Cursor, ...]."""
        results = self._pipeline([_stmt(s, p) for s, p in statements], self.in_transaction)
        return [Cursor(r) for r in results]

    def executescript(self, script):
        stmts, buf = [], ""
        for line in script.splitlines(keepends=True):
            buf += line
            if sqlite3.complete_statement(buf):
                if buf.strip():
                    stmts.append((buf.strip(), ()))
                buf = ""
        if buf.strip():
            stmts.append((buf.strip(), ()))
        for i in range(0, len(stmts), 100):
            self.batch(stmts[i:i + 100])

    def commit(self):
        pass  # без явного BEGIN каждый запрос фиксируется сразу (как isolation_level=None)

    def close(self):
        if self.baton:
            try:
                _session.post(f"{self.base}/v2/pipeline", headers=self.headers, timeout=5,
                              json={"baton": self.baton, "requests": [{"type": "close"}]})
            except requests.RequestException:
                pass
        self.baton = None
