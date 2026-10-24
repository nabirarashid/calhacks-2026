"""Onshape HTTP client: auth, manual redirects, retries, ledger (S1).

Every request is charged to the ledger BEFORE it is sent, redirect follow-ups
included, because the usage page counts them until the spike proves otherwise.

Nothing here knows about fins. It speaks paths and returns bytes.
"""
import os
from typing import Dict, Optional, Tuple
from urllib.parse import quote

import requests
from requests.auth import HTTPBasicAuth

from cad.ledger import Ledger

API_BASE = "https://cad.onshape.com/api/v10"
TIMEOUT_S = 20.0
STL_ACCEPT = "application/vnd.onshape.v1+octet-stream"


class OnshapeError(RuntimeError):
    """Non-retryable API failure. Carries the status code when there is one."""

    def __init__(self, message: str, status: Optional[int] = None):
        RuntimeError.__init__(self, message)
        self.status = status


def parse_doc_url(url: str) -> Tuple[str, str, str]:
    """Pull (did, wvm_id, eid) out of an Onshape document URL.

    Accepts .../documents/{did}/w/{wid}/e/{eid} and the v/m variants.
    """
    parts = [p for p in url.split("?")[0].split("/") if p]
    did = wid = eid = None
    for i, part in enumerate(parts):
        if part == "documents" and i + 1 < len(parts):
            did = parts[i + 1]
        elif part in ("w", "v", "m") and i + 1 < len(parts):
            wid = parts[i + 1]
        elif part == "e" and i + 1 < len(parts):
            eid = parts[i + 1]
    if not (did and wid and eid):
        raise ValueError("could not parse did/wid/eid from Onshape URL")
    return did, wid, eid


def encode_configuration(values: Dict[str, object], units: Dict[str, str]) -> str:
    """Local configuration encoding: name=value+unit;name2=value2 (URL-encoded).

    Implemented locally so we spend exactly one /configurationencodings call
    during the spike to confirm the format, and none afterwards.
    """
    parts = []
    for name in sorted(values):
        val = values[name]
        unit = units.get(name, "")
        if isinstance(val, bool):
            token = "true" if val else "false"
        elif isinstance(val, float):
            token = ("%.4f" % val).rstrip("0").rstrip(".")
            if unit:
                token = token + "+" + unit
        elif isinstance(val, int):
            token = str(val)
            if unit:
                token = token + "+" + unit
        else:
            token = str(val)
        parts.append("%s=%s" % (name, token))
    return quote(";".join(parts), safe="=;+")


class OnshapeClient(object):
    """Thin, serialized client. One instance per account label."""

    def __init__(self, access_key: Optional[str] = None, secret_key: Optional[str] = None,
                 ledger: Optional[Ledger] = None, base: str = API_BASE):
        access_key = access_key or os.environ.get("ONSHAPE_ACCESS_KEY") or ""
        secret_key = secret_key or os.environ.get("ONSHAPE_SECRET_KEY") or ""
        if not access_key or not secret_key:
            raise OnshapeError(
                "ONSHAPE_ACCESS_KEY / ONSHAPE_SECRET_KEY are not set "
                "(source ~/.darwin_secrets.sh)")
        self.base = base.rstrip("/")
        self.ledger = ledger or Ledger.from_env()
        self._session = requests.Session()
        self._session.auth = HTTPBasicAuth(access_key, secret_key)

    def request(self, method: str, path: str, purpose: str,
                path_template: Optional[str] = None,
                params: Optional[Dict[str, str]] = None,
                headers: Optional[Dict[str, str]] = None,
                follow_redirect: bool = True) -> requests.Response:
        """Charge, send, and optionally follow one authenticated redirect.

        The ledger is charged before each hop. Connection errors are retried
        once; 4xx responses never are.
        """
        url = path if path.startswith("http") else self.base + path
        seq = self.ledger.charge(purpose, method, path_template or path)
        resp = self._send(method, url, params, headers)
        self.ledger.set_status(seq, resp.status_code)

        if follow_redirect and resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            if not location:
                raise OnshapeError("redirect with no Location header", resp.status_code)
            seq2 = self.ledger.charge(purpose, method, "(redirect)")
            resp = self._send(method, location, None, headers)
            self.ledger.set_status(seq2, resp.status_code)

        if resp.status_code >= 400:
            raise OnshapeError("%s %s -> HTTP %d" % (method, path_template or path,
                                                     resp.status_code),
                               resp.status_code)
        return resp

    def _send(self, method: str, url: str, params, headers) -> requests.Response:
        last = None
        for attempt in (0, 1):
            try:
                return self._session.request(
                    method, url, params=params, headers=headers,
                    timeout=TIMEOUT_S, allow_redirects=False)
            except requests.exceptions.RequestException as exc:
                last = exc                      # connection-level only; no 4xx retry
                if attempt == 1:
                    break
        raise OnshapeError("connection failed: %s" % last)

    # ---- endpoints used by the spike and by build_geometry ----

    def get_configuration(self, did: str, wid: str, eid: str,
                          purpose: str = "discover") -> Dict:
        """Configuration parameter ids, types and ranges. 1 call."""
        return self.request(
            "GET", "/elements/d/%s/w/%s/e/%s/configuration" % (did, wid, eid),
            purpose, path_template="/elements/d/{did}/w/{wid}/e/{eid}/configuration",
        ).json()

    def get_features(self, did: str, wid: str, eid: str,
                     purpose: str = "discover") -> Dict:
        """Feature list, for the assignVariable fallback path. 1 call."""
        return self.request(
            "GET", "/partstudios/d/%s/w/%s/e/%s/features" % (did, wid, eid),
            purpose, path_template="/partstudios/d/{did}/w/{wid}/e/{eid}/features",
        ).json()

    def export_stl(self, did: str, wid: str, eid: str,
                   configuration: Optional[str] = None,
                   purpose: str = "build") -> str:
        """Configured STL export. 1 call, plus 1 more if it redirects."""
        params = {"units": "millimeter"}
        if configuration:
            params["configuration"] = configuration
        resp = self.request(
            "GET", "/partstudios/d/%s/w/%s/e/%s/stl" % (did, wid, eid), purpose,
            path_template="/partstudios/d/{did}/w/{wid}/e/{eid}/stl",
            params=params, headers={"Accept": STL_ACCEPT},
        )
        return resp.text
