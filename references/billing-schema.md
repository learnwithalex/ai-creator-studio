# Billing Schema Notes

- Unit: 1 credit = 1 GPU-second.
- Reserve startup credits at session start.
- Finalize debit from actual elapsed seconds on stop/disconnect.
- Persist wallet + transaction history in Postgres.
