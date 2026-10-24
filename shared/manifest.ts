// Darwin contracts v2 — FROZEN mirror of shared/manifest.py (tag contracts-v2).
// Field names are snake_case exactly as on the wire. Python is the source of truth.
import type { AnalysisArtifact, Constraint, DesignSpace, GeometryRef, ParamValue } from './contracts';

export type { AnalysisArtifact };

export const MANIFEST_SCHEMA = 'manifest-v1';

/** 0 unsupported · 1 inventory-only · 2 manifest-reviewed · 3 solver-ready · 4 write-enabled */
export type Maturity = 0 | 1 | 2 | 3 | 4;
export type Action = 'inspect' | 'probe' | 'simulate' | 'optimize' | 'write';

export const MATURITY_LABEL: Record<Maturity, string> = {
  0: 'unsupported',
  1: 'inventory-only',
  2: 'manifest-reviewed',
  3: 'solver-ready',
  4: 'write-enabled',
};

export const PERMITTED_BY_LEVEL: Record<Maturity, Action[]> = {
  0: [],
  1: ['inspect'],
  2: ['inspect', 'probe'],
  3: ['inspect', 'probe', 'simulate', 'optimize'],
  4: ['inspect', 'probe', 'simulate', 'optimize', 'write'],
};

// ---------------------------------------------------------------- provenance
export interface SourceRef {
  kind: 'engineer' | 'project_doc' | 'standard' | 'datasheet' | 'solver' | 'model_suggestion';
  source_id: string;
  title: string;
  version: string;
  section: string;
}

export interface RevisionNote { revision: number; at: string; by: string; change: string; }

// ---------------------------------------------------------------- engineering context
export interface ParamSemantics {
  name: string;
  cad_ref: string;
  role: 'editable' | 'fixed' | 'protected';
  meaning: string;
  confidence?: number | null;   // drafts only
  confirmed: boolean;
}

export interface ProtectedInterface {
  id: string;
  kind: 'hole' | 'face' | 'datum' | 'envelope' | 'mate_connector';
  cad_ref: string;
  check: 'position' | 'diameter' | 'bbox_contains' | 'unchanged';
  nominal: Record<string, number>;
  tolerance_mm: number;
}

export interface MaterialSpec {
  name: string;
  density_kg_m3: number;
  youngs_mpa: number;
  poisson: number;
  yield_mpa: number;
  source: SourceRef;
  confirmed: boolean;
}

export interface LoadCase {
  id: string;
  kind: 'force' | 'aero_reference';
  applied_at?: string | null;
  vector_n?: number[] | null;
  fixtures: string[];
  source: SourceRef;
  confirmed: boolean;
}

export interface Requirement {
  id: string;
  constraint: Constraint;
  evaluator: 'metric_compare' | 'param_compare' | 'geometry_check';
  source: SourceRef;
  approved: boolean;
}

export interface BlockingQuestion {
  id: string;
  field: string;
  prompt: string;
  why: string;
  required_for: Maturity;
  options?: string[] | null;
}

export interface AnalysisPlan {
  screening_adapter: string;
  verify_adapter?: string | null;
  verify_top_k: number;
  convergence: 'none' | 'champion_two_level';
  timeout_s: number;
}

export interface CadBinding {
  provider: 'onshape' | 'mock';
  doc_ref: string;                       // env var NAME, never a URL
  write_target_ref?: string | null;
  source_microversion?: string | null;
  export: 'stl_configured' | 'step_configured';
}

export interface Authority {
  maturity: Maturity;
  permitted: Action[];
  max_onshape_calls_per_run: number;
  evidence: string[];
}

// ---------------------------------------------------------------- the manifest
export interface ProjectManifest {
  schema_version: 'manifest-v1';
  project_id: string;
  revision: number;
  name: string;
  domain_pack?: string | null;
  cad: CadBinding;
  design_space: DesignSpace;
  semantics: ParamSemantics[];
  protected: ProtectedInterface[];
  material?: MaterialSpec | null;
  load_cases: LoadCase[];
  requirements: Requirement[];
  analysis?: AnalysisPlan | null;
  authority: Authority;
  assumptions: string[];
  open_questions: BlockingQuestion[];
  history: RevisionNote[];
}

// ---------------------------------------------------------------- inventory
export interface ConfigInput {
  id: string;
  name: string;
  kind: 'quantity' | 'enum' | 'boolean' | 'string';
  unit: string;
  min?: number | null;
  max?: number | null;
  default?: ParamValue | null;
  choices?: string[] | null;
}

export interface InventoryPart {
  part_id: string;
  name: string;
  volume_mm3?: number | null;
  mass_g?: number | null;
  bbox_mm?: number[] | null;
}

export interface InventoryFeature { id: string; name: string; type: string; suppressed: boolean; }
export interface MateConnector { id: string; name: string; origin_mm?: number[] | null; }

export interface CadInventory {
  provider: string;
  source_microversion: string;
  document_name: string;                 // untrusted text: render as text, never as HTML
  units: Record<string, string>;
  parts: InventoryPart[];
  config_inputs: ConfigInput[];
  features: InventoryFeature[];
  mate_connectors: MateConnector[];
  export_formats: string[];
  onshape_calls: number;
}

// ---------------------------------------------------------------- checks, probes, reports
export interface CheckResult {
  id: string;
  passed: boolean | null;                // null = could not run => blocked, never a pass
  actual?: number | null;
  limit?: number | null;
  detail: string;
}

export interface GeometryEvidence {
  geometry_key: string;
  parse_ok: boolean;
  watertight: boolean;
  volume_mm3?: number | null;
  bbox_mm?: number[] | null;
  triangles?: number | null;
  checks: CheckResult[];
}

export interface ProbeResult {
  case: string;
  params: Record<string, ParamValue>;
  geometry: GeometryRef;
  evidence?: GeometryEvidence | null;
}

export interface CapabilityReport {
  project_id: string;
  maturity: Maturity;
  found: Record<string, unknown>;
  missing: BlockingQuestion[];
  unsupported: string[];
  required_adapter?: string | null;
}

export interface AdapterCapability {
  adapter_id: string;
  kind: 'cad' | 'solver' | 'verifier';
  version: string;
  domain: string;
  required_fields: string[];
  metrics: string[];
  fidelity: Array<'screening' | 'verification'>;
  process_safe: boolean;
  validity_envelope: Record<string, string>;
}

// ---------------------------------------------------------------- REST bodies (PLAN.md v3 B.7)
export interface ProjectSummary {
  project_id: string;
  name: string;
  revision: number;
  maturity: Maturity;
  domain_pack?: string | null;
}

export interface InspectRequest { doc_url: string; }

export interface InspectResponse {
  project_id: string;
  inventory: CadInventory;
  manifest: ProjectManifest;
  report: CapabilityReport;
}

export interface ManifestUpdate {
  revision: number;
  by: string;
  answers: Record<string, unknown>;
  semantics?: ParamSemantics[] | null;
  protected?: ProtectedInterface[] | null;
  requirements?: Requirement[] | null;
  note: string;
}

export interface ActivateResponse { maturity: Maturity; evidence: string[]; report: CapabilityReport; }

export interface CommitPreview {
  target: string;
  param_diff: Array<{ name: string; from: ParamValue; to: ParamValue; unit: string }>;
  expected_calls: number;
  checks_planned: string[];
  maturity: Maturity;
  blocked_reason?: string | null;
}
