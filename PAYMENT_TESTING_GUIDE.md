# Pharmacy Payment Flow - Complete Testing Guide

## Environment Setup ✓
Your `.env` file has:
- `RAZORPAY_KEY_ID=<configured-in-environment>` ✓ **SET**
- `RAZORPAY_KEY_SECRET=<configured-in-environment>` ✓ **SET**
- `RAZORPAY_WEBHOOK_SECRET=<configured-in-environment>` ✓ **SET**

## Testing Checklist

### Step 1: Verify Backend Configuration Loaded
After docker-compose up, check backend logs:
```bash
docker logs hospital_backend 2>&1 | grep -E "(RAZORPAY|Starting|HOSPITAL API)"
```

**Expected output:**
```
=========================================================================
🚀 HOSPITAL API STARTING UP
=========================================================================
Environment: development
Debug: true
RAZORPAY_KEY_ID: <configured-in-environment>
RAZORPAY_WEBHOOK_SECRET: ✓ SET
=========================================================================
```

**If you see:**
- ❌ `RAZORPAY_KEY_ID: <configured-in-environment>
  - **Solution:** Check docker-compose.yml has `env_file: - ../.env`
  - Rebuild: `docker-compose build --no-cache && docker-compose up`

---

### Step 2: Test Configuration Endpoint
```bash
curl http://localhost:8000/api/v1/billing/config
```

**Expected response:**
```json
{
  "razorpay_key_id": "<configured-in-environment>",
  "razorpay_configured": true
}
```

**If you see:**
- `"razorpay_configured": false` or empty string → Environment variable not being read
  - Check backend logs for startup errors
  - Verify .env file has correct format

---

### Step 3: Pharmacy Dispense Flow (Online Payment)

#### 3a. Create a pharmacy dispense invoice
```bash
# First, identify a prescription in the pharmacy queue
# Then call:
curl -X POST http://localhost:8000/api/v1/pharmacy/{pq_id}/bill \
  -H "Authorization: Bearer {token}" \
  -H "Content-Type: application/json" \
  -d '{
    "line_items": [{
      "name": "Amoxicillin",
      "mfr": "ABC Pharma",
      "batch": "LOT123",
      "expiry": "12/2025",
      "qty": 1,
      "mrp": 150,
      "gst_pct": 5,
      "dis_pct": 0,
      "total": 157.50
    }],
    "discount": 0,
    "payment_method": "online"
  }'
```

**Check backend logs:**
```bash
docker logs hospital_backend 2>&1 | grep -E "Pharmacy bill:|Broadcasting payload"
```

**Expected sequence:**
```
Pharmacy bill: Start - pq_id=..., payment_method=online, discount=0
Pharmacy bill: Created invoice ... - payment_method=online, total=157.50
Pharmacy bill: Processing ONLINE payment for invoice ...
Pharmacy bill: Committed invoice to DB, now creating Razorpay order
Pharmacy bill: Razorpay order created: {...}
Pharmacy bill: Set razorpay_order_id=... on invoice
Pharmacy bill: Committed razorpay_order_id to DB
Pharmacy bill: Refreshed invoice - razorpay_order_id=..., status=draft
Pharmacy bill: Broadcasting payload - {"event": "payment_request", "razorpay_key_id": "<configured-in-environment>", "razorpay_order_id": "...", "invoice_id": "...", "tenant": "..."}
Pharmacy bill: Broadcasted payment_request to POS
```

**If you see:**
- ❌ `RAZORPAY_KEY_ID not configured` error
  - Solution: Ensure environment variables are passed to docker container
  - Verify docker-compose.yml line has: `env_file: - ../.env`
  
- ❌ `razorpay_order_id` is not showing in logs
  - Solution: Razorpay API call failed
  - Check `RAZORPAY_KEY_SECRET` is correct in .env

---

### Step 4: POS Screen Receives Request

**Navigate to:** `http://localhost:5173/pos/shankar` (your tenant schema)

**Open browser console** (F12 → Console tab)

**Expected logs:**
```
[PosScreen] Message received: {event: 'payment_request', razorpay_key_id: 'rzp_test_...', ...}
[PosScreen] Payment request - key: rzp_test_... order: order_...
[PosScreen] openRazorpayCheckout() called with: {...}
[PosScreen] Creating Razorpay with options: {key: 'rzp_test_...', order_id: 'order_...', ...}
[PosScreen] Razorpay initialized, opening modal...
```

**If you see:**
- ❌ `key: undefined` or `order: undefined`
  - Backend is NOT broadcasting the values correctly
  - Check Step 3 backend logs

- ❌ No logs at all
  - WebSocket connection not established
  - Check network tab in DevTools for connection to `ws://localhost:8000/ws/shankar/pos:payment`

---

### Step 5: Complete Razorpay Payment

**In the Razorpay modal:**
1. Use test card: `4111 1111 1111 1111`
2. Any future date for expiry (e.g., 12/25)
3. Any 3-digit CVV (e.g., 123)
4. Click "Pay"

**Monitor backend logs:**
```bash
docker logs hospital_backend 2>&1 | grep -E "Webhook:|payment captured"
```

**Expected sequence:**
```
Webhook: Received Razorpay webhook. Signature header present: True
Webhook: Parsed event: payment.captured
Webhook: Extracted data: order_id=order_..., payment_id=..., tenant=shankar, method=card
Webhook: Looking for invoice with order_id=... in tenant=shankar
Webhook: Processing payment for invoice ... (source=pharmacy, pharmacy_queue=...)
Webhook: Set invoice fields — razorpay_payment_id=..., payment_method=card, status=paid, paid_at=...
Webhook: Committed invoice payment
Webhook: Verified invoice in DB — status=paid, payment_method=card, paid_at=..., razorpay_payment_id=...
Webhook: Set payment_success to pos:payment
Webhook: Broadcasted visit_registered to queue:update
Webhook: Pharmacy payment success broadcast: order=..., payment=..., tenant=shankar
```

**If you see:**
- ❌ `Invoice not found for order_id=...`
  - The `razorpay_order_id` was NOT saved to the database
  - Check backend logs from Step 3 more carefully
  
- ❌ `Ignored event type`
  - Razorpay is sending an event type we don't handle
  - Should be "payment.captured" or "payment.authorized"

- ❌ `Invalid webhook signature`
  - `RAZORPAY_WEBHOOK_SECRET` doesn't match Razorpay dashboard
  - Get the correct secret from: Razorpay Dashboard → Settings → Webhooks

---

### Step 6: Verify Database Updated

**Check the invoice was marked paid:**
```bash
docker exec hospital_postgres psql -U hospital_user hospital -c "
  SELECT id, status, payment_method, paid_at, razorpay_payment_id 
  FROM shankar.invoices 
  WHERE source = 'pharmacy' 
  ORDER BY created_at DESC 
  LIMIT 1;
"
```

**Expected:**
```
                  id                  | status | payment_method |       paid_at       |  razorpay_payment_id
--------------------------------------+--------+----------------+---------------------+----------------------
 12345678-1234-1234-1234-123456789abc |  paid  | card           | 2026-04-15 10:30:45 | pay_Nv1234567890abc1
```

**If status is still "draft":**
- Webhook never updated the database
- Check backend logs from Step 5

---

### Step 7: Verify POS Screen Updated

**Browser console should show:**
```
[PosScreen] Payment success: {event: 'payment_success', razorpay_order_id: 'order_...', ...}
```

**On screen:** Should show success message and return to idle after 6 seconds

**If POS screen:**
- ❌ Still shows "Amount Due" screen
  - WebSocket event not received by POS
  - Check backend broadcast logs
  
- ❌ Returned to idle but no success shown
  - Success event came after state already reset
  - Check timing in POS screen logic

---

### Step 8: Verify Pharmacy Modal Closed

**If pharmacy UI:**
- ✅ Modal closed automatically → ✓ **FLOW COMPLETE**
- ⚠️ Still shows "Processing..." message
  - WebSocket event not received by modal
  - Check frontend logs for WebSocket connection issues

---

## Common Issues & Solutions

### Issue: "403 Forbidden" on checkout-static-next.razorpay.com/build/undefined
**Cause:** `razorpay_key_id` is undefined in frontend
**Solution:**
1. Check backend logs show RAZORPAY_KEY_ID is loaded
2. Check broadcast logs show key is included in payload
3. Check browser console shows key value in received message
4. If still undefined, rebuild docker: `docker-compose build --no-cache && docker-compose up`

### Issue: Invoice status stays "draft" after payment
**Cause:** Webhook not updating database
**Root causes:**
- Invoice not found by order_id
- Webhook event type not matched
- Database transaction not committed
**Solution:**
1. Check Step 5 logs for "Invoice not found for order_id"
2. Verify razorpay_order_id was saved in Step 3
3. Check webhook received correct event type
4. Review billing.py webhook code for any errors

### Issue: POS screen doesn't show payment success
**Cause:** WebSocket broadcast not received
**Debug:**
1. Check backend broadcast logs
2. Check browser DevTools → Network → WS for connected WebSocket
3. Verify message payload in Network tab of WS connection
4. Check browser console for any JS errors

---

## Quick Debug Commands

```bash
# View all backend logs related to payment
docker logs hospital_backend 2>&1 | grep -E "Pharmacy bill:|Webhook:|Broadcasting|Payment"

# View database invoice (adjust tenant and limit)
docker exec hospital_postgres psql -U hospital_user hospital -c "
  SELECT status, payment_method, razorpay_order_id, razorpay_payment_id 
  FROM shankar.invoices 
  WHERE source = 'pharmacy' 
  ORDER BY created_at DESC LIMIT 1;"

# Restart backend container
docker-compose restart backend

# Full rebuild
docker-compose build --no-cache && docker-compose up -d
```

---

## Final Verification Checklist

- [ ] Backend logs show RAZORPAY_KEY_ID loaded at startup
- [ ] Configuration endpoint returns razorpay_configured: true
- [ ] Pharmacy bill endpoint broadcasts with valid key and order_id
- [ ] POS screen receives WebSocket message with correct values
- [ ] Razorpay modal opens without 403 error
- [ ] Payment completes and webhook is received
- [ ] Invoice status changes to "paid" in database
- [ ] Pharmacy modal closes automatically
- [ ] POS screen shows success message

Once all ✓, the payment flow is complete!
