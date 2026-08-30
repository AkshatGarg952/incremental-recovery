# Reference batch distribution summary (N=3000)

## Method
- upi: 1240 (41.3%)
- card: 964 (32.1%)
- netbanking: 301 (10.0%)
- wallet: 264 (8.8%)
- emandate: 231 (7.7%)

## Decline code
- DO_NOT_HONOR: 1097 (36.6%)
- INSUFFICIENT_FUNDS: 617 (20.6%)
- ISSUER_DOWN: 330 (11.0%)
- AUTH_TIMEOUT: 250 (8.3%)
- GATEWAY_TIMEOUT: 245 (8.2%)
- LIMIT_EXCEEDED: 176 (5.9%)
- CARD_EXPIRED: 129 (4.3%)
- INVALID_VPA: 96 (3.2%)
- RISK_BLOCKED: 41 (1.4%)
- MANDATE_REVOKED: 19 (0.6%)

## Recovery class (ground truth, holdout only — not used by the agent)
- action: 1626 (54.2%), self-recovery 10.4%
- time: 911 (30.4%), self-recovery 53.6%
- route: 241 (8.0%), self-recovery 32.0%
- dead: 222 (7.4%), self-recovery 0.9%
