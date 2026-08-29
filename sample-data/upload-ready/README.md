# Upload-ready synthetic FIR samples

These files are fictional and exist only to demonstrate the evidence-processing and network-graph workflow. They do not identify guilty individuals or represent real police records.

## Files

- `sample_fir_network_001.txt` introduces Kavya Nair, Imran Shaikh, two phone numbers, one vehicle, Majestic Bus Stand, and Northstar Logistics.
- `sample_fir_network_002.txt` repeats Kavya Nair, phone `9988776601`, vehicle `KA05MN4821`, and Northstar Logistics, then introduces Rohan Das, another phone and vehicle, Yeshwanthpur Railway Yard, and Blue River Warehousing.

The repeated identifiers are intentional. Uploading both files to the same case lets entity resolution merge shared entities and produce one connected graph instead of two unrelated graphs.

## Demonstration steps

1. Open the application at `http://127.0.0.1:15173`.
2. Sign in as `investigator.demo` with password `SIH1@2026`.
3. Open one case and upload both `.txt` files to that same case through Evidence Intake.
4. Wait until both processing jobs show `COMPLETED`.
5. Open Extraction Review and confirm the synthetic entity and relationship candidates.
6. Run entity resolution and rebuild the network graph for the case.
7. Open Network Graph. Kavya Nair, phone `9988776601`, vehicle `KA05MN4821`, and Northstar Logistics should bridge the two FIRs.
8. Optionally run graph analytics to refresh centrality and community indicators.

Plain-text FIRs test the ingestion and extraction pipeline without OCR uncertainty. To demonstrate OCR later, render or print these documents to image/PDF and upload those versions instead.
