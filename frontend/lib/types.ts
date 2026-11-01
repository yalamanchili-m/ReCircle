export interface HealthResponse {
  status: string;
  app?: string;
  env?: string;
}

export interface HealthDbResponse {
  status: string;
  database: string;
}

export interface OrganizationSummary {
  id: string;
  name: string;
  organization_type: string;
  industry: string | null;
  description: string | null;
  city: string;
  region: string | null;
  country: string;
}

export interface UserSummary {
  id: string;
  email: string;
  full_name: string;
  role: "generator" | "buyer" | "admin";
  is_active: boolean;
  organization: OrganizationSummary | null;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_at: string;
  user: UserSummary;
}

export type ListingStatus = "draft" | "active" | "matched" | "archived";

export interface Listing {
  id: string;
  title: string;
  description: string;
  category: string;
  material_name: string | null;
  composition: string | null;
  grade: string | null;
  condition: string | null;
  contamination_notes: string | null;
  quantity: string;
  unit: string;
  price_per_unit: string | null;
  currency: string;
  city: string;
  region: string | null;
  country: string;
  available_from: string | null;
  status: ListingStatus;
  created_at: string;
  updated_at: string;
}

export interface ListingPage {
  items: Listing[];
  total: number;
  page: number;
  page_size: number;
}

export interface ListingInput {
  title: string;
  description: string;
  category: string;
  material_name: string;
  composition: string;
  grade: string;
  condition: string;
  contamination_notes: string;
  quantity: string;
  unit: string;
  price_per_unit: string;
  city: string;
  region: string;
  available_from: string;
}

export interface MarketplaceListing extends Listing {
  organization_name: string;
}

export type RequirementStatus = "active" | "paused" | "closed";

export interface Requirement {
  id: string;
  title: string;
  category: string;
  description: string | null;
  min_quantity: string;
  unit: string;
  required_grade: string | null;
  max_price_per_unit: string | null;
  preferred_city: string | null;
  preferred_region: string | null;
  status: RequirementStatus;
  created_at: string;
  updated_at: string;
}

export interface RequirementInput {
  title: string;
  category: string;
  description: string;
  min_quantity: string;
  unit: string;
  required_grade: string;
  max_price_per_unit: string;
  preferred_city: string;
  preferred_region: string;
}

export interface MatchCandidate {
  listing_id: string;
  title: string;
  organization_name: string;
  category: string;
  quantity: string;
  unit: string;
  city: string;
  region: string | null;
  price_per_unit: string | null;
  currency: string;
  grade: string | null;
  score: number;
  score_breakdown: Record<string, number>;
  max_applicable: number;
  material_fit: number;
  knn_score: number;
  algorithm_version: string;
  explanation: string;
  warnings: string[];
}

export interface MatchRunResponse {
  requirement_id: string;
  persisted: boolean;
  candidate_count: number;
  results: MatchCandidate[];
}

export interface DashboardSummary {
  active_listings: number;
  quantity_by_unit: { unit: string; total: number; listing_count: number }[];
  requirements_count: number;
  matches_count: number;
  recent_listings: Listing[];
}

export interface EnrichmentResponse {
  available: boolean;
  source: "ollama" | "fallback";
  needs_review: boolean;
  suggestions: {
    category: string | null;
    material_name: string | null;
    composition: string | null;
    grade: string | null;
    quantity: number | null;
    unit: string | null;
    missing_information: string[];
    notes: string | null;
  };
}

export type PassportProvenance =
  | "user_provided"
  | "source_derived"
  | "ai_inferred"
  | "unverified";

export interface PassportAttribute {
  value: unknown;
  provenance: PassportProvenance;
  confidence: number | null;
}

export interface MaterialPassport {
  id: string;
  listing_id: string;
  organization_id: string;
  version: number;
  status: string;
  attributes: Record<string, PassportAttribute>;
  possible_applications: string[];
  suitable_industries: string[];
  candidate_pathways: string[];
  notes: string | null;
  review_status: string;
  reviewed_by: string | null;
  reviewed_at: string | null;
  created_by: string | null;
  created_at: string;
}

export interface MaterialSuggestionResponse {
  suggestions: {
    material_type: { value: { type_id: string; label: string } | null; provenance: string; confidence: number; evidence: Record<string, unknown> };
    category: { value: string | null; provenance: string; confidence: number };
    possible_applications: { value: string[]; provenance: string; confidence: number };
    suitable_industries: { value: string[]; provenance: string; confidence: number };
    candidate_pathways: { value: string[]; provenance: string; confidence: number | null };
  };
  original_label: string | null;
  missing_information: string[];
  needs_review: boolean;
  model_version: string;
  method: string;
  taxonomy_version: string;
  disclaimer: string;
}

export const MATERIAL_CATEGORIES = [
  "metals",
  "plastics",
  "paper_cardboard",
  "wood",
  "glass",
  "textiles",
  "organics",
  "electronics",
  "chemicals",
  "other",
] as const;

export const UNITS = ["kg", "tonne", "litre", "unit"] as const;

export interface GraphStatusResponse {
  neo4j_configured: boolean;
  connected: boolean;
  counts: Record<string, number> | null;
  last_sync: {
    status: string;
    error: string | null;
    projection_version: string;
    started_at: string;
    stats: Record<string, number>;
  } | null;
}

export interface GraphSyncResponse {
  status: string;
  projection_version: string;
  stats: Record<string, number>;
}

export interface GraphExploreRelationship {
  rel_type: string;
  rel_properties: Record<string, unknown>;
  other_labels: string[];
  other: Record<string, unknown> | null;
}

export interface GraphExploreResponse {
  connected: boolean;
  node: { labels: string[]; properties: Record<string, unknown> } | null;
  relationships: GraphExploreRelationship[];
  note?: string;
}

export interface SymbiosisPathEdge {
  from: string;
  to: string;
  rel_type: string;
  provenance: string | null;
  is_fact: boolean;
}

export interface SymbiosisOpportunity {
  producer_organization_id: string;
  producer_organization_name: string | null;
  consumer_organization_id: string;
  consumer_organization_name: string | null;
  listing_id: string;
  listing_title: string;
  requirement_id: string;
  requirement_title: string;
  category: string;
  material_fit: number;
  availability: number;
  graph_proximity: number;
  cluster_membership: number | null;
  confidence: number;
  evidence: {
    path: string[];
    path_edges: SymbiosisPathEdge[];
    path_depth: number | null;
    shared_cluster: number | null;
    hub_pagerank: Record<string, number>;
  };
  status: string;
}

export interface SymbiosisResponse {
  opportunities: SymbiosisOpportunity[];
  graph: {
    snapshot_id: string;
    nodes: number;
    edges: number;
    top_hubs: { node: string; pagerank: number }[];
    clusters: Record<string, number>;
  };
  limitations: string[];
  run: {
    status: string;
    graph_snapshot_id: string | null;
    candidates: number;
    runtime_ms: number;
    params: Record<string, unknown>;
    versions: {
      discovery: string;
      taxonomy: string;
      weights: Record<string, number>;
    };
  };
}

export interface SymbiosisEvaluationResponse {
  evaluation_version: string;
  dataset: string;
  passed: number;
  total: number;
  cases: Record<string, unknown>[];
  disclaimer: string;
}
