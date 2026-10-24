"""Onshape HTTP client: auth, manual redirects, retries, ledger (S1).

Every request is charged to the ledger BEFORE it is sent, redirect follow-ups
included, because the usage page counts them until the spike proves otherwise.

Nothing here knows about fins. It speaks paths and returns bytes.
"""
import copy
import math
import os
import time
from typing import Dict, Optional, Tuple
from urllib.parse import quote, urljoin, urlsplit

import requests
from requests.auth import HTTPBasicAuth

from cad.ledger import Ledger

API_BASE = "https://cad.onshape.com/api/v10"
TIMEOUT_S = 20.0
STL_ACCEPT = "application/vnd.onshape.v1+octet-stream"
QUANTITY_TYPES = {
    "BTMConfigurationParameterQuantity-1826",
    "BTMConfigurationParameterQuantity",
}
_NUMERIC_TOLERANCE = 1e-9


def _parameter_id(row):
    if not isinstance(row, dict):
        return None
    return row.get("parameterId") or (row.get("message") or {}).get("parameterId")


def _is_quantity(parameter):
    return (parameter.get("typeName") in QUANTITY_TYPES
            or parameter.get("btType") in QUANTITY_TYPES
            or parameter.get("message", {}).get("typeName") in QUANTITY_TYPES)


def _as_finite_number(value, parameter_id):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("configuration value for %s must be numeric" % parameter_id)
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("configuration value for %s must be finite" % parameter_id)
    return number


def _close(a, b):
    return math.isclose(float(a), float(b), rel_tol=_NUMERIC_TOLERANCE,
                        abs_tol=_NUMERIC_TOLERANCE)


def _quantity_defaults(configuration):
    parameters = configuration.get("configurationParameters")
    if not isinstance(parameters, list):
        raise ValueError("configuration response has no configurationParameters list")
    out = {}
    for parameter in parameters:
        if not isinstance(parameter, dict):
            raise ValueError("configuration response contains malformed parameter")
        pid = _parameter_id(parameter)
        if not pid:
            raise ValueError("configuration parameter lacks parameterId")
        if pid in out:
            raise ValueError("configuration response repeats parameterId %s" % pid)
        if _is_quantity(parameter):
            range_default = parameter.get("rangeAndDefault")
            if not isinstance(range_default, dict) or "defaultValue" not in range_default:
                raise ValueError("quantity parameter %s lacks rangeAndDefault.defaultValue" % pid)
            out[pid] = (parameter, range_default)
    return out


def build_configuration_update(configuration, expected):
    """Build a guarded quantity-only update from a fresh configuration GET.

    The GET body is copied intact so API metadata and unmodified inputs survive.
    Values are expressed in the units declared on each current-configuration row.
    """
    if not isinstance(configuration, dict):
        raise ValueError("configuration response must be an object")
    if not isinstance(expected, dict) or not expected:
        raise ValueError("configuration update requires expected quantity values")
    for field in ("sourceMicroversion", "serializationVersion"):
        if not isinstance(configuration.get(field), str) or not configuration[field].strip():
            raise ValueError("configuration response lacks %s" % field)
    library_version = configuration.get("libraryVersion")
    if isinstance(library_version, bool) or not isinstance(library_version, int):
        raise ValueError("configuration response lacks integer libraryVersion")
    if configuration.get("microversionSkew") is True:
        raise ValueError("cannot update configuration with microversionSkew=true")

    quantity_params = _quantity_defaults(configuration)
    unknown = sorted(pid for pid in expected if pid not in quantity_params)
    if unknown:
        raise ValueError("target ids are not quantity parameters: %s" % ", ".join(unknown))

    rows = configuration.get("currentConfiguration")
    if not isinstance(rows, list):
        raise ValueError("configuration response has no currentConfiguration list")
    row_by_id = {}
    for row in rows:
        pid = _parameter_id(row)
        if not pid or pid in row_by_id:
            raise ValueError("configuration response has missing or duplicate current parameterId")
        row_by_id[pid] = row

    result = copy.deepcopy(configuration)
    result["btType"] = "BTConfigurationUpdateCall-2933"
    result["rejectMicroversionSkew"] = True
    # A false/absent response flag is not copied as permission to accept skew.
    for pid, raw_value in expected.items():
        if pid not in row_by_id:
            raise ValueError("current configuration lacks target parameter %s" % pid)
        value = _as_finite_number(raw_value, pid)
        parameter, range_default = quantity_params[pid]
        low = range_default.get("minValue")
        high = range_default.get("maxValue")
        if low is not None and value < _as_finite_number(low, pid):
            raise ValueError("configuration value for %s is below minValue" % pid)
        if high is not None and value > _as_finite_number(high, pid):
            raise ValueError("configuration value for %s is above maxValue" % pid)

        row = next(r for r in result["currentConfiguration"] if _parameter_id(r) == pid)
        units = row.get("units", row.get("unit", range_default.get("units", ""))) or ""
        raw_unit = str(units).strip().lower()
        unit_aliases = {
            "": "", "unitless": "", "dimensionless": "", "none": "",
            "millimeter": "mm", "millimeters": "mm", "mm": "mm",
            "degree": "deg", "degrees": "deg", "deg": "deg",
        }
        if raw_unit not in unit_aliases:
            raise ValueError("unsupported configuration unit for %s: %s" % (pid, units))
        unit_text = unit_aliases[raw_unit]
        expression = ("%.15g" % value) + ((" " + unit_text) if unit_text else "")
        row["value"] = value
        row["expression"] = expression
        default_row = next(p for p in result["configurationParameters"]
                           if _parameter_id(p) == pid)
        default_row["rangeAndDefault"]["defaultValue"] = value
    return result


def configuration_values(configuration):
    """Extract numeric current values and default values for quantity inputs."""
    current_rows = configuration.get("currentConfiguration")
    if not isinstance(current_rows, list):
        raise ValueError("configuration response has no currentConfiguration list")
    current = {}
    for row in current_rows:
        pid = _parameter_id(row)
        if not pid or pid in current or "value" not in row:
            raise ValueError("configuration current row lacks unique parameterId/value")
        current[pid] = row["value"]
    defaults = {}
    for pid, (_parameter, range_default) in _quantity_defaults(configuration).items():
        defaults[pid] = range_default["defaultValue"]
    return {"current": current, "defaults": defaults}


def verify_configuration_update(before, after, expected):
    """Verify current/default values and require the write to advance microversion."""
    if not isinstance(expected, dict) or not expected:
        raise ValueError("configuration verification requires expected values")
    before_mv = before.get("sourceMicroversion")
    after_mv = after.get("sourceMicroversion")
    if not before_mv or not after_mv:
        raise ValueError("configuration response lacks sourceMicroversion")
    before_values = configuration_values(before)
    after_values = configuration_values(after)
    missing = []
    mismatched = {}
    for pid, value in expected.items():
        target = _as_finite_number(value, pid)
        for category in ("current", "defaults"):
            observed = after_values[category].get(pid)
            if observed is None:
                missing.append("%s:%s" % (category, pid))
            elif not _close(_as_finite_number(observed, pid), target):
                mismatched["%s:%s" % (category, pid)] = {
                    "expected": target, "observed": observed,
                }
    return {
        "ok": not missing and not mismatched and after_mv != before_mv,
        "missing": sorted(missing), "mismatched": mismatched,
        "microversion_changed": after_mv != before_mv,
        "source_microversion": after_mv,
    }


def build_configuration_restore(current, snapshot):
    """Restore quantity current/default values from a pre-write snapshot.

    The current response supplies a fresh source microversion and API metadata;
    snapshot values supply only the state being restored.
    """
    if not isinstance(current, dict) or not isinstance(snapshot, dict):
        raise ValueError("configuration restore requires object snapshots")
    current_values = configuration_values(current)
    saved_values = configuration_values(snapshot)
    result = copy.deepcopy(current)
    result["btType"] = "BTConfigurationUpdateCall-2933"
    result["rejectMicroversionSkew"] = True
    parameter_rows = {pid: row for pid, (row, _range_default)
                      in _quantity_defaults(result).items()}
    current_rows = { _parameter_id(row): row for row in result.get("currentConfiguration", []) }
    if set(saved_values["defaults"]) != set(parameter_rows):
        raise ValueError("snapshot/current quantity parameter sets differ")
    for pid, saved_default in saved_values["defaults"].items():
        if pid not in current_rows or pid not in current_values["current"]:
            raise ValueError("current configuration lacks quantity parameter %s" % pid)
        saved_current = configuration_values(snapshot)["current"].get(pid)
        if saved_current is None:
            raise ValueError("snapshot lacks current value for %s" % pid)
        current_rows[pid]["value"] = saved_current
        unit = current_rows[pid].get("units", current_rows[pid].get("unit", "")) or ""
        aliases = {"millimeter": "mm", "millimeters": "mm", "mm": "mm",
                   "degree": "deg", "degrees": "deg", "deg": "deg",
                   "unitless": "", "dimensionless": "", "none": "", "": ""}
        raw_unit = str(unit).strip().lower()
        if raw_unit not in aliases:
            raise ValueError("unsupported configuration unit for %s: %s" % (pid, unit))
        unit_text = aliases[raw_unit]
        current_rows[pid]["expression"] = ("%.15g" % float(saved_current)) + (" " + unit_text if unit_text else "")
        parameter_rows[pid]["rangeAndDefault"]["defaultValue"] = saved_default
    return result


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


def parse_workspace_url(url: str) -> Tuple[str, str, str]:
    """Parse an editable workspace URL and reject immutable version/microversion URLs."""
    parts = [p for p in url.split("?")[0].split("/") if p]
    try:
        marker = next(i for i, part in enumerate(parts) if part in ("w", "v", "m"))
    except StopIteration:
        raise ValueError("Onshape write target has no workspace marker")
    if parts[marker] != "w":
        raise ValueError("Onshape write target must be a /w/ workspace URL")
    return parse_doc_url(url)


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
                json_body: Optional[Dict] = None,
                follow_redirect: bool = True) -> requests.Response:
        """Charge, send, and optionally follow one authenticated redirect.

        The ledger is charged before each hop. Connection errors are retried
        once; 4xx responses never are.
        """
        url = path if path.startswith("http") else self.base + path
        seq = self.ledger.charge(purpose, method, path_template or path)
        resp = self._send(method, url, params, headers, json_body)
        self.ledger.set_status(seq, resp.status_code)

        if follow_redirect and resp.status_code in (301, 302, 303, 307, 308):
            location = resp.headers.get("Location")
            if not location:
                raise OnshapeError("redirect with no Location header", resp.status_code)
            location = urljoin(url, location)
            seq2 = self.ledger.charge(purpose, method, "(redirect)")
            original, target = urlsplit(url), urlsplit(location)
            same_origin = ((original.scheme.lower(), original.hostname, original.port)
                           == (target.scheme.lower(), target.hostname, target.port))
            if same_origin:
                resp = self._send(method, location, None, headers, json_body)
            else:
                # Export downloads may redirect to object storage. Never carry
                # Onshape auth or cookies to a different origin.
                if target.scheme.lower() != "https" or not target.hostname:
                    raise OnshapeError("refusing insecure external redirect")
                clean_headers = {k: v for k, v in (headers or {}).items()
                                 if k.lower() not in ("authorization", "cookie", "proxy-authorization")}
                external = requests.Session()
                try:
                    external.auth = None
                    external.cookies.clear()
                    resp = external.request(method, location, headers=clean_headers,
                                            timeout=TIMEOUT_S, allow_redirects=False)
                except requests.exceptions.RequestException as exc:
                    raise OnshapeError("external download connection failed: %s" % type(exc).__name__)
                finally:
                    external.close()
            self.ledger.set_status(seq2, resp.status_code)

        if resp.status_code >= 400:
            raise OnshapeError("%s %s -> HTTP %d" % (method, path_template or path,
                                                     resp.status_code),
                               resp.status_code)
        return resp

    def _send(self, method: str, url: str, params, headers,
              json_body=None) -> requests.Response:
        last = None
        for attempt in (0, 1):
            try:
                return self._session.request(
                    method, url, params=params, headers=headers, json=json_body,
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

    def update_configuration(self, did: str, wid: str, eid: str,
                             configuration: Dict,
                             purpose: str = "commit") -> Dict:
        """POST a complete, caller-vetted configuration representation.

        Onshape documents ``POST /elements/.../configuration`` as the update
        endpoint.  This method deliberately does *not* manufacture its body:
        quantity/list parameter objects are document- and API-version-specific,
        so callers must start from a developer-verified GET representation.
        Keeping that decision outside the transport layer prevents a guessed
        payload from changing a real document.
        """
        if not isinstance(configuration, dict) or not configuration:
            raise ValueError("configuration update requires a non-empty vetted payload")
        return self.request(
            "POST", "/elements/d/%s/w/%s/e/%s/configuration" % (did, wid, eid),
            purpose, path_template="/elements/d/{did}/w/{wid}/e/{eid}/configuration",
            headers={"Content-Type": "application/json"}, json_body=configuration,
        ).json()

    @staticmethod
    def current_configuration_values(configuration: Dict) -> Dict[str, object]:
        """Read the documented ``currentConfiguration`` values from a response.

        This intentionally refuses malformed entries instead of treating a
        missing value as a successful verification.
        """
        rows = configuration.get("currentConfiguration")
        if not isinstance(rows, list):
            raise ValueError("configuration response has no currentConfiguration list")
        out = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("configuration response contains a malformed value")
            parameter_id = row.get("parameterId")
            if not isinstance(parameter_id, str) or not parameter_id or "value" not in row:
                raise ValueError("configuration response entry lacks parameterId/value")
            if parameter_id in out:
                raise ValueError("configuration response repeats a parameterId")
            out[parameter_id] = row["value"]
        return out

    def verify_configuration(self, did: str, wid: str, eid: str,
                             expected: Dict[str, object],
                             purpose: str = "commit_verify") -> Dict:
        """Read back configuration values and return a strict verification result.

        A caller should create a named version only after ``ok`` is true and a
        separately exported STL has passed its geometry sanity check.
        """
        if not isinstance(expected, dict) or not expected:
            raise ValueError("configuration verification requires expected values")
        observed = self.current_configuration_values(
            self.get_configuration(did, wid, eid, purpose=purpose))
        missing = sorted(key for key in expected if key not in observed)
        mismatched = {
            key: {"expected": expected[key], "observed": observed[key]}
            for key in expected
            if key in observed and observed[key] != expected[key]
        }
        return {
            "ok": not missing and not mismatched,
            "missing": missing,
            "mismatched": mismatched,
        }

    def create_version(self, did: str, wid: str, name: str,
                       purpose: str = "commit_version") -> Dict:
        """Create a named version from a workspace using Onshape's v10 API.

        This is intentionally a primitive, not an implicit follow-up to a
        configuration write.  The caller must verify both the write and the
        regenerated geometry first.
        """
        if not isinstance(name, str) or not name.strip():
            raise ValueError("version name is required")
        return self.request(
            "POST", "/documents/d/%s/versions" % did, purpose,
            path_template="/documents/d/{did}/versions",
            headers={"Content-Type": "application/json"},
            json_body={"documentId": did, "workspaceId": wid, "name": name.strip()},
        ).json()

    def get_features(self, did: str, wid: str, eid: str,
                     purpose: str = "discover") -> Dict:
        """Feature list, for the assignVariable fallback path. 1 call."""
        return self.request(
            "GET", "/partstudios/d/%s/w/%s/e/%s/features" % (did, wid, eid),
            purpose, path_template="/partstudios/d/{did}/w/{wid}/e/{eid}/features",
        ).json()

    def add_feature(self, did: str, wid: str, eid: str, payload: Dict,
                    purpose: str = "build") -> Dict:
        """Add one feature from an explicitly vetted Onshape feature payload."""
        if not isinstance(payload, dict) or not payload:
            raise ValueError("feature creation requires a non-empty vetted payload")
        bt_type = payload.get("btType")
        if not isinstance(bt_type, str) or not bt_type.startswith("BTFeatureDefinitionCall"):
            raise ValueError("feature payload must have a BTFeatureDefinitionCall btType")
        return self.request(
            "POST", "/partstudios/d/%s/w/%s/e/%s/features" % (did, wid, eid),
            purpose,
            path_template="/partstudios/d/{did}/w/{wid}/e/{eid}/features",
            headers={"Content-Type": "application/json"}, json_body=payload,
        ).json()

    def copy_workspace(self, did: str, wid: str, name: str,
                       is_public: bool = False,
                       purpose: str = "build_copy") -> Dict:
        """Copy a workspace to a new document with an explicit access setting."""
        if not isinstance(name, str) or not name.strip():
            raise ValueError("workspace copy name is required")
        if not isinstance(is_public, bool):
            raise ValueError("is_public must be a boolean")
        return self.request(
            "POST", "/documents/%s/workspaces/%s/copy" % (did, wid), purpose,
            path_template="/documents/{did}/workspaces/{wid}/copy",
            headers={"Content-Type": "application/json"},
            json_body={"newName": name.strip(), "isPublic": is_public},
        ).json()

    def get_elements(self, did: str, wid: str,
                     purpose: str = "inspect") -> list:
        """List document elements. One read-only call."""
        return self.request(
            "GET", "/documents/d/%s/w/%s/elements" % (did, wid), purpose,
            path_template="/documents/d/{did}/w/{wid}/elements",
        ).json()

    def get_parts(self, did: str, wid: str, eid: str,
                  purpose: str = "inspect") -> list:
        """List Part Studio parts without thumbnails. One read-only call."""
        return self.request(
            "GET", "/parts/d/%s/w/%s" % (did, wid), purpose,
            path_template="/parts/d/{did}/w/{wid}",
            params={"elementId": eid, "withThumbnails": "false",
                    "includePropertyDefaults": "false"},
        ).json()

    def get_mass_properties(self, did: str, wid: str, eid: str,
                            purpose: str = "inspect") -> Dict:
        """Read Part Studio mass properties in Onshape's SI units. One call."""
        return self.request(
            "GET", "/partstudios/d/%s/w/%s/e/%s/massproperties" % (did, wid, eid),
            purpose,
            path_template="/partstudios/d/{did}/w/{wid}/e/{eid}/massproperties",
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

    def export_step(self, did: str, wid: str, eid: str,
                    configuration: Optional[str] = None,
                    purpose: str = "build", timeout_s: float = 45.0,
                    poll_interval_s: float = 0.5, max_polls: int = 12) -> bytes:
        """Export configured STEP using Onshape's asynchronous translation API.

        Each POST/poll/download is charged by ``request`` before it is sent.
        IDs are kept in memory and never included in exceptions or log paths.
        """
        body = {"formatName": "STEP", "storeInDocument": False,
                "translate": True}
        if configuration:
            body["configuration"] = configuration
        created = self.request(
            "POST", "/partstudios/d/%s/w/%s/e/%s/translations" % (did, wid, eid),
            purpose, path_template="/partstudios/d/{did}/w/{wid}/e/{eid}/translations",
            headers={"Content-Type": "application/json"}, json_body=body,
        ).json()
        translation_id = created.get("id") if isinstance(created, dict) else None
        if not translation_id:
            raise OnshapeError("STEP translation response lacks id")
        deadline = time.monotonic() + max(0.0, timeout_s)
        for poll in range(max_polls):
            if poll and time.monotonic() >= deadline:
                raise TimeoutError("STEP translation timed out")
            state = self.request(
                "GET", "/translations/%s" % translation_id, purpose,
                path_template="/translations/{translationId}",
            ).json()
            request_state = state.get("requestState") if isinstance(state, dict) else None
            if request_state == "FAILED":
                raise OnshapeError("STEP translation failed")
            if request_state == "DONE":
                ids = state.get("resultExternalDataIds") or []
                if not ids:
                    raise OnshapeError("STEP translation completed without output")
                result = self.request(
                    "GET", "/documents/d/%s/externaldata/%s" % (did, ids[0]), purpose,
                    path_template="/documents/d/{did}/externaldata/{fid}",
                    follow_redirect=True,
                )
                return result.content
            remaining = deadline - time.monotonic()
            if poll + 1 < max_polls and remaining > 0:
                time.sleep(min(poll_interval_s, remaining))
        raise TimeoutError("STEP translation timed out")
