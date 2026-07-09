# Capa-004 Corrective And Preventive Action

## Metadata
- created: unknown
- aliases: none
- source: /Users/hotuongvinh/ai_projects/wiki-cli/datasets/quality_assurance/documents/CAPA-004_Corrective_and_Preventive_Action.pdf

## Related
- [Sop-Qa-008 Internal Audit Procedure](sop_qa_008_internal_audit_procedure.md)
- [Sop-Qa-012 Non Conformance Report Procedure](sop_qa_012_non_conformance_report_procedure.md)

## Referenced By
- [Sop-Qa-008 Internal Audit Procedure](sop_qa_008_internal_audit_procedure.md)
- [Sop-Qa-001 Quality Management System](sop_qa_001_quality_management_system.md)
- [Sop-Qa-012 Non Conformance Report Procedure](sop_qa_012_non_conformance_report_procedure.md)

## Body
Corrective and Preventive Action Procedure
Purpose
This procedure defines the system for implementing and verifying corrective
andpreventiveactionstoeliminatethecausesofnon-conformancesandprevent
recurrence.
Scope
This procedure applies to all corrective and preventive actions at Acme Corpo-
ration, including those triggered by NCRs, audit findings, customer complaints,
and improvement initiatives.
Definitions
CAPA: Corrective and Preventive Action — a systematic process to eliminate
causes of non-conformances.
CorrectiveAction: Actiontoeliminatethecauseofadetectednon-conformance
and prevent recurrence.
Preventive Action: Action to eliminate the cause of a potential non-
conformance.
Effectiveness Check: Verification that the implemented action achieves the in-
tended result.
Procedure
Step 1: Initiation
A CAPA is initiated when any of the following occur:
• An NCR is classified as Critical or Major (per SOP-QA-012)
• An audit finding identifies a systemic issue
• A customer complaint indicates a process failure
• Recurring non-conformances (three or more similar NCRs in 90 days)
• Management review identifies improvement opportunities
TheQAEngineeropensaCAPArecordwithauniquenumber(format: CAPA-
YYYY-XXXX).
Step 2: Problem Description
Define the problem clearly and quantitatively:
• What happened? Include objective evidence.
• When did it happen? Dates and shift information.
• Where did it happen? Production line, station, process step.
1

• How big is the impact? Quantity affected, cost impact, customer impact.
• How was it detected? Inspection, test, customer feedback.
Step 3: Containment
Implement immediate containment actions to protect the customer:
• Quarantine affected products
• Sort and inspect inventory
• Protect work in process
• Notify customers if applicable
Document containment effectiveness within 48 hours.
Step 4: Root Cause Analysis
Perform root cause analysis using approved methods:
5 Whys: Drill down from symptom to root cause by asking “why” iteratively.
Fishbone Diagram: Analyze six categories: Man, Machine, Material, Method,
Measurement, Environment.
Data Analysis: Use statistical tools (control charts, Pareto analysis, hypothesis
testing) when suﬀicient data exists.
Document the verified root cause with supporting evidence.
Step 5: Action Plan
Define corrective actions that address the root cause:
Action Owner Due Date Expected Result
Update QA 14 days Clear pressure limits
WI-034 Engineer
Retrain Production 7 days 100% operator competency
operators Manager
Install Maintenance 30 days Real-time alert
pressure
alarm
Each action must have a single owner, a specific due date, and a measurable
expected result.
Step 6: Implementation
Execute the action plan. The QA Engineer tracks progress weekly. Escalate
overdue actions to the QA Manager.
2

| Step 7: Effectiveness |                  | Check               |               |             |                  |                |              |
| --------------------- | ---------------- | ------------------- | ------------- | ----------- | ---------------- | -------------- | ------------ |
| Within 30             | days             | of implementation   |               | completion, | verify           | effectiveness: |              |
| • Collect             | data             | for at least        | 30 production |             | cycles (or       | as specified   | in the plan) |
| • Compare             | before-and-after |                     | data          |             |                  |                |              |
| • Confirm             | that             | the non-conformance |               |             | has not recurred |                |              |
| • Document            |                  | the verification    | in            | the CAPA    | record           |                |              |
If effectiveness is not demonstrated, reopen the CAPA and revise the action
plan.
| Step 8: Closure     |           |               |         |     |     |     |     |
| ------------------- | --------- | ------------- | ------- | --- | --- | --- | --- |
| The CAPA            | is closed | when:         |         |     |     |     |     |
| • All actions       |           | are completed |         |     |     |     |     |
| • Effectiveness     |           | is verified   |         |     |     |     |     |
| • Documentation     |           | is complete   |         |     |     |     |     |
| • QA Manager        |           | approves      | closure |     |     |     |     |
| CAPA Prioritization |           |               |         |     |     |     |     |
Priority 1: Safety or regulatory issue. Complete within 14 days. Priority 2:
Customerimpactorsignificantqualityissue. Completewithin30days. Priority
| 3: Process    | improvement. | Complete        |              | within    | 60 days.  |     |     |
| ------------- | ------------ | --------------- | ------------ | --------- | --------- | --- | --- |
| Related       | Documents    |                 |              |           |           |     |     |
| • SOP-QA-012: |              | Non-Conformance |              | Report    | Procedure |     |     |
| • SOP-QA-008: |              | Internal        | Audit        | Procedure |           |     |     |
| Document      | Version      | 2.0 —           | Last Updated | February  | 2026      |     |     |
3

## Notes
_(add your own notes here -- preserved on recompile)_
