# Credit Dost: demo script (≈6 minutes)

## Before you start (5 min, off stage)

- `python server.py`, then open http://127.0.0.1:8000. Log in as `lokesh.m993@gmail.com` / `paisadost`.
- **Warm everything once.** Click through every persona in the sidebar switcher and make one test call, so no cold start happens on stage.
- **Use headphones.** In Safari, echo cancellation is off, so a speaker can trigger false interruptions.
- **Keep two things ready:**
  - `tests/fixtures/sample_credit_report.txt` (synthetic) or a real credit-report PDF plus its password;
  - **Dues & reminders → "Simulate low balance"** switched **off**. You'll switch it on live.
- **Clear test reminders** so the reminder card lands on an empty list: `rm data/1749913629362473/reminders.json`
- **Have a backup:** a screen recording of this script, in case the venue's network or mic fails.

---

## 0:00 · The hook (Overview page, 30s)

> "Every Indian with a phone gets 30 money SMS a day: debits, bills, EMIs, credit checks. Nobody reads them. **Credit Dost reads all of them, and you just talk to it**, in Hindi, Hinglish or English. And every number it says comes with proof."

- **Point at the money health score** (64/100) and its five parts.
- **Point at "Monthly money":**
  > "It worked out that Lokesh earns about ₹48,000 a month from repeat deposits, and that **66% of it is already committed** to EMIs, premiums and SIPs. Nobody told it that; it learned it from his messages."
- **Point at the "Next 30 days" forecast:**
  > "This is his balance for the next month: his income comes in, his bills go out."

## 0:45 · Talk to it (Talk page)

Click **Talk now**. Credit Dost greets you and asks how it can help: balance, bills, spending, credit score or a purchase decision. It doesn't push alerts on an incoming call; those come by outgoing call (4:30).

1. **"Balance kitna hai?"**
   - The agent answers in Hindi, with the number spoken in words.
   - **Point at the right panel:**
     > "Watch the evidence: the exact Bank of Baroda SMS lights up under *Cited just now*, and *Talking about* shows the two accounts. **It cannot say a number without its source.**"
2. **Interrupt mid-answer:** "Ruko — mera CIBIL kaisa hai?"
   > "Barge-in: it stops and answers the new question."
   - Answer: his credit report was checked 8 times by 6 lenders in 90 days, so pause applications.
3. **"Meri monthly income aur fixed kharcha kitna hai?"**
   - ₹48k in, ₹32k fixed, 66%.
4. **"August mein mujhe kitna paisa aaya?"**
   - ₹89,768 received, cited.

## 2:30 · It's an advisor, not a reader

5. **"Kya mujhe Rolex khareedni chahiye?"**
   > "It looks up the price online, then reasons with his real money."
   - Answer: not now; ₹6.8 lakh against ₹69k in the bank, about N months of saving; a cheaper alternative.
6. **"Agar 20 hazaar prepay karun?"**
   - Shows the what-if card: interest saved and card utilisation.
   - *Tip: switch to **Devender Kumar** first, so the utilisation change is visible.*
7. **"Reminder laga do YES card bill ke liye kal"**, then **"haan"**
   > "Every action is confirmed by voice first."
   - The reminder card slides in.

## 3:45 · Feed it a document (the wow moment)

Drag `sample_credit_report.txt` (or a real credit-report PDF) **onto the chat**.

- The steps tick by: Reading → Extracting → **Verifying every number against the document** → Updating the money graph.
- **Result card:**
  - credit score **712**;
  - cards with a known limit 1 → 3;
  - card use **0.2% → 17.4%**;
  - health **64 → 60**.
  > "It learned his real limits and score in five seconds, and it rejects any number that isn't printed in the document."
- **If you're on a call,** Credit Dost says out loud what it learned.

## 4:30 · It calls *you* (outgoing call)

Use the sidebar **Demo** box. Click **Ring me now**, or press **Shift + R**. Better still, click **Ring in 10s** before you start talking, so the phone rings mid-sentence. The slower route also works: **Dues & reminders → Simulate low balance → Check deadlines**.

- An **incoming-call screen** rings, showing "Credit Dost" and the due with its source.
- **Accept.** The agent speaks first:
  > "हैलो Lokesh, क्रेडिट दोस्त बोल रहा हूँ… आपका SIP ₹251 कल ड्यू है… लेकिन BOB में सिर्फ़ ₹100 हैं…"
- Say: "It only calls when a bill is due within 2 days **and** the balance is lower. On real data nobody qualifies, so we simulate the low balance. The rule itself is unchanged."

## 5:15 · Proof & breadth

- **Insights page:**
  - **Score coach:** "Clear 3 past-due bills (₹1,997)", "Pause applications".
  - **Drafted refund email**, shown for **Ankit**: the Jio ₹300.80 double charge, quoting both SMS. Use "Copy email".
- **Evidence → Graph:** the money graph (accounts, cards, dues, merchants, sources).
- **Switch persona to Satish Kushwaha:**
  > "A stressed user: health 21, overdue EMIs, 18 credit checks. Same system, completely different advice."
- **Toggle dark mode** for the visual moment.

## 5:45 · Close

> "Regex-first parsing of real SMS, email and statements. All maths in plain code, never the LLM. Every spoken number carries its source. Hindi voice with barge-in. Proactive calls. It learns from any document you drop in. **Credit Dost: a money friend who shows its proof.**"

---

## Fallbacks if something breaks live

| Problem | Do this |
|---|---|
| Mic or STT misbehaves | Type the same questions in the chat box. The answers, evidence glow and voice still work. |
| Slow first answer | Talk about the evidence panel while it loads. Warm up next time. |
| Deadline check says "nothing due" | The "Simulate low balance" switch is off. Switch it on. |
| Document upload fails | Use the synthetic `sample_credit_report.txt`. It needs no password. |
| Network down | Play the backup recording. |
