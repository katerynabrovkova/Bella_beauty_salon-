from datetime import timedelta

# A PENDING_PAYMENT appointment holds its slot for 15 minutes before the
# expiry sweep releases it. Fixed for v1, not salon-configurable — a
# payment-UX parameter, not a business lever (docs/DECISIONS.md § Business
# rules).
SLOT_HOLD_DURATION = timedelta(minutes=15)
