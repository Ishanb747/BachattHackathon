// Realistic sample data shaped exactly like API.md, for mock mode.

export const MOCK_USER = { id: "u_lokesh", name: "Lokesh Verma", email: "lokesh.m993@gmail.com" };

export const SOURCES = [
  { id: "sms:yes-0926", kind: "sms", at: "2026-09-26T10:12:00+05:30", sender: "VM-YESBNK",
    text: "YES BANK Credit Card XX9269 SEP-26 statement: Total due INR 399.97 Min due INR 399.97 Due by 10-OCT-2026.",
    label: "from your YES Bank SMS on 26 Sep" },
  { id: "email:yes-0926", kind: "email", at: "2026-09-26T11:40:00+05:30", sender: "estatement@yesbank.in",
    text: "Your YES BANK Credit Card statement for XX9269 is ready. Total amount due: Rs. 399.97. Payment due date: 10/10/2026.",
    label: "from your YES Bank email on 26 Sep" },
  { id: "sms:airtel-1001", kind: "sms", at: "2026-10-01T09:05:00+05:30", sender: "AD-AIRTEL",
    text: "Dear Customer, your Airtel Postpaid bill of Rs 195.88 for 98XXXXX412 is generated. Due date 15-Oct-2026. Pay via Airtel Thanks app.",
    label: "from your Airtel SMS on 1 Oct" },
  { id: "sms:lic-0930", kind: "sms", at: "2026-09-30T18:22:00+05:30", sender: "VK-LICIND",
    text: "LIC: Premium of Rs.1401/- for Policy No. XXXX5521 is due on 18/10/2026. Please pay before due date to keep your policy in force.",
    label: "from your LIC SMS on 30 Sep" },
  { id: "sms:bob-0922", kind: "sms", at: "2026-09-22T19:47:00+05:30", sender: "BP-BOBTXN",
    text: "Rs.1250.00 debited from A/c XX1626 on 22-09-26 to UPI/SWIGGY. Avl Bal Rs.30375.54. -Bank of Baroda",
    label: "from your BOB SMS on 22 Sep" },
  { id: "sms:indus-1012", kind: "sms", at: "2026-10-12T14:03:00+05:30", sender: "VM-INDUSB",
    text: "INR 4,860.00 spent on IndusInd Card XX3359 at AMAZON on 12-10-2026. Avl Lmt: INR 10,982.40. Not you? Call 18602677777",
    label: "from your IndusInd SMS on 12 Oct" },
  { id: "csv:indus-stmt-0930", kind: "csv", at: "2026-09-30T00:00:00+05:30", sender: "IndusInd card statement",
    text: "30-09-2026 | IndusInd Card XX3359 | Credit limit 50,000.00 | Outstanding 39,017.60 | Utilisation 78%",
    label: "from your IndusInd statement for Sep" },
  { id: "sms:swiggy-1003a", kind: "sms", at: "2026-10-03T21:14:00+05:30", sender: "VM-INDUSB",
    text: "INR 642.00 spent on IndusInd Card XX3359 at SWIGGY on 03-10-2026. Avl Lmt: INR 15,842.40.",
    label: "from your IndusInd SMS on 3 Oct" },
  { id: "csv:swiggy-1003b", kind: "csv", at: "2026-10-03T00:00:00+05:30", sender: "IndusInd card statement",
    text: "03-10-2026 | SWIGGY BANGALORE | 642.00 Dr  (also 04-10-2026 | SWIGGY BANGALORE | 642.00 Dr)",
    label: "from your IndusInd statement for Oct" },
  { id: "email:swiggy-1003", kind: "email", at: "2026-10-03T21:15:00+05:30", sender: "noreply@swiggy.in",
    text: "Your Swiggy order #1849302 of ₹642 has been delivered. Paid via IndusInd Credit Card XX3359.",
    label: "from your Swiggy email on 3 Oct" },
  { id: "csv:sip-1005", kind: "csv", at: "2026-10-05T00:00:00+05:30", sender: "Mutual fund statement",
    text: "05-10-2026 | SIP | Parag Parikh Flexi Cap Fund - Direct Growth | 2,000.00 | Units 27.311",
    label: "from your MF statement for Oct" },
  { id: "sms:bob-1014", kind: "sms", at: "2026-10-14T08:31:00+05:30", sender: "BP-BOBTXN",
    text: "Rs.2,150.00 debited from A/c XX1626 on 14-10-26 to UPI/ZOMATO. Avl Bal Rs.28,225.54. -Bank of Baroda",
    label: "from your BOB SMS on 14 Oct" },
];

export const DUES = [
  { id: "due:yes-xx9269-2610", title: "YES Bank card bill", amount: 399.97, due_date: "2026-10-10", kind: "card_bill",
    account_ref: "YES Bank XX9269", status: "overdue", source_ids: ["sms:yes-0926", "email:yes-0926"], source_label: "from your YES Bank SMS on 26 Sep" },
  { id: "due:airtel-2610", title: "Airtel postpaid", amount: 195.88, due_date: "2026-10-15", kind: "utility",
    account_ref: "Airtel 98XXXXX412", status: "due", source_ids: ["sms:airtel-1001"], source_label: "from your Airtel SMS on 1 Oct" },
  { id: "due:lic-5521-2610", title: "LIC premium", amount: 1401, due_date: "2026-10-18", kind: "insurance",
    account_ref: "LIC XXXX5521", status: "upcoming", source_ids: ["sms:lic-0930"], source_label: "from your LIC SMS on 30 Sep" },
];

export const BALANCES = [
  { account_ref: "Bank of Baroda XX1626", amount: 30375.54, at: "2026-09-22T19:47:00+05:30",
    source_ids: ["sms:bob-0922"], source_label: "from your BOB SMS on 22 Sep" },
];

export const INSIGHTS = [
  { id: "ins:util-indus", title: "Pay IndusInd XX3359 first", kind: "card_utilisation", impact_inr: 4860,
    detail: "Your IndusInd card is at 78% utilisation. Paying ₹20,000 brings it under 30% and saves about ₹590 a month in interest.",
    source_ids: ["csv:indus-stmt-0930", "sms:indus-1012"], source_label: "from your IndusInd statement for Sep" },
  { id: "ins:food-spend", title: "Food delivery up 38% vs usual", kind: "spend_vs_usual", impact_inr: 2150,
    detail: "You spent ₹7,820 on Swiggy and Zomato this month against a usual ₹5,670.",
    source_ids: ["sms:bob-1014", "sms:swiggy-1003a"], source_label: "from your BOB SMS on 14 Oct" },
  { id: "ins:dup-swiggy", title: "Swiggy ₹642 charged twice", kind: "duplicate", impact_inr: 642,
    detail: "The same ₹642 Swiggy order appears on 3 and 4 Oct on your IndusInd card. Raise a dispute.",
    source_ids: ["sms:swiggy-1003a", "csv:swiggy-1003b", "email:swiggy-1003"], source_label: "from your IndusInd SMS on 3 Oct" },
];

export const HEALTH = {
  score: 64, grade: "B",
  parts: [
    { name: "Bills paid on time", score: 22, max: 30, source_ids: ["sms:yes-0926", "sms:airtel-1001"] },
    { name: "Credit utilisation", score: 9, max: 25, source_ids: ["csv:indus-stmt-0930"] },
    { name: "Cash buffer", score: 18, max: 20, source_ids: ["sms:bob-0922"] },
    { name: "Spend stability", score: 10, max: 15, source_ids: ["sms:bob-1014"] },
    { name: "Insurance & SIP", score: 5, max: 10, source_ids: ["sms:lic-0930", "csv:sip-1005"] },
  ],
};

export const INITIAL_REMINDERS = [
  { id: "rem:lic", title: "Pay LIC premium ₹1,401", date: "2026-10-17", due_id: "due:lic-5521-2610",
    created_at: "2026-10-15T20:10:00+05:30", source_ids: ["sms:lic-0930"] },
];

export const WHATIF = {
  amount: 20000,
  card: "IndusInd XX3359",
  utilisation_before: 0.78,
  utilisation_after: 0.38,
  interest_saved_per_month: 590,
  plan: [{ card: "IndusInd XX3359", pay: 20000, util_before: 0.78, util_after: 0.38, interest_saved_per_month: 590 }],
  source_ids: ["csv:indus-stmt-0930"],
  source_label: "from your IndusInd statement for Sep",
};

export function buildGraph() {
  const nodes = [], links = [];
  const N = (id, type, label, props = {}) => nodes.push({ id, type, label, props });
  const L = (source, target, rel) => links.push({ source, target, rel });
  N("user:lokesh", "User", "Lokesh Verma");
  N("acct:bob-1626", "Account", "BOB XX1626", { balance: 30375.54 });
  N("card:indus-3359", "Card", "IndusInd XX3359", { limit: 50000, utilisation: 0.78 });
  N("card:yes-9269", "Card", "YES Bank XX9269");
  N("policy:lic-5521", "Policy", "LIC XXXX5521", { premium: 1401 });
  N("sip:ppfas", "SIP", "PPFAS Flexi Cap", { amount: 2000 });
  L("user:lokesh", "acct:bob-1626", "OWNS"); L("user:lokesh", "card:indus-3359", "OWNS");
  L("user:lokesh", "card:yes-9269", "OWNS"); L("user:lokesh", "policy:lic-5521", "HOLDS");
  L("user:lokesh", "sip:ppfas", "INVESTS");
  DUES.forEach((d) => {
    N(d.id, "Due", d.title, { amount: d.amount, due_date: d.due_date });
    const owner = d.id.includes("yes") ? "card:yes-9269" : d.id.includes("lic") ? "policy:lic-5521" : "user:lokesh";
    L(owner, d.id, "HAS_DUE");
    d.source_ids.forEach((s) => L(d.id, s, "FROM"));
  });
  [["m:swiggy", "Swiggy"], ["m:zomato", "Zomato"], ["m:amazon", "Amazon"], ["m:airtel", "Airtel"]].forEach(([id, l]) => N(id, "Merchant", l));
  const txns = [
    ["txn:1", 1250, "acct:bob-1626", "m:swiggy", ["sms:bob-0922"]],
    ["txn:2", 2150, "acct:bob-1626", "m:zomato", ["sms:bob-1014"]],
    ["txn:3", 4860, "card:indus-3359", "m:amazon", ["sms:indus-1012"]],
    ["txn:4", 642, "card:indus-3359", "m:swiggy", ["sms:swiggy-1003a", "csv:swiggy-1003b", "email:swiggy-1003"]],
    ["txn:5", 642, "card:indus-3359", "m:swiggy", ["csv:swiggy-1003b"]],
    ["txn:6", 2000, "acct:bob-1626", "sip:ppfas", ["csv:sip-1005"]],
    ["txn:7", 195.88, "acct:bob-1626", "m:airtel", []],
  ];
  txns.forEach(([id, amt, from, to, srcs]) => {
    N(id, "Txn", `₹${amt}`, { amount: amt });
    L(from, id, "PAID"); L(id, to, "TO");
    srcs.forEach((s) => L(id, s, "FROM"));
  });
  SOURCES.forEach((s) => N(s.id, "Source", s.sender, { kind: s.kind, text: s.text, at: s.at, label: s.label }));
  L("acct:bob-1626", "sms:bob-0922", "FROM");
  L("card:indus-3359", "csv:indus-stmt-0930", "FROM");
  L("policy:lic-5521", "sms:lic-0930", "FROM");
  L("due:airtel-2610", "m:airtel", "TO");
  INSIGHTS.forEach((i) => {
    N(i.id, "Insight", i.title, { impact_inr: i.impact_inr });
    i.source_ids.forEach((s) => L(i.id, s, "CITES"));
  });
  L("ins:util-indus", "card:indus-3359", "ABOUT");
  L("ins:dup-swiggy", "txn:4", "ABOUT"); L("ins:dup-swiggy", "txn:5", "ABOUT");
  INITIAL_REMINDERS.forEach((r) => { N(r.id, "Reminder", r.title); L(r.id, r.due_id, "FOR"); });
  return { nodes, links };
}
