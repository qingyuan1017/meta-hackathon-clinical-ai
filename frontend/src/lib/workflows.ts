import { Braces, ClipboardList, FileOutput, Files, LayoutDashboard, TableProperties, type LucideIcon } from "lucide-react";
import type { Workflow } from "./types";

export interface WorkflowDefinition {
  id: Workflow;
  title: string;
  shortTitle: string;
  description: string;
  eyebrow: string;
  experimental: boolean;
  icon: LucideIcon;
  accepts: string;
  filePrompt: string;
}

export const workflows: WorkflowDefinition[] = [
  {
    id: "protocol-extraction",
    title: "Clinical protocol extraction",
    shortTitle: "Protocol extraction",
    description: "Turn a protocol into traceable study facts and a CDISC USDM 4.0 artifact gated by the complete published CORE ruleset.",
    eyebrow: "01 · UNDERSTAND",
    experimental: true,
    icon: Braces,
    accepts: ".pdf,.docx,.txt,.md",
    filePrompt: "Upload one protocol (PDF, DOCX, TXT, or Markdown).",
  },
  {
    id: "clinical-document",
    title: "Clinical document generation",
    shortTitle: "Document generation",
    description: "Draft one of ten clinical documents from a study brief and optional reference material.",
    eyebrow: "02 · AUTHOR",
    experimental: true,
    icon: FileOutput,
    accepts: ".pdf,.docx,.txt,.md,.json",
    filePrompt: "Add optional protocol or extracted JSON reference files.",
  },
  {
    id: "edc-design",
    title: "EDC database design",
    shortTitle: "EDC design",
    description: "Propose visits, forms, fields, codelists, derivations, and edit checks as a build-ready draft.",
    eyebrow: "03 · COLLECT",
    experimental: true,
    icon: LayoutDashboard,
    accepts: ".pdf,.docx,.txt,.md,.json",
    filePrompt: "Upload a protocol or protocol-extraction JSON.",
  },
  {
    id: "sdtm",
    title: "CDISC SDTM",
    shortTitle: "SDTM artifacts",
    description: "Generate reviewed SDTM mappings and programs, then execute R against synthetic raw data and review validation evidence.",
    eyebrow: "04 · STANDARDIZE",
    experimental: false,
    icon: Files,  
    accepts: ".json,.xlsx,.docx,.txt,.md",
    filePrompt: "Select the required EDC JSON/XLSX and any optional protocol context. Raw data, CRF, and validation evidence have separate fields below.",
  },
  {
    id: "tlf",
    title: "TLF artifact generation",
    shortTitle: "TLF artifacts",
    description: "Approve the output table of contents, review detailed shells for every approved output, then review ADaM-linked R/SAS programming scaffolds.",
    eyebrow: "05 · ANALYZE",
    experimental: true,
    icon: TableProperties,
    accepts: ".pdf,.docx,.txt,.md,.json,.xlsx",
    filePrompt: "Upload a SAP or protocol and optional ADaM metadata.",
  },
];

export const workflowById = Object.fromEntries(workflows.map((item) => [item.id, item])) as Record<Workflow, WorkflowDefinition>;

export const workspaceGroups = [
  {
    id: "biostats",
    title: "Biostats",
    items: [
      { workflow: "protocol-extraction", label: "Protocol extraction", href: "/workflows/protocol-extraction", pathname: "/workflows/protocol-extraction", discipline: "biostats", icon: Braces },
      { workflow: "clinical-document", label: "Document generation", href: "/workflows/clinical-document?discipline=biostats", pathname: "/workflows/clinical-document", discipline: "biostats", icon: FileOutput },
    ],
  },
  {
    id: "data-management",
    title: "Data management",
    items: [
      { workflow: "edc-design", label: "EDC design", href: "/workflows/edc-design", pathname: "/workflows/edc-design", discipline: "data-management", icon: LayoutDashboard },
      { workflow: "clinical-document", label: "Document generation", href: "/workflows/clinical-document?discipline=data-management", pathname: "/workflows/clinical-document", discipline: "data-management", icon: ClipboardList },
    ],
  },
  {
    id: "stats-programming",
    title: "Stats programming",
    items: [
      { workflow: "sdtm", label: "SDTM", href: "/workflows/sdtm", pathname: "/workflows/sdtm", discipline: "stats-programming", icon: Files },
      { workflow: "tlf", label: "TLF", href: "/workflows/tlf", pathname: "/workflows/tlf", discipline: "stats-programming", icon: TableProperties },
    ],
  },
] as const;

export const documentTypes = [
  ["protocol-synopsis", "Protocol Synopsis"],
  ["full-protocol", "Full Protocol Draft"],
  ["sap", "Statistical Analysis Plan"],
  ["csr-shell", "Clinical Study Report Shell"],
  ["informed-consent", "Informed Consent Form Draft"],
  ["data-management-plan", "Data Management Plan"],
  ["data-review-plan", "Data Review Plan"],
  ["aggregate-risk-profile", "Aggregate Study Risk Profile"],
  ["potential-important-deviations", "Potential Important Protocol Deviations"],
  ["potential-amendments", "Potential Protocol Amendments"],
] as const;
