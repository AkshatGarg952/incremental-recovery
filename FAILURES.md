# Where the agent gets it wrong

Five real cases, collected while building — three from a live run of the classifier
against `evals/golden_set.jsonl` on `gemini-2.5-flash-lite`, one showing the concrete
downstream consequence of one of those misclassifications through the real policy
call on `openai/gpt-oss-120b`, and one structural gap found by reading the code, not
yet observed live. Real inputs and outputs throughout — nothing here is invented.

The real number to keep in view: classifier accuracy on the golden set is
**76.7% (23/30)**, with a **6.7%** exception rate and a **53.3%** LLM-call rate.
That's not a footnote — it's the headline honesty this whole project is built
around applied one level down: the classifier is wrong about a quarter of the
time on the cases specifically chosen to be hard.

---

## 1. Rule-prior overconfidence on a "clean" code that happened to be noise

**`fail_0002953`** — `decline_code=INVALID_VPA`, `"Incorrect UPI ID provided"`.
Gold class: `time`. Classifier output: `action`, confidence **1.0**, source `rule`.

`INVALID_VPA` maps deterministically to `ACTION_RECOVERABLE` in
`src/simulator/decline_codes.py::DECLINE_CODE_CLASS` — a bad UPI handle should
need the customer to fix it. That mapping is right about 95% of the time by
construction (`_CODE_CLASS_NOISE_PROBABILITY = 0.05` in the same file — real
issuer codes aren't perfectly reliable signals even when the taxonomy says they
should be). This golden-set case landed in that 5%: the generator's ground truth
happened to be `time`, not `action`.

**The actual bug isn't the 5% miss — it's that the classifier never gets a
chance to catch it.** `rule_prior()` returns a class for any code in
`DECLINE_CODE_CLASS`, and `needs_llm_adjudication()` only routes to the LLM for
`DO_NOT_HONOR`, a message/code keyword conflict, or the one narrow
`DEAD`-class context check. A noisy-but-clean code sails through with
confidence `1.0` — the *same* confidence a correct clean-code case gets — and
nothing downstream ever sees a reason to doubt it. The rule prior is a
deliberate cost trade (near-zero-cost classification on ~47% of cases), and
the price of that trade is a small, silent, structurally invisible error rate
that the confidence score doesn't reflect at all.

---

## 2. A misclassification that becomes a real, unnecessary customer contact

**`fail_0002371`** — `decline_code=DO_NOT_HONOR`,
`"Do not honor - try an alternate payment method"`. Gold class: `route`.
Classifier output: `action`, confidence 0.7, source `llm`.

The rationale it gave: *"The raw message suggests trying an alternate payment
method, which implies the customer needs to take action, such as updating
their payment details or choosing a different method."* That's a reasonable
reading in isolation — but `route` in this project's taxonomy means the
*system* retries via a different rail without involving the customer at all
(`R2`: "retry via different rail/PSP"), while `action` means the customer has
to do something. The model conflated "alternate" with "the customer picks an
alternative," when the message was describing a system-side reroute.

Fed that wrong label into the real policy call (`openai/gpt-oss-120b`), here is
exactly what it proposed:

```
should_retry=True  should_contact=True  uplift=0.45  confidence=0.78
retry_schedule: [(4h, alternate_method)]
message: in_app / action_required_in_app, sent after 1h
rationale: "...prompting the customer to switch payment method via an
in-app notice and then retrying on an alternate method after a short
wait maximizes recovery chance without causing fatigue."
```

The system was already going to retry via `alternate_method` — which is
exactly the fix the raw message described — but the misclassification also
bought an unnecessary in-app notification: a real contact-budget spend and a
small fatigue cost for a case where the retry alone was very plausibly
sufficient. This is the concrete cost of a classification error: it doesn't
just mislabel a report row, it changes what actually happens to a customer.

---

## 3. The same confusion recurs on a second, unrelated phrasing

**`fail_0002921`** — `decline_code=DO_NOT_HONOR`,
`"Genuine decline - contact your bank"`. Gold class: `route`. Classifier
output: `action`, confidence 0.6.

**`fail_0002141`** — identical message, different failure. Same gold class
(`route`), same wrong output (`action`), confidence 0.6, near-identical
rationale both times: *"...suggests the customer needs to interact with their
bank to resolve the issue, which falls under the 'action' recovery class."*

Between this and case 2, **4 of the 8 `route`-gold cases in the golden set
were misclassified as `action`** (the confusion matrix: `route -> action: 4`,
`route -> route: 4` — a 50% error rate on this specific class). That's not
noise from one ambiguous message; it's the model applying a consistent,
incorrect heuristic — "the message names something related to the customer's
bank or payment method, therefore action" — regardless of whether the fix is
system-side or customer-side. `ROUTE_RECOVERABLE` has no clean decline code at
all (`GATEWAY_TIMEOUT`/`ISSUER_DOWN` both map to `time`, R1), so every single
`route` case in production would go through this same LLM call, with this
same bias.

---

## 4. Correctly flagged as uncertain, but the stated reasoning still leans the wrong way

**`fail_0001579`** — `decline_code=DO_NOT_HONOR`,
`"Transaction declined by issuing bank"`. Gold class: `time`. Classifier
output: **exception** (confidence 0.35, below the 0.6 threshold).

**`fail_0000309`** — `decline_code=DO_NOT_HONOR`, `"Do not honor"`. Gold
class: `time`. Also routed to exception, confidence 0.40.

These are the system working as designed — low confidence correctly routes
to the human exception list instead of forcing a guess (BUILD.md task 5.5).
But read the model's own words on `fail_0001579`: *"...it's more likely to
require customer action, but with low confidence due to the ambiguity."* And
on `fail_0000309`: *"...without more specific information, it's most likely
to require customer action, such as updating their card details."* In both
cases the true class was `time`, and in both cases the model's *tie-breaking
instinct*, even while correctly admitting uncertainty, leans toward `action`.
The safety net (the confidence threshold) caught these two. It would not
catch a case where the same bias pushed confidence just over 0.6 instead of
just under it — and cases 2 and 3 show that happening at 0.6 and 0.7.

---

## 5. The envelope's amount check is exact-string, not semantic

Not yet observed live — a structural gap found by reading the code, flagged
here because it's a *guaranteed* failure mode, not a probabilistic one.

`ENV_AMOUNT_BOUND` (`src/envelope/rules.py::AmountBoundRule`) checks a
proposal's `amount` message variable against
`_format_amount_paise(failure.amount_paise)`, which is exactly
`f"INR {amount_paise / 100:.2f}"`. If the model ever writes the amount as
`"₹500.00"`, `"Rs. 500"`, or `"500.00 INR"` — all semantically identical, all
things a model asked to fill in a currency variable might plausibly write —
the rule doesn't recognize them as correct. It silently overwrites the
variable with the canonical format and reports a `clamped` verdict, as if the
model had proposed the wrong amount rather than the right amount in the wrong
format. Behaviorally this is safe (the customer always sees the correct
number), but the suppression-by-rule report (`ENV_AMOUNT_BOUND` count) would
overstate how often the model is actually getting the amount *wrong*, when
most of that count is really a formatting mismatch the rule can't tell apart
from a real error. A real bug, currently masked by a rule that's stricter
than it needs to be.
