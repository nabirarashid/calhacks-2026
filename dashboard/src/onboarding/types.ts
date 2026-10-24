export type Maturity = 0 | 1 | 2 | 3 | 4;

export type ParamRole = 'editable' | 'fixed' | 'protected';

export interface InventoryPart {
  part_id: string;
  name: string;
  volume_mm3?: number;
  mass_g?: number;
  bbox_mm?: number[];
}

export interface InventoryInput {
  id: string;
  name: string;
  kind: string;
  unit?: string;
  min?: number;
  max?: number;
  default?: string | number;
  choices?: string[];
}

export interface MateConnector {
  id: string;
  name: string;
  origin_mm?: number[];
}

export interface CadInventory {
  provider: string;
  source_microversion: string;
  units: Record<string, string>;
  parts: InventoryPart[];
  config_inputs: InventoryInput[];
  features: Array<{ id: string; name: string; type: string; suppressed?: boolean }>;
  mate_connectors: MateConnector[];
  export_formats: string[];
  onshape_calls: number;
}

export interface ParamSemantics {
  name: string;
  cad_ref: string;
  role: ParamRole;
  meaning: string;
  confidence?: number | null;
  confirmed: boolean;
}

export interface BlockingQuestion {
  id: string;
  field: string;
  prompt: string;
  why: string;
  required_for: Maturity;
  options?: string[] | null;
}

export interface CapabilityReportData {
  project_id: string;
  maturity: Maturity;
  found: Record<string, unknown>;
  missing: BlockingQuestion[];
  unsupported: string[];
  required_adapter?: string | null;
}

export interface ProjectManifestDraft {
  project_id: string;
  revision: number;
  name: string;
  semantics: ParamSemantics[];
  open_questions: BlockingQuestion[];
  authority: {
    maturity: Maturity;
    permitted: string[];
    evidence?: string[];
  };
}

export interface OnboardingInspection {
  project_id: string;
  inventory: CadInventory;
  manifest: ProjectManifestDraft;
  report: CapabilityReportData;
}

export type QuestionValue = string | number | string[] | number[];

export interface ReviewSubmission {
  project_id: string;
  revision: number;
  by: string;
  semantics: ParamSemantics[];
  answers: Record<string, QuestionValue>;
}

export interface CheckResult {
  id: string;
  passed: boolean | null;
  actual?: number | null;
  limit?: number | null;
  detail?: string;
}

export interface ProbeResult {
  case: string;
  params: Record<string, string | number>;
  geometry: {
    geometry_key?: string;
    status?: string;
    preview_url?: string;
  };
  evidence?: {
    parse_ok: boolean;
    watertight: boolean;
    volume_mm3?: number | null;
    triangles?: number | null;
    checks: CheckResult[];
  } | null;
}

export interface ActivationResult {
  maturity: Maturity;
  evidence: string[];
  report: CapabilityReportData;
}

