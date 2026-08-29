# Reference batch distribution summary (N=3000)

## Method
- upi: 1252 (41.7%)
- card: 948 (31.6%)
- netbanking: 308 (10.3%)
- emandate: 248 (8.3%)
- wallet: 244 (8.1%)

## Decline code
- INSUFFICIENT_FUNDS: 752 (25.1%)
- DO_NOT_HONOR: 464 (15.5%)
- ISSUER_DOWN: 434 (14.5%)
- AUTH_TIMEOUT: 344 (11.5%)
- GATEWAY_TIMEOUT: 328 (10.9%)
- LIMIT_EXCEEDED: 217 (7.2%)
- CARD_EXPIRED: 167 (5.6%)
- INVALID_VPA: 125 (4.2%)
- RISK_BLOCKED: 86 (2.9%)
- MANDATE_REVOKED: 83 (2.8%)

## Recovery class (ground truth, holdout only — not used by the agent)
- action: 1634 (54.5%), self-recovery 9.4%
- time: 904 (30.1%), self-recovery 54.8%
- dead: 240 (8.0%), self-recovery 1.2%
- route: 222 (7.4%), self-recovery 27.0%
