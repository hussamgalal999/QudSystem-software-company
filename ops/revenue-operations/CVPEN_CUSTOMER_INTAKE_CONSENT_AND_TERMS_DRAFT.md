# CVPen Customer Intake, Consent & Service Terms — Pilot Draft
Version: 1.0 | For owner/legal review before public use

## Customer-facing explanation (Arabic)
بنستخدم البيانات اللي بتبعتها لنا فقط لفهم خبرتك وتجهيز مراجعة أو نسخة محسّنة من سيرتك الذاتية حسب الباقة اللي اخترتها. مش بنضيف خبرات أو شهادات أو أرقام من عندنا. لو معلومة ناقصة أو غير واضحة، بنسألك بدل ما نخمن.

## Minimum intake fields
- Preferred name for the CV (not necessarily legal name).
- Contact channel needed for delivery.
- Target role and country/market.
- CV text or file only after the secure intake channel is approved.
- Target job description only when role-tailoring is requested.
- Preferred language and output format.
- Explicit consent timestamp and notice version.

Do not request national ID, passport, full home address, marital status, religion, health data, bank/payment credentials, or unrelated personal details. Ask the customer to remove these from uploaded files where possible.

## Consent wording — draft
أوافق على استخدام المعلومات والمستندات التي أرسلها لمعالجة طلب CVPen المحدد، وإعداد المراجعة أو المستندات المتفق عليها، والتواصل معي بخصوص الطلب. أفهم أن التنفيذ يتضمن مراجعة بشرية، وأنه لا يوجد ضمان لاجتياز أي نظام ATS أو الحصول على مقابلة أو وظيفة. يمكنني طلب إيقاف المعالجة أو الاستفسار عن حذف ملفاتي عبر قناة التواصل المعلنة، مع مراعاة أي التزامات قانونية واجبة.

## Service terms — pilot draft
1. **Scope:** The package includes only the listed deliverables, target role count, file formats and revision count confirmed in the written order.
2. **Truthfulness:** CVPen edits and organizes facts supplied by the customer. It will not invent employers, job titles, dates, qualifications, certifications, skills, metrics or achievements.
3. **Customer review:** The customer is responsible for checking names, dates, contact details and factual accuracy before using the CV.
4. **ATS limitation:** ATS tools differ. CVPen can review common structure and parsing practices but cannot guarantee a score, parsing result, shortlist, interview or job offer.
5. **Payment:** Work on a paid package starts only after payment is verified through the approved payment provider. Screenshots and SMS are not payment confirmation.
6. **Revisions:** The included revision count and deadline are stated in the order. A revision corrects or clarifies the agreed deliverable; a new target role or major scope change may require a new quote.
7. **Delivery:** Delivery time begins after required information and verified payment are received. Any delay caused by missing or contradictory facts is communicated to the customer.
8. **Privacy:** CV files are handled separately from the commercial order ledger. They must not be pasted into GitHub, public issue trackers, Telegram, analytics, or long-term agent memory.
9. **Deletion:** The owner must publish a specific retention period and secure deletion process before accepting real CV files. Do not promise deletion timelines until they are implemented.
10. **Refunds/complaints:** Publish a clear refund and complaint route consistent with applicable Egyptian consumer and data-protection requirements before taking payment.

## Internal secure-processing checklist
- [ ] Approved private intake channel; no public upload bucket or personal chat as a default.
- [ ] Named staff access only; MFA enabled on storage and business accounts.
- [ ] Encrypted storage and transport; no public links.
- [ ] Malware scanning and file-type/size limits before opening files.
- [ ] Separate tenant/customer folders and access logs.
- [ ] No CV content in logs, error traces, prompts retained as memory, or analytics.
- [ ] Model providers reviewed for data retention/training settings and contractual suitability before any customer CV is sent.
- [ ] Human fact-check and privacy review before delivery.
- [ ] Retention period, deletion workflow and backup expiry tested.
- [ ] Incident and breach response contact/process documented.

## Owner release gate
Do not publish this notice or accept real CV uploads until the owner approves the terms, privacy notice, retention period, secure intake channel, data processor choices, and applicable legal review. This is an operational draft, not a legal compliance certification.