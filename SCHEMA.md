# Paisa Dost — data map and unified schema

All columns below are copied from the CSV headers in `buildathon/`. Nothing here is guessed.
The data runs to 16 Oct 2026. Times are IST.

## Data map

| File | Rows | Gives us | Used for |
|---|---|---|---|
| `sms/sms.csv` (user_id, sender, sms_id, body_text, received_at_ist) | 31,905 (21 users) | Bank debits/credits, **Avl Bal**, card spends + **Avl Lmt**, card statement alerts (**Total Amount Due, Min Due, due date**), EMI/premium/bill due notices, CIBIL enquiry alerts | txns, balances, dues, card limits, credit enquiries |
| `emails/emails.csv` (user_id, email, subject, body, attachments_path, received_at) | 30,746 (24 users) | Card statement summaries in the body (Statement Date, Total Amount Due, Payment Due Date), bills, loan due notices, CAS/statement PDFs as attachments | dues, statement totals, second source for dedupe |
| `emails/users_data.csv` (user_id, first_name, last_name, email, pan, date_of_birth) | 24 | Identity, plus the PAN/DOB the README says to use for protected PDFs | login identity, PDF passwords (blocked, see PLAN open question 1) |
| `emails/attachments/<user>/<msg>/*.pdf` | ~2,780 PDFs | Bank statements, card statements, Experian reports (password protected) | balances, card limits, CIBIL data (pending permission) |
| `loan/customers.csv` (user_id, first_name, last_name, mobile, email, age, gender, city, state, pincode, signed_up_at) | 11,436 | Profile, mobile | profile |
| `loan/loan_applications.csv` (… lender, loan_status, approved_amount, interest_rate_yearly_pct, total_interest, tenure_days, number_of_emi, emi_frequency, applied_at, disbursed_at …) | 19,364 | Loan terms incl. **APR** | loan APR, enquiry count |
| `loan/emis.csv` (loan_id, user_id, lender, emi_number, due_date, emi_amount, principal, interest, amount_still_due, emi_status, days_past_due, …) | 31,699 | EMI schedule and status | dues (none of the 24 email/SMS users have rows here) |
| `loan/payments.csv` (payment_id, loan_id, user_id, amount, payment_mode, status, failure_reason, initiated_at, succeeded_at, …) | 5,732 | EMI payment attempts | txns, failed autopay |
| `loan/lenders.csv` (lender, advertised_rate_text, emi_frequency, …) | 15 | Lender terms | labels |
| `investment/holdings.csv` (user_id, product, fund_id, units, invested_amount_inr, current_value_inr, nav_date, …) | 9,651 | Current investments | net worth, health score |
| `investment/sip_plans.csv` (sip_plan_id, user_id, frequency, amount_inr, debit_day, status, first_debit_date, …) | 6,246 | Recurring SIP debits | recurring charges, upcoming dues |
| `investment/orders.csv` (order_id, user_id, order_type, amount_inr, status, failure_reason, created_at, succeeded_at, …) | 130,349 | Buys/sells | txns |
| `investment/funds.csv`, `baskets.csv`, `fund_daily_nav.csv` | 19 / 22 / 1,423 | Fund names, splits, NAV | labels |
| `insurance/policies.csv` (policy_id, user_id, status, next_payment_at, cycle_premium, …) | 1,550 | Active policies, next premium | dues, recurring |
| `insurance/policy_billing_period.csv` (policy_id, period_start, amount, status, settled_at, …) | 30,165 | Premiums due/paid | dues |
| `insurance/transactions.csv` (transaction_id, user_id, policy_id, purpose, amount_requested, status, resolved_at, …) | 32,974 | Premium debits | txns, failed debits |
| `insurance/mandates.csv`, `transaction_events.csv`, `billing_attempt.csv`, `receivables.csv`, `applications.csv`, `policy_*`, `premium_rate_cards.csv`, `insurance_products.csv`, `cover_drafts.csv`, `insurance_eligibility_blocks.csv`, `partner_user_mappings.csv` | various | Autopay mandates, payment steps, product catalogue | supporting detail, not needed for the demo |

**Gaps vs context.md:** there is no CIBIL CSV and no bank/card statement CSV. Credit data comes from SMS (card **Avl Lmt**, statement dues, CIBIL enquiry alerts) and email statement summaries. Full credit reports are in password-protected Experian PDFs.

## Demo user

`1749913629362473`, LOKESH VERMA. He has the richest finance signal of the 24 users: 3,703 SMS, 3,809 emails, 714 balance SMS, card statement alerts from IndusInd (XX3359), IDFC FIRST Select (XXXX1641), HDFC, Axis and YES, LIC and Canara HSBC premium dues, Experian reports, SIPs and a small policy. The loader works for every user. The demo is tuned on this one.

## Unified schema

```python
Txn:       id, user_id, amount, direction("debit"|"credit"), date, merchant, merchant_norm,
           type("upi"|"card"|"neft"|"autopay"|"emi"|"premium"|"sip"|"bill"|"other"),
           category, account_ref("BOB XX1626" | "IndusInd card XX3359"), balance_after?,
           source_ids[], source_label
Due:       id, user_id, title, amount, min_amount?, due_date, kind("card"|"emi"|"premium"|"bill"|"sip"),
           account_ref, status("upcoming"|"paid"|"overdue"), source_ids[], source_label
Balance:   id, user_id, account_ref, amount, as_of, source_ids[], source_label
Card:      id, user_id, account_ref, limit?, available?, outstanding?, apr?, statement_due?, source_ids[], source_label
Fact:      text_key, value, source_ids[], source_label     # every number the agent may say
```

* **`source_id`** is `<file>:<row key>`, for example `sms:3502`, `email:<user>:<received_at>`, `emis:<loan_id>#<emi_number>`, `sip:<sip_plan_id>`.
* **`source_label`** is what the agent says, for example "from your Bank of Baroda SMS on 13 Sep" or "from your IndusInd statement email on 23 Sep".
* **Dedupe** uses the key `(amount, date ±1 day, fuzzy merchant ≥ 0.8)`. Merged rows keep the union of `source_ids`.

## Graph store (per user)

The same records are also stored as a property graph, which drives the evidence UI and the "how do I know this" answers.

* **Nodes:** `User`, `Account`, `Card`, `Merchant`, `Txn`, `Due`, `Policy`, `SIP`, `Source` (one per SMS, email or CSV row), `Insight`, `Reminder`.
* **Edges:**
  * `User-OWNS->Account|Card|Policy|SIP`
  * `Txn-FROM->Account|Card`
  * `Txn-TO->Merchant`
  * `Due-ON->Card|Policy|SIP`
  * `*-EVIDENCED_BY->Source`
  * `Insight-ABOUT->*`
  * `Reminder-FOR->Due`
* **Storage:** SQLite, `nodes(id, type, props_json)` and `edges(src, dst, rel, props_json)`, one database file per user under `data/`.
