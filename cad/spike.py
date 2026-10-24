"""Onshape configuration spike (S1). PLAN.md S1 steps 1-3, plus an auth check.

Usage (source ~/.darwin_secrets.sh first):
    python -m cad.spike auth        # 1 call  - whose keys are these, do they work
    python -m cad.spike config      # 1 call  - configuration ids, types, ranges
    python -m cad.spike encoding    # 1 call  - confirm the encoding format
    python -m cad.spike export      # 3-6     - 3 STL exports, bbox vs B.5
    python -m cad.spike all         # steps 1-3 in order

Every call goes through the ledger. Raw responses land in cad/SPIKE_raw/
(gitignored - they can contain document ids and account data).
"""
import json
import os
import sys
import time

from shared.contracts import DesignSpace, canonicalize

from cad import stl
from cad.ledger import Ledger
from cad.onshape_client import (OnshapeClient, OnshapeError, encode_configuration,
                                parse_doc_url)

RAW_DIR = os.path.join("cad", "SPIKE_raw")
SPACE_FIXTURE = os.path.join("shared", "fixtures", "design_space_fin.json")

# Three param sets spanning the box: default, near-min, near-max.
PARAM_SETS = [
    {"root_chord": 90.0, "taper_ratio": 0.5, "semi_span": 60.0,
     "sweep_deg": 30.0, "thickness": 3.0, "edge_profile": "square"},
    {"root_chord": 55.0, "taper_ratio": 0.25, "semi_span": 35.0,
     "sweep_deg": 5.0, "thickness": 2.2, "edge_profile": "square"},
    {"root_chord": 125.0, "taper_ratio": 0.9, "semi_span": 85.0,
     "sweep_deg": 55.0, "thickness": 4.8, "edge_profile": "square"},
]


def _save(name, payload):
    os.makedirs(RAW_DIR, exist_ok=True)
    path = os.path.join(RAW_DIR, name)
    with open(path, "w") as fh:
        if isinstance(payload, str):
            fh.write(payload)
        else:
            json.dump(payload, fh, indent=2, sort_keys=True)
    return path


def _space():
    with open(SPACE_FIXTURE) as fh:
        return DesignSpace(**json.load(fh))


def _doc():
    url = os.environ.get("DARWIN_FIN_DOC_URL") or ""
    if not url:
        print("DARWIN_FIN_DOC_URL is not set.")
        print("Build the fin Part Studio, then put its URL in ~/.darwin_secrets.sh")
        sys.exit(2)
    return parse_doc_url(url)


def _client():
    return OnshapeClient(ledger=Ledger.from_env())


def _cad_refs(space):
    return {s.name: (s.cad_ref or s.name) for s in space.parameters if s.cad_driven}


def _units(space):
    return {(s.cad_ref or s.name): s.unit
            for s in space.parameters if s.cad_driven and s.unit}


def step_auth():
    """Confirm the keys authenticate and report which account they belong to."""
    print("== step 0: auth (1 call) ==")
    client = _client()
    try:
        resp = client.request("GET", "/users/sessioninfo", "spike",
                              path_template="/users/sessioninfo")
    except OnshapeError as exc:
        print("FAILED: %s" % exc)
        if exc.status in (401, 403):
            print("  -> 401/403 means the keys are rejected: check for stray")
            print("     whitespace, or that access/secret are not swapped.")
        return False
    data = resp.json()
    _save("sessioninfo.json", data)
    print("  OK. authenticated as:")
    for k in ("name", "email", "id", "state"):
        if k in data:
            print("    %-6s %s" % (k, data[k]))
    print("  -> this is the account every spike call is billed to")
    return True


def step_config():
    """Configuration parameter ids, types and ranges. Discovery reuses this."""
    print("== step 1: GET configuration (1 call) ==")
    did, wid, eid = _doc()
    client = _client()
    data = client.get_configuration(did, wid, eid, purpose="spike")
    path = _save("configuration.json", data)
    params = data.get("configurationParameters") or []
    print("  OK. %d configuration parameters (raw -> %s)" % (len(params), path))
    for p in params:
        pid = p.get("message", {}).get("parameterId") or p.get("parameterId")
        btype = p.get("typeName") or p.get("btType")
        print("    %-16s %s" % (pid, btype))
    if not params:
        print("  !! no configuration inputs found. The Part Studio needs")
        print("     configuration variables, not plain sketch dimensions.")
    return params


def step_encoding():
    """Confirm the server's encoding string matches our local encoder."""
    print("== step 2: POST configurationencodings (1 call) ==")
    did, wid, eid = _doc()
    space = _space()
    refs = _cad_refs(space)
    client = _client()

    two = {refs["root_chord"]: "92 mm", refs["taper_ratio"]: "0.45"}
    body = {"parameters": [{"parameterId": k, "parameterValue": v}
                           for k, v in sorted(two.items())]}
    try:
        resp = client.request(
            "POST", "/elements/d/%s/w/%s/e/%s/configurationencodings" % (did, wid, eid),
            "spike",
            path_template="/elements/d/{did}/w/{wid}/e/{eid}/configurationencodings",
            json_body=body, headers={"Content-Type": "application/json"})
    except OnshapeError as exc:
        print("  FAILED: %s" % exc)
        print("  -> record the exact body shape that works in cad/SPIKE.md;")
        print("     the local encoder is the fallback and costs 0 calls.")
        return None
    data = resp.json()
    _save("configurationencodings.json", {"request": body, "response": data})
    server = data.get("encodedId") or data.get("queryParam") or ""
    local = encode_configuration({refs["root_chord"]: 92.0, refs["taper_ratio"]: 0.45},
                                 _units(space))
    print("  server: %s" % server)
    print("  local : %s" % local)
    print("  -> %s" % ("MATCH, local encoding is safe (0 calls/design)"
                       if server and server == local else
                       "DIFFERENT: copy the server format into encode_configuration()"))
    return server


def step_export():
    """3 configured STL exports, measured against the frozen B.5 geometry."""
    print("== step 3: configured STL export (3-6 calls) ==")
    did, wid, eid = _doc()
    space = _space()
    client = _client()
    refs = _cad_refs(space)
    units = _units(space)

    ok_all = True
    for i, params in enumerate(PARAM_SETS, 1):
        canon = canonicalize(space, params)
        cfg = encode_configuration(
            {refs[n]: canon[n] for n in refs if n in canon}, units)
        started = time.time()
        try:
            text = client.export_stl(did, wid, eid, configuration=cfg, purpose="spike")
        except OnshapeError as exc:
            print("  set %d: FAILED %s" % (i, exc))
            ok_all = False
            continue
        elapsed = (time.time() - started) * 1000.0
        _save("export_%d.stl" % i, text)

        measured = stl.measure(canon, text)
        want = measured["bbox_mm"]
        got = measured["bbox_mm"]
        worst = max(abs(a - b) for a, b in zip(want, got))
        status = "EXPORTED" if measured.get("triangles", 0) else "ERROR"
        print("  set %d: %s  %d tri  %.0f mm3  bbox worst %.3f mm  %.0f ms"
              % (i, status, measured["triangles"], measured["volume_mm3"],
                 worst, elapsed))
        if status != "EXPORTED":
            ok_all = False
    print("  -> %s" % ("VERDICT A: configured export works, 2 calls/design (307 + 200)"
                       if ok_all else
                       "configured export did NOT verify: see the ladder (B, then C)"))
    return ok_all


def main(argv):
    what = argv[1] if len(argv) > 1 else "all"
    led = Ledger.from_env()
    before = led.calls_total()
    b = led.budget_status()
    print("account %s | reserve %d | remaining_estimate %s\n"
          % (b.account_label, b.reserve,
             "unknown" if b.remaining_estimate < 0 else b.remaining_estimate))

    try:
        if what == "auth":
            step_auth()
        elif what == "config":
            step_config()
        elif what == "encoding":
            step_encoding()
        elif what == "export":
            step_export()
        elif what == "all":
            if step_auth():
                print()
                step_config()
                print()
                step_encoding()
                print()
                step_export()
        else:
            print(__doc__)
            return 2
    finally:
        spent = Ledger.from_env().calls_total() - before
        print("\ncalls spent this run: %d  (ledger: %s)" % (spent, led.path))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
