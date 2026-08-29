export const caseRecord = {
  id: "KSP-CR-2048",
  title: "Majestic Corridor Link Analysis",
  jurisdiction: "Bengaluru Central",
  classification: "RESTRICTED",
  owner: "Inspector A. Rao",
  updated: "24 Aug 2026 · 17:42",
};

export const sources = [
  {
    id: "SRC-001",
    name: "FIR_042_Majestic.pdf",
    type: "Scanned FIR",
    pages: 8,
    status: "Reviewed",
    accent: "yellow",
    details: "OCR 96.4% · 14 entities · 7 relationships",
  },
  {
    id: "SRC-002",
    name: "FIR_039_Cottonpet.pdf",
    type: "Scanned FIR",
    pages: 6,
    status: "Processed",
    accent: "yellow",
    details: "OCR 93.8% · 9 entities · 4 relationships",
  },
  {
    id: "SRC-003",
    name: "FIR_051_Vehicle.pdf",
    type: "Digital FIR",
    pages: 5,
    status: "Review needed",
    accent: "red",
    details: "Text parsed · 7 entities · 3 relationships",
  },
  {
    id: "SRC-004",
    name: "cdr_window_12-18_aug.csv",
    type: "Call detail records",
    pages: 4820,
    status: "Processed",
    accent: "blue",
    details: "4,820 rows · 18 phones · 3 validation warnings",
  },
  {
    id: "SRC-005",
    name: "transactions_batch_b.csv",
    type: "Financial transactions",
    pages: 1260,
    status: "Review needed",
    accent: "red",
    details: "1,260 rows · 9 accounts · 2 pattern alerts",
  },
];

export const extractionItems = [
  { id: 1, text: "Ravi K.", type: "PERSON", confidence: 94, status: "confirmed", source: "Page 2 · line 14" },
  { id: 2, text: "+91 98••• 2146", type: "PHONE", confidence: 100, status: "confirmed", source: "Page 2 · line 16" },
  { id: 3, text: "Majestic Bus Stand", type: "LOCATION", confidence: 91, status: "pending", source: "Page 3 · line 4" },
  { id: 4, text: "KA-05-MT-4812", type: "VEHICLE", confidence: 99, status: "confirmed", source: "Page 3 · line 9" },
  { id: 5, text: "Ajay M.", type: "PERSON", confidence: 78, status: "review", source: "Page 4 · line 7" },
];

export const relationships = [
  { id: 1, from: "Ravi K.", type: "USES", to: "+91 98••• 2146", confidence: 96, evidence: "FIR_042 · p2" },
  { id: 2, from: "Ravi K.", type: "PRESENT_AT", to: "Majestic Bus Stand", confidence: 88, evidence: "FIR_042 · p3" },
  { id: 3, from: "Ajay M.", type: "OWNS", to: "KA-05-MT-4812", confidence: 93, evidence: "Vehicle record · row 18" },
  { id: 4, from: "+91 98••• 2146", type: "CALLED", to: "+91 97••• 8031", confidence: 100, evidence: "CDR · row 241" },
];

export const graphElements = [
  { data: { id: "ravi", label: "Ravi K.", type: "person", subtitle: "Person · reviewed", evidence: 8, history: ["FIR_042 · entity confirmed", "CDR · linked phone observed", "Graph · centrality rank 01"] } },
  { data: { id: "ajay", label: "Ajay M.", type: "person", subtitle: "Person · review needed", evidence: 5, history: ["FIR_039 · entity extracted", "CDR · proposed phone association", "Vehicle register · reviewed owner link"] } },
  { data: { id: "nisha", label: "Nisha S.", type: "person", subtitle: "Person · reviewed", evidence: 4, history: ["FIR_051 · entity confirmed", "CDR · 5 observed contacts", "Transaction batch · account holder link"] } },
  { data: { id: "phone1", label: "98•••2146", type: "phone", subtitle: "Phone · 42 events", evidence: 42, history: ["12 Aug · first observed call", "16 Aug · 12 calls in 47 minutes", "18 Aug · last selected-window event"] } },
  { data: { id: "phone2", label: "97•••8031", type: "phone", subtitle: "Phone · 17 events", evidence: 17, history: ["12 Aug · first contact with 98•••2146", "16 Aug · communication burst", "17 Aug · new bridge edge observed"] } },
  { data: { id: "account1", label: "A/C ••7312", type: "account", subtitle: "Account · 12 records", evidence: 12 } },
  { data: { id: "vehicle1", label: "KA-05-MT-4812", type: "vehicle", subtitle: "Vehicle · 3 records", evidence: 3 } },
  { data: { id: "majestic", label: "Majestic", type: "location", subtitle: "Location · 9 events", evidence: 9 } },
  { data: { id: "market", label: "Cottonpet", type: "location", subtitle: "Location · 6 events", evidence: 6 } },
  { data: { id: "e1", source: "ravi", target: "phone1", relation: "USES", confidence: 96, evidence: "FIR_042 · page 2", status: "confirmed" } },
  { data: { id: "e2", source: "phone1", target: "phone2", relation: "CALLED", confidence: 100, evidence: "CDR · 12 events", status: "confirmed" } },
  { data: { id: "e3", source: "phone2", target: "ajay", relation: "USED_BY", confidence: 89, evidence: "FIR_039 + CDR", status: "proposed" } },
  { data: { id: "e4", source: "ajay", target: "vehicle1", relation: "OWNS", confidence: 93, evidence: "Vehicle register", status: "confirmed" } },
  { data: { id: "e5", source: "ravi", target: "majestic", relation: "PRESENT_AT", confidence: 88, evidence: "FIR_042 · page 3", status: "proposed" } },
  { data: { id: "e6", source: "nisha", target: "phone2", relation: "CONTACTED", confidence: 100, evidence: "CDR · 5 events", status: "confirmed" } },
  { data: { id: "e7", source: "nisha", target: "account1", relation: "HOLDS", confidence: 97, evidence: "Bank file · row 12", status: "confirmed" } },
  { data: { id: "e8", source: "account1", target: "ajay", relation: "TRANSFERRED_TO", confidence: 100, evidence: "Transaction · ₹48,000", status: "confirmed" } },
  { data: { id: "e9", source: "vehicle1", target: "market", relation: "OBSERVED_AT", confidence: 76, evidence: "Field report · page 1", status: "proposed" } },
];

export const centralityRanking = [
  { rank: 1, id: "ravi", label: "Ravi K.", type: "person", score: 0.62, metric: "PageRank", evidence: 8, status: "reviewed", history: ["FIR_042 · entity confirmed", "CDR · linked phone observed", "Graph · centrality rank 01"] },
  { rank: 2, id: "phone1", label: "98•••2146", type: "phone", score: 0.58, metric: "PageRank", evidence: 42, status: "observed", history: ["12 Aug · first observed call", "16 Aug · 12 calls in 47 minutes", "18 Aug · last selected-window event"] },
  { rank: 3, id: "ajay", label: "Ajay M.", type: "person", score: 0.43, metric: "PageRank", evidence: 5, status: "review needed", history: ["FIR_039 · entity extracted", "CDR · proposed phone association", "Vehicle register · reviewed owner link"] },
];

export const timeline = [
  { time: "12 Aug · 21:14", title: "First observed communication", detail: "Phone 98•••2146 called 97•••8031 for 03:42", source: "CDR row 241", type: "communication" },
  { time: "13 Aug · 10:35", title: "Location mentioned in report", detail: "Majestic Bus Stand recorded in FIR narrative", source: "FIR_042 page 3", type: "location" },
  { time: "14 Aug · 16:08", title: "Transaction recorded", detail: "₹48,000 transferred between linked accounts", source: "Transaction row 184", type: "transaction" },
  { time: "16 Aug · 23:17", title: "Communication burst detected", detail: "12 calls within 47 minutes; baseline is 2.1 per day", source: "Rule COM-BURST-01", type: "alert" },
  { time: "18 Aug · 08:42", title: "Vehicle observation added", detail: "KA-05-MT-4812 observed near Cottonpet", source: "Field report page 1", type: "vehicle" },
];

export const alerts = [
  {
    id: "ALT-019",
    severity: "HIGH REVIEW",
    title: "Communication burst",
    explanation: "12 calls occurred within 47 minutes, exceeding this phone's 14-day baseline by 4.8×.",
    evidence: ["CDR rows 318–329", "2 phones", "16 Aug · 22:30–23:17"],
    status: "new",
  },
  {
    id: "ALT-021",
    severity: "MEDIUM REVIEW",
    title: "New bridge between communities",
    explanation: "A newly observed phone link connects two previously separate graph communities.",
    evidence: ["CDR row 410", "Betweenness change +31%", "17 Aug · 19:04"],
    status: "new",
  },
  {
    id: "ALT-024",
    severity: "MEDIUM REVIEW",
    title: "Rapid transaction chain",
    explanation: "Funds traversed three accounts within 26 minutes. This is a rule match, not evidence of wrongdoing.",
    evidence: ["3 transactions", "₹48,000 total", "14 Aug · 15:42–16:08"],
    status: "reviewed",
  },
];

export const citations = [
  { id: 1, label: "FIR_042 · page 2", excerpt: "The supplied contact number was recorded in the statement…" },
  { id: 2, label: "CDR · rows 241–252", excerpt: "Twelve observed call events connect the selected numbers…" },
  { id: 3, label: "Vehicle register · row 18", excerpt: "Registration KA-05-MT-4812 is linked to the reviewed entity…" },
];
