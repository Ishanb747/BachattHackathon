# CONTEXT
This folder has two things:
1. My existing voice agent (already built). Treat it as the base. Extend it, do not rewrite it.
2. A dataset folder of structured CSVs: loans, investments, SMS, insurance, emails, credit (CIBIL), bank/card statements.

We are building "Paisa Dost" for a Voice AI x Finance buildathon. Hindi/Hinglish/English voice agent that:
- Answers money questions, every answer cites its source ("from your SBI SMS on 3 Oct").
- Calls the user when an EMI/bill is due within 2 days and balance is lower than the amount.
- Gives one sharp credit insight from CIBIL data (high card utilisation, which card to pay first, interest saved).
- Takes at least one action: set_reminder (confirmed by voice first).
Extras: live evidence panel highlighting source rows, "what if I prepay 20k" by voice, money health score /100.
Stack: ElevenLabs for STT/TTS, OpenAI for the LLM. No Twilio, the outgoing call is simulated in the UI.

# STEP 0: DISCOVER (do this before writing any code, no questions to me)
1. Print the folder tree.
2. Read my existing voice agent code end to end. Summarize in <=10 lines: entry point, how it connects to ElevenLabs and OpenAI, what tools it already has, what is missing vs the list above.
3. For every CSV: filename, row count, columns, 3 sample rows. Then a DATA MAP: file -> what it gives us (txns, dues, balances, utilisation, APR, etc.).
4. Write SCHEMA.md with a unified schema (id, amount, merchant, date, type, category, source_ids[], source_label). Never guess columns.
5. Write PLAN.md: what you will add, what you will reuse, file by file. Stop and show me PLAN.md. Wait for my "go".

# RULES
- Plain code does all math and pattern detection. The LLM never calculates or invents numbers.
- Every fact carries proof: {text_key, value, source_ids[], source_label}. The agent says the source after each number. The UI highlights source_ids.
- Regex/rules first for parsing, LLM only for unparseable leftovers.
- Dedupe across SMS/email/statement on (amount, date +-1 day, fuzzy merchant). Keep all source ids.
- Voice replies: max 2 short sentences, no markdown, no lists. Confirm by voice before any action.
- Secrets in .env only. Match the existing code style and folder layout.

# BUILD (after I say go, one phase at a time, show real output on my data after each)
P1 Loader: parse everything into one list of txns and dues, deduped.
P2 Patterns: spend by category, spend vs usual, recurring charges, dues vs balance, card utilisation, duplicate charges.
P3 Recommendations: one line per pattern ranked by rupee impact, health score /100, card_paydown_plan(cards, cash) (avalanche by APR, target util <30%, returns pay per card and interest saved per month). Reuse it for what-if.
P4 Voice tools wired into my existing agent: get_insights, answer_question(q), what_if_prepay(amount), set_reminder(title, date). Update the agent system prompt: use numbers only from tools, cite source, max 2 sentences, call get_insights first on session start, stop when interrupted.
P5 Frontend (React + Tailwind + shadcn): left = call orb, "Check deadlines" button with fake incoming call screen, live transcript. Right = health score ring, evidence panel (glow on source_ids), reminder cards, top 3 insights. Always show a text transcript as fallback for Hindi STT errors.
P6 Outgoing call: "Check deadlines" fires only if due <=2 days AND balance < amount. Agent speaks first with the alert and source.

If we run behind, drop outgoing call polish first, then the health score. NEVER drop the evidence trail or the recommendation.

# DONE WHEN (run these and show results)
1. get_insights returns >=3 ranked insights, each with source_ids.
2. "Balance kitna hai?" returns balance with a source label.
3. Interrupting mid-sentence makes the agent stop and answer the new question.
4. "Agar 20 hazaar prepay karun?" returns new utilisation and interest saved.
5. "Reminder laga do" shows a reminder card after voice confirm.
6. A duplicate charge across SMS and statement merges into one fact with 2 source ids.
7. Outgoing call fires only when due <=2 days and balance < amount.
Finish with a README: setup, .env keys, run commands.

# STYLE
Concise. Code first, short notes. If a fix is simple, regenerate the file instead of explaining.