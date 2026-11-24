"""Tiny Turso / libSQL client that talks to Turso over its HTTP API.

It mimics the parts of Python's `sqlite3` module that this project uses
(execute, executescript, commit, rollback, `with conn:`, Row objects,
sqlite3.IntegrityError ...), so the rest of the app does not know whether it is
talking to a local SQLite file or to Turso. It needs no extra pip package.

Transactions follow sqlite3's rules: a transaction starts before the first
INSERT / UPDATE / DELETE and ends at commit() / rollback(). Reads outside a
transaction use a single round trip.
"""

import base64
import http.client
import json
import sqlite3
import threading

_DML = {"INSERT", "UPDATE", "DELETE", "REPLACE"}
_BEGIN = {"BEGIN", "SAVEPOINT"}
_END = {"COMMIT", "END", "ROLLBACK"}

_local = threading.local()


# ---------------------------------------------------------------------------
# URL / HTTP plumbing
# ---------------------------------------------------------------------------

def split_url(url: str):
    """'libsql://db.turso.io' -> ('https', 'db.turso.io')."""
    url = url.strip()
    scheme = "https"
    for prefix, sch in (("libsql://", "https"), ("https://", "https"), ("wss://", "https"),
                        ("http://", "http"), ("ws://", "http")):
        if url.startswith(prefix):
            url, scheme = url[len(prefix):], sch
            break
    return scheme, url.split("/")[0]


def is_remote(target) -> bool:
    return isinstance(target, str) and target.startswith(
        ("libsql://", "https://", "http://", "wss://", "ws://")
    )


def _pooled(scheme, host):
    pool = getattr(_local, "pool", None)
    if pool is None:
        pool = _local.pool = {}
    conn = pool.get((scheme, host))
    if conn is None:
        cls = http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        conn = pool[(scheme, host)] = cls(host, timeout=30)
    return conn


def _drop(scheme, host):
    pool = getattr(_local, "pool", {})
    conn = pool.pop((scheme, host), None)
    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass


def _post(scheme, host, token, body):
    payload = json.dumps(body).encode()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    last = None
    for attempt in range(2):
        conn = _pooled(scheme, host)
        try:
            conn.request("POST", "/v2/pipeline", payload, headers)
            resp = conn.getresponse()
            raw = resp.read()
            break
        except (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError,
                http.client.CannotSendRequest, http.client.ResponseNotReady) as exc:
            # A kept-alive connection the server already closed: use a fresh one.
            _drop(scheme, host)
            last = exc
        except (OSError, http.client.HTTPException) as exc:
            _drop(scheme, host)
            raise sqlite3.OperationalError(
                f"Could not reach Turso ({exc.__class__.__name__})."
            ) from None
    else:
        raise sqlite3.OperationalError(
            f"Could not reach Turso ({last.__class__.__name__})."
        ) from None

    if resp.status in (401, 403):
        raise sqlite3.OperationalError(
            f"Turso rejected the credentials (HTTP {resp.status}). "
            "Check TURSO_AUTH_TOKEN (it must be valid for this database)."
        )
    if resp.status == 404:
        raise sqlite3.OperationalError(f"Turso database not found at {host}.")
    try:
        data = json.loads(raw)
    except ValueError:
        raise sqlite3.OperationalError(f"Unexpected reply from Turso (HTTP {resp.status}).") from None
    if resp.status != 200:
        msg = data.get("error") if isinstance(data, dict) else None
        raise sqlite3.OperationalError(f"Turso error (HTTP {resp.status}): {msg or 'unknown'}")
    return data


# ---------------------------------------------------------------------------
# Values, rows, errors
# ---------------------------------------------------------------------------

def _encode(v):
    if v is None:
        return {"type": "null"}
    if isinstance(v, bool):
        return {"type": "integer", "value": str(int(v))}
    if isinstance(v, int):
        return {"type": "integer", "value": str(v)}
    if isinstance(v, float):
        return {"type": "float", "value": v}
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"type": "blob", "base64": base64.b64encode(bytes(v)).decode()}
    return {"type": "text", "value": str(v)}


def _decode(cell):
    kind = cell.get("type")
    if kind == "null":
        return None
    if kind == "integer":
        return int(cell["value"])
    if kind == "float":
        return float(cell["value"])
    if kind == "blob":
        return base64.b64decode(cell.get("base64", "") + "==")
    return cell.get("value")


def _error(err) -> Exception:
    msg = (err or {}).get("message") or "Turso error"
    code = str((err or {}).get("code") or "")
    if "CONSTRAINT" in code.upper() or "constraint failed" in msg.lower():
        return sqlite3.IntegrityError(msg)
    return sqlite3.OperationalError(msg)


class Row:
    """Like sqlite3.Row: index by position or (case-insensitive) column name."""

    __slots__ = ("_cols", "_vals", "_idx")

    def __init__(self, cols, vals):
        self._cols, self._vals = cols, vals
        self._idx = {}
        for i, c in enumerate(cols):
            self._idx.setdefault(c.lower(), i)

    def keys(self):
        return list(self._cols)

    def __getitem__(self, key):
        if isinstance(key, str):
            try:
                return self._vals[self._idx[key.lower()]]
            except KeyError:
                raise IndexError("No item with that key") from None
        return self._vals[key]

    def __iter__(self):
        return iter(self._vals)

    def __len__(self):
        return len(self._vals)

    def __eq__(self, other):
        return isinstance(other, Row) and self._cols == other._cols and self._vals == other._vals

    def __hash__(self):
        return hash((tuple(self._cols), tuple(self._vals)))

    def __repr__(self):
        return f"<Row {dict(zip(self._cols, self._vals))}>"


class Cursor:
    def __init__(self, conn, result=None):
        self._conn = conn
        self.arraysize = 1
        self.rowcount = -1
        self.lastrowid = None
        self.description = None
        self._rows = []
        self._pos = 0
        if result is not None:
            self._load(result)

    def _load(self, result):
        cols = [c.get("name") or "" for c in result.get("cols", [])]
        raw = result.get("rows", [])
        factory = self._conn.row_factory
        rows = []
        for r in raw:
            vals = [_decode(c) for c in r]
            rows.append(Row(cols, vals) if factory is not None else tuple(vals))
        self._rows = rows
        self.description = tuple((c, None, None, None, None, None, None) for c in cols) if cols else None
        if not cols:
            ar = result.get("affected_row_count")
            self.rowcount = int(ar) if ar is not None else -1
        li = result.get("last_insert_rowid")
        self.lastrowid = int(li) if li is not None else None

    def execute(self, sql, params=()):
        self._load(self._conn._run(sql, params))
        return self

    def executemany(self, sql, seq):
        self._conn._run_many(sql, seq)
        return self

    def fetchone(self):
        if self._pos >= len(self._rows):
            return None
        row = self._rows[self._pos]
        self._pos += 1
        return row

    def fetchmany(self, size=None):
        size = size or self.arraysize
        rows = self._rows[self._pos:self._pos + size]
        self._pos += len(rows)
        return rows

    def fetchall(self):
        rows = self._rows[self._pos:]
        self._pos = len(self._rows)
        return rows

    def __iter__(self):
        return iter(self.fetchall())

    def close(self):
        pass


# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------

def _keyword(sql: str) -> str:
    """First SQL keyword of a statement, ignoring leading comments."""
    s = sql.lstrip()
    while True:
        if s.startswith("--"):
            s = s.split("\n", 1)[1].lstrip() if "\n" in s else ""
        elif s.startswith("/*"):
            s = s.split("*/", 1)[1].lstrip() if "*/" in s else ""
        else:
            break
    word = s.split(None, 1)[0] if s else ""
    return word.rstrip(";(").upper()


def _stmt(sql, params):
    stmt = {"sql": sql, "want_rows": True}
    if isinstance(params, dict):
        stmt["named_args"] = [
            {"name": str(k).lstrip(":@$"), "value": _encode(v)} for k, v in params.items()
        ]
    elif params:
        stmt["args"] = [_encode(v) for v in params]
    return stmt


class Connection:
    def __init__(self, url: str, token: str):
        self._scheme, self._host = split_url(url)
        self._token = token
        self._baton = None
        self._in_tx = False
        self.row_factory = Row
        self.total_changes = 0

    # -- low level ---------------------------------------------------------
    def _send(self, reqs, close):
        body = {"requests": list(reqs) + ([{"type": "close"}] if close else [])}
        if self._baton:
            body["baton"] = self._baton
        try:
            data = _post(self._scheme, self._host, self._token, body)
        except sqlite3.Error:
            self._baton, self._in_tx = None, False
            raise
        self._baton = None if close else data.get("baton")
        if data.get("base_url"):
            self._scheme, self._host = split_url(data["base_url"])
        items = []
        for r in data.get("results", [])[:len(reqs)]:
            if r.get("type") == "error":
                items.append(_error(r.get("error")))
            else:
                items.append(r.get("response", {}))
        return items

    def _run(self, sql, params=()):
        kind = _keyword(sql)
        begin = (not self._in_tx) and kind in _DML
        reqs = []
        if begin:
            reqs.append({"type": "execute", "stmt": {"sql": "BEGIN"}})
        reqs.append({"type": "execute", "stmt": _stmt(sql, params)})
        ends = kind in _END
        close = ends or (not self._in_tx and not begin and kind not in _BEGIN)

        items = self._send(reqs, close)
        if begin:
            if isinstance(items[0], Exception):
                raise items[0]
            self._in_tx = True
        if kind in _BEGIN:
            self._in_tx = True
        if ends:
            self._in_tx = False
        res = items[-1]
        if isinstance(res, Exception):
            raise res
        result = res.get("result", {})
        self.total_changes += int(result.get("affected_row_count") or 0)
        return result

    def _run_many(self, sql, seq):
        kind = _keyword(sql)
        begin = (not self._in_tx) and kind in _DML
        reqs = [{"type": "execute", "stmt": {"sql": "BEGIN"}}] if begin else []
        reqs += [{"type": "execute", "stmt": _stmt(sql, p)} for p in seq]
        if not reqs:
            return
        items = self._send(reqs, close=(not self._in_tx and not begin))
        if begin and not isinstance(items[0], Exception):
            self._in_tx = True
        for it in items:
            if isinstance(it, Exception):
                raise it

    # -- sqlite3-style API -------------------------------------------------
    def execute(self, sql, params=()):
        return Cursor(self, self._run(sql, params))

    def executemany(self, sql, seq):
        cur = Cursor(self)
        cur.executemany(sql, seq)
        return cur

    def cursor(self):
        return Cursor(self)

    def executescript(self, script):
        self.commit()
        items = self._send([{"type": "sequence", "sql": script}], close=True)
        if items and isinstance(items[0], Exception):
            raise items[0]
        return Cursor(self)

    def commit(self):
        if self._in_tx:
            self._in_tx = False
            items = self._send([{"type": "execute", "stmt": {"sql": "COMMIT"}}], close=True)
            if items and isinstance(items[0], Exception):
                raise items[0]

    def rollback(self):
        if self._baton:
            self._in_tx = False
            try:
                self._send([{"type": "execute", "stmt": {"sql": "ROLLBACK"}}], close=True)
            except sqlite3.Error:
                pass
        self._in_tx = False

    def close(self):
        if self._baton:
            try:
                self._send([], close=True)
            except sqlite3.Error:
                pass
        self._baton, self._in_tx = None, False

    @property
    def in_transaction(self):
        return self._in_tx

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False

    def __del__(self):
        try:
            if self._baton:
                self._send([], close=True)
        except Exception:
            pass


def connect(url: str, token: str) -> Connection:
    return Connection(url, token)
