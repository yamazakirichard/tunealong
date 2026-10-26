"""Optional HTTP Basic auth, on when SONGBOOK_AUTH_USER and
SONGBOOK_AUTH_PASSWORD_HASH (bcrypt) are both set. Off by default, for people
who put their own reverse proxy or SSO in front.

A pure ASGI middleware, so media streaming isn't buffered. bcrypt is slow on
purpose, and a page makes many media Range requests, so a header that
verified once is remembered (by its SHA-256, in memory) for this process.
"""

import base64
import hashlib
import hmac

import bcrypt

_CHALLENGE = [(b"www-authenticate", b'Basic realm="Songbook", charset="UTF-8"'),
              (b"content-type", b"text/plain; charset=utf-8")]


class BasicAuth:
    def __init__(self, app, user: str, password_hash: str, open_paths=("/api/health",), max_cached: int = 64):
        self.app = app
        self.open_paths = tuple(open_paths)
        self.user = user.encode()
        self.hash = password_hash.encode()
        self.max_cached = max_cached
        self._ok: set[bytes] = set()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] in self.open_paths:
            return await self.app(scope, receive, send)
        header = dict(scope["headers"]).get(b"authorization", b"")
        if self._check(header):
            return await self.app(scope, receive, send)
        await send({"type": "http.response.start", "status": 401, "headers": _CHALLENGE})
        await send({"type": "http.response.body", "body": b"authentication required\n"})

    def _check(self, header: bytes) -> bool:
        if not header.lower().startswith(b"basic "):
            return False
        digest = hashlib.sha256(header).digest()
        if digest in self._ok:
            return True
        try:
            user, _, password = base64.b64decode(header[6:].strip(), validate=True).partition(b":")
        except ValueError:
            return False
        user_ok = hmac.compare_digest(user, self.user)
        try:
            pw_ok = bcrypt.checkpw(password, self.hash)
        except ValueError:  # a malformed hash in the environment
            pw_ok = False
        if user_ok and pw_ok:
            if len(self._ok) >= self.max_cached:
                self._ok.clear()
            self._ok.add(digest)
            return True
        return False
