"""Project registry and maturity rules (PLAN.md v3 P1-2, B.5, B.6).

Committed projects live in projects/<project_id>/r<N>.json; projects onboarded at runtime
(the wizard) live in .darwin/projects/<project_id>/r<N>.json and are never committed.
Revisions are immutable: every edit writes r<N+1>. Maturity is computed by deterministic
rules from the manifest plus recorded evidence; an LLM confidence never moves a level.
An edit can only keep or lower the level; only activate() raises it, with evidence.
"""
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

from shared.manifest import (
    PERMITTED_BY_LEVEL, BlockingQuestion, ManifestUpdate, ProbeResult, ProjectManifest, ProjectSummary,
    RevisionNote, SourceRef,
)

ROOT = Path(__file__).resolve().parent.parent
_REV = re.compile(r"^r(\d+)\.json$")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")
_PATH = re.compile(r"^([a-z_]+)(?:\[(\d+)\])?(?:\.([a-z_]+))?$")


class ActivationEvidence(BaseModel):
    """What activate() needs beyond the manifest; produced by onboarding (P2-C1) or a test."""
    adapter_findings: Optional[List[BlockingQuestion]] = None   # None = adapters not consulted yet
    probes: List[ProbeResult] = Field(default_factory=list)
    baseline_reproduced: bool = False
    golden_tests: List[str] = Field(default_factory=list)       # ids of green golden-test suites
    live_write: Optional[str] = None                            # id of the recorded smoke write (level 4)


def _probe_ok(probes: List[ProbeResult]) -> bool:
    seed = [p for p in probes if p.case == "seed"]
    return bool(seed) and all(
        p.geometry.status == "ready" and p.evidence is not None and p.evidence.checks
        and all(c.passed is True for c in p.evidence.checks) for p in probes)


def compute_maturity(m: ProjectManifest, ev: Optional[ActivationEvidence] = None,
                     env: Optional[Dict[str, str]] = None) -> Tuple[int, List[str], List[str]]:
    """B.5 rules. Returns (level, evidence lines, reasons the next level is blocked)."""
    env = dict(os.environ) if env is None else env
    ev = ev or ActivationEvidence()
    got, blocked = [], []  # type: List[str], List[str]

    if not m.design_space.parameters:
        return 0, got, ["no configuration inputs found"]
    got.append("inventory: %d configuration inputs" % len(m.design_space.parameters))

    unconfirmed = [s.name for s in m.semantics if not s.confirmed]
    open2 = [q.id for q in m.open_questions if q.required_for <= 2]
    referenced = {r for lc in m.load_cases for r in ([lc.applied_at] if lc.applied_at else []) + lc.fixtures}
    missing_if = sorted(referenced - {p.id for p in m.protected})
    if unconfirmed:
        blocked.append("unconfirmed parameter meanings: %s" % ", ".join(unconfirmed))
    if open2:
        blocked.append("open questions: %s" % ", ".join(open2))
    if missing_if:
        blocked.append("load cases reference undefined interfaces: %s" % ", ".join(missing_if))
    if blocked:
        return 1, got, blocked
    got.append("semantics confirmed (%d)" % len(m.semantics))

    if m.domain_pack is None:
        blocked.append("no installed domain pack matches this object")
    if m.analysis is None:
        blocked.append("no analysis plan")
    if m.material is not None and not m.material.confirmed:
        blocked.append("material not confirmed")
    if any(not lc.confirmed for lc in m.load_cases):
        blocked.append("load case not confirmed")
    open3 = [q.id for q in m.open_questions if q.required_for <= 3]
    if open3:
        blocked.append("open questions: %s" % ", ".join(open3))
    if ev.adapter_findings is None:
        blocked.append("solver adapters not consulted")
    elif ev.adapter_findings:
        blocked.append("adapter needs: %s" % ", ".join(q.id for q in ev.adapter_findings))
    if not _probe_ok(ev.probes):
        blocked.append("seed/probe regeneration not verified")
    if not ev.baseline_reproduced:
        blocked.append("baseline evaluation not reproduced")
    if not ev.golden_tests:
        blocked.append("no green golden tests recorded for the adapter")
    if blocked:
        return 2, got, blocked
    got += ["adapters accept the manifest", "probes passed (%d cases)" % len(ev.probes), "baseline reproduced"]
    got += ["golden:%s" % g for g in ev.golden_tests]

    ref = m.cad.write_target_ref
    url = env.get(ref, "") if ref else ""
    if not ref:
        blocked.append("no write target")
    elif "/w/" not in url:
        blocked.append("write target %s is not set to a workspace (/w/) URL" % ref)
    if env.get("DARWIN_ONSHAPE_WRITE_ISOLATED") != "1":
        blocked.append("isolated workspace not acknowledged (DARWIN_ONSHAPE_WRITE_ISOLATED)")
    if not ev.live_write:
        blocked.append("no recorded live smoke write for this document")
    if blocked:
        return 3, got, blocked
    got.append("live_write:%s" % ev.live_write)
    return 4, got, []


def _set_path(data: Dict[str, Any], path: str, value: Any) -> str:
    """Set 'material', 'load_cases[0].vector_n' style paths. Returns the top-level key touched."""
    m = _PATH.match(path)
    if not m:
        raise ValueError("unsupported answer path %r" % path)
    key, idx, sub = m.group(1), m.group(2), m.group(3)
    if idx is None and sub is None:
        data[key] = value
        return key
    if idx is None:
        data.setdefault(key, {})[sub] = value  # type: ignore[index]
        return key
    items = data.setdefault(key, [])
    i = int(idx)
    if i >= len(items):
        raise ValueError("%s[%d] does not exist" % (key, i))
    if sub is None:
        items[i] = value
    else:
        items[i][sub] = value
    return key


class ProjectRegistry:
    def __init__(self, root: Optional[Path] = None, runtime: Optional[Path] = None,
                 env: Optional[Callable[[], Dict[str, str]]] = None) -> None:
        self.root = root or Path(os.environ.get("DARWIN_PROJECTS_DIR") or (ROOT / "projects"))
        self.runtime = runtime or (Path(os.environ.get("DARWIN_CACHE_DIR", ".darwin")) / "projects")
        self._env = env or (lambda: dict(os.environ))
        self._lock = threading.Lock()
        self._projects = {}  # type: Dict[str, ProjectManifest]
        self._where = {}  # type: Dict[str, Path]
        self.reload()

    # ---------------------------------------------------------------- loading

    def reload(self) -> None:
        with self._lock:
            self._projects.clear()
            self._where.clear()
            for base in (self.root, self.runtime):
                if not base.is_dir():
                    continue
                for d in sorted(p for p in base.iterdir() if p.is_dir()):
                    revs = sorted((int(_REV.match(f.name).group(1)), f) for f in d.iterdir() if _REV.match(f.name))
                    if not revs:
                        continue
                    m = ProjectManifest.model_validate_json(revs[-1][1].read_text())
                    if m.project_id != d.name or m.revision != revs[-1][0]:
                        raise ValueError("%s: project_id/revision must match its path" % revs[-1][1])
                    if m.project_id in self._projects:
                        raise ValueError("duplicate project id %s" % m.project_id)
                    self._projects[m.project_id] = m
                    self._where[m.project_id] = base

    def ids(self) -> List[str]:
        return sorted(self._projects)

    def get(self, project_id: str) -> ProjectManifest:
        try:
            return self._projects[project_id]
        except KeyError:
            raise KeyError("unknown project %s" % project_id)

    def summaries(self) -> List[ProjectSummary]:
        return [ProjectSummary(project_id=m.project_id, name=m.name, revision=m.revision,
                               maturity=m.authority.maturity, domain_pack=m.domain_pack)
                for m in (self._projects[i] for i in self.ids())]

    # ---------------------------------------------------------------- writing

    def _write(self, m: ProjectManifest, base: Path) -> None:
        for ref in (m.cad.doc_ref, m.cad.write_target_ref):
            if ref is not None and not _ENV_NAME.match(ref) and not ref.startswith("runtime:"):
                raise ValueError("cad refs must be env var names or runtime refs, never URLs")
        if m.design_space.source.doc_url:
            raise ValueError("design_space.source.doc_url must be empty in a stored manifest")
        d = base / m.project_id
        d.mkdir(parents=True, exist_ok=True)
        path = d / ("r%d.json" % m.revision)
        if path.exists():
            raise FileExistsError("%s already exists; revisions are immutable" % path)
        path.write_text(m.model_dump_json(indent=2) + "\n")
        self._projects[m.project_id] = m
        self._where[m.project_id] = base

    def create(self, m: ProjectManifest, *, runtime: bool = True) -> ProjectManifest:
        """Store a new project (revision 1). Wizard drafts go to the runtime dir."""
        with self._lock:
            if m.project_id in self._projects:
                raise ValueError("project %s already exists" % m.project_id)
            if m.revision != 1:
                raise ValueError("a new project starts at revision 1")
            lvl, _, _ = compute_maturity(m, env=self._env())
            lvl = min(lvl, m.authority.maturity)
            m = m.model_copy(update={"authority": m.authority.model_copy(update={
                "maturity": lvl, "permitted": PERMITTED_BY_LEVEL[lvl]})})
            self._write(m, self.runtime if runtime else self.root)
            return m

    def _next(self, m: ProjectManifest, nxt: ProjectManifest, by: str, change: str, level: int,
              evidence: Optional[List[str]] = None) -> ProjectManifest:
        auth = nxt.authority.model_copy(update={"maturity": level, "permitted": PERMITTED_BY_LEVEL[level]})
        if evidence is not None:
            auth = auth.model_copy(update={"evidence": evidence})
        out = nxt.model_copy(update={
            "revision": m.revision + 1, "authority": auth,
            "history": m.history + [RevisionNote(revision=m.revision + 1, at=time.strftime("%Y-%m-%dT%H:%M:%S"),
                                                 by=by, change=change)]})
        out = ProjectManifest.model_validate(out.model_dump(mode="json"))   # re-validate the whole thing
        self._write(out, self._where[m.project_id])
        return out

    def update(self, project_id: str, body: ManifestUpdate) -> ProjectManifest:
        """Apply engineer edits/answers as a new revision. Stale revision -> ValueError (HTTP 409)."""
        with self._lock:
            m = self.get(project_id)
            if body.revision != m.revision:
                raise ValueError("stale revision %d (current %d)" % (body.revision, m.revision))
            data = m.model_dump(mode="json")
            touched = []  # type: List[str]
            for name in ("semantics", "protected", "requirements"):
                val = getattr(body, name)
                if val is not None:
                    data[name] = [v.model_dump(mode="json") for v in val]
                    touched.append(name)
            engineer = SourceRef(kind="engineer", source_id="engineer:%s" % body.by).model_dump(mode="json")
            for path, value in body.answers.items():
                key = _set_path(data, path, value)
                touched.append(path)
                # An answered engineering input is confirmed by the person who answered it.
                if key == "material" and isinstance(data.get("material"), dict):
                    data["material"].setdefault("source", engineer)
                    data["material"]["confirmed"] = True
                if key == "load_cases":
                    i = int(_PATH.match(path).group(2) or 0)
                    data["load_cases"][i].setdefault("source", engineer)
                    data["load_cases"][i]["confirmed"] = True
            answered = set(body.answers)
            data["open_questions"] = [q for q in data["open_questions"] if q["field"] not in answered]
            nxt = ProjectManifest.model_validate(data)
            lvl, _, _ = compute_maturity(nxt, env=self._env())
            lvl = min(lvl, m.authority.maturity)          # edits never raise the level
            return self._next(m, nxt, body.by, body.note or "edited %s" % ", ".join(touched) or "no-op", lvl)

    def activate(self, project_id: str, ev: ActivationEvidence, by: str = "darwin") \
            -> Tuple[ProjectManifest, List[str]]:
        """Recompute the level from the rules plus evidence; writes a revision only if it changed."""
        with self._lock:
            m = self.get(project_id)
            lvl, got, blocked = compute_maturity(m, ev, env=self._env())
            if lvl == m.authority.maturity and got == m.authority.evidence:
                return m, blocked
            return self._next(m, m, by, "activate: level %d -> %d" % (m.authority.maturity, lvl), lvl, got), blocked


__all__ = ["ActivationEvidence", "compute_maturity", "ProjectRegistry"]
