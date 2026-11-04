# QudSystem Pilot Quote & Unit-Economics Worksheet
Status: internal calculator template. Prices below are hypotheses; replace inputs with actual costs and approved quotes.

## 1. Quote formula
Use the following for each job:

`Minimum quote = (human_hours × hourly_cost + model_cost + tools_and_fees + acquisition_cost + support_allowance + rework_allowance) ÷ (1 − target_gross_margin)`

All values should use the same currency. Do not confuse gross margin with markup.

## 2. Worked example — illustrative only
| Input | Example |
|---|---:|
| Human delivery + QA | 2.0 hours |
| Internal hourly cost | EGP 120/hour |
| Model usage | EGP 15 |
| Tools/payment allowance | EGP 20 |
| Acquisition allowance | EGP 30 |
| Rework/support allowance | EGP 25 |
| Target gross margin | 40% |

Direct/allocated cost = 2×120 + 15 + 20 + 30 + 25 = EGP 330.
Minimum quote = 330 ÷ (1 − 0.40) = EGP 550.

This example is not a market price recommendation. It shows why a low fixed price can lose money when human review is included.

## 3. CVPen package guardrails
| Package | Scope boundary | Price test |
|---|---|---:|
| CV Health Check | Short redacted excerpt, structure and clarity notes, capped free cohort | Free, limited slots |
| CV Refresh | One CV, one target role, one revision | Test EGP 249 only if measured cost supports it |
| Targeted CV | One CV + one job description + one revision | Test EGP 499 only if measured cost supports it |
| Career Bundle | CV + cover letter + LinkedIn summary draft, one revision | Test EGP 899 only if measured cost supports it |

## 4. Per-order tracking sheet fields
- Quote ID (random internal reference)
- Service SKU and package
- Quoted amount and currency
- Verified settlement amount and date (only after provider/bank evidence)
- Human minutes: intake, drafting, QA, revisions, support
- Model calls/tokens and known cost
- Tools/payment/acquisition costs
- Number of included and extra revisions
- Delivery date and acceptance state
- Refund/complaint state
- Calculated contribution = settled revenue − direct costs

Do not store candidate CV text, national IDs, full addresses, card/bank credentials, or sensitive profile data in this worksheet.

## 5. First 10-order learning loop
Do not forecast conversion or income before collecting evidence. For each of the first ten paid orders, measure:
1. Lead source and whether consent/expectations were clear.
2. Quote acceptance or rejection and stated reason.
3. Actual human time versus estimated time.
4. Model/tool cost and whether any unknown cost remains.
5. Revision count, complaint/refund and acceptance.
6. Contribution margin after all direct costs.

After ten completed orders, compare package-level median delivery time, revision rate and contribution. Change price/scope only from measured data.

## 6. Stop-loss rules
- Pause sales if secure intake, privacy notice, named reviewer or deletion process is unavailable.
- Pause any package with negative contribution after two consecutive completed orders until scope/price is corrected.
- Stop automated model use when per-order budget or provider-side hard cap is missing.
- Do not call a pending payment revenue.
- Do not scale a service with unresolved critical factual/privacy complaints.

## 7. Owner approval
- [ ] Approve target segment and package scope.
- [ ] Enter actual hourly cost and provider prices.
- [ ] Confirm taxes/payment fees and refund obligations.
- [ ] Approve final price and turnaround.
- [ ] Name reviewer and backup.
- [ ] Confirm intake, storage, retention and deletion are live.
- [ ] Approve first customer acquisition message.