#!/usr/bin/env python3
"""
Test Pharmacy Online Payment Flow - Direct Bill Endpoint Test
"""
import json
import urllib.request
from urllib.error import HTTPError

BASE_URL = "http://localhost:8000/api/v1"
TENANT = "shankar"

def make_request(method, endpoint, data=None, token=None):
    """Make HTTP request and return (status, response_json)"""
    url = f"{BASE_URL}{endpoint}"
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode() if data else None,
        headers=headers,
        method=method
    )
    
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except HTTPError as e:
        return e.code, json.loads(e.read())

print("=" * 80)
print("PHARMACY ONLINE PAYMENT - DIRECT ENDPOINT TEST")
print("=" * 80)

# Step 1: Login
print("\n[1] Logging in as admin...")
status, auth_response = make_request("POST", "/auth/login", {
    "login_id": "admin@shankar-hospital.in",
    "password": "ChangeMe@123"
})
if status != 200:
    print(f"❌ Login failed: {auth_response}")
    exit(1)

token = auth_response["access_token"]
print(f"✓ Login successful")

# Step 2: Use an existing pharmacy queue item
print("\n[2] Using existing pharmacy queue item for testing...")
pq_id = "fd2af670-719b-4ee3-b44f-6f83f1eddd92"
print(f"✓ Pharmacy Queue ID: {pq_id}")

# Step 3: MAIN TEST - Bill with ONLINE payment
print("\n[3] TESTING PHARMACY ONLINE PAYMENT ENDPOINT")
print("=" * 80)

dispense_data = {
    "line_items": [
        {
            "name": "Amoxicillin",
            "mfr": "ABC Pharma",
            "batch": "LOT123",
            "expiry": "12/2025",
            "qty": 1,
            "mrp": 150,
            "gst_pct": 5,
            "dis_pct": 0,
            "total": 157.50
        }
    ],
    "discount": 0,
    "payment_method": "online"
}

print(f"\nDispense request payload:")
print(json.dumps(dispense_data, indent=2))

status, dispense_response = make_request(
    "POST",
    f"/pharmacy/{pq_id}/bill",
    dispense_data,
    token
)

print(f"\n[Response Status: {status}]")

if status not in [200, 201]:
    print(f"❌ Dispense failed!")
    print(json.dumps(dispense_response, indent=2))
    exit(1)

print(f"✓ Dispense successful!")
print(json.dumps(dispense_response, indent=2))

invoice_id = dispense_response.get("id")
razorpay_order_id = dispense_response.get("razorpay_order_id")
razorpay_key_id = dispense_response.get("razorpay_key_id")

print(f"\n" + "=" * 80)
print("CRITICAL VALUES IN RESPONSE:")
print(f"  Invoice ID: {invoice_id}")
print(f"  Razorpay Order ID: {razorpay_order_id}")
print(f"  Razorpay Key ID: {razorpay_key_id}")
print(f"=" * 80)

if not razorpay_order_id:
    print(f"\n❌ ERROR: razorpay_order_id not in response! Payment will fail.")
    print(f"Response keys: {list(dispense_response.keys())}")
    exit(1)

if not razorpay_key_id:
    print(f"\n⚠️  WARNING: razorpay_key_id not in response")
    print(f"Checking /api/v1/billing/config endpoint...")
    status, config = make_request("GET", "/billing/config", None, token)
    if status == 200:
        print(f"✓ Backend has Razorpay key: {config['razorpay_key_id']}")
    else:
        print(f"❌ Backend config endpoint failed")

print(f"\n✅ STEP 3 COMPLETE - Online payment request successfully created")

# Step 4: Check backend logs
print("\n[4] Check backend logs with:")
print(f"    docker logs hospital_backend 2>&1 | grep -E 'Pharmacy bill:|Broadcasting'")

# Step 5: Check database was updated
print("\n[5] Verify invoice was created:")
print(f"    docker exec hospital_postgres psql -U hospital_user hospital -c \\")
print(f"      \"SELECT id, status, razorpay_order_id FROM {TENANT}.invoices WHERE id = '{invoice_id}';\"")

print("\n" + "=" * 80)
print("✅ SUCCESS - Now manually test the POS flow:")
print(f"  1. Open: http://localhost:5173/pos/{TENANT}")
print(f"  2. Open DevTools (F12) → Console")
print(f"  3. Should see WebSocket message with razorpay_key_id and order_id")
print(f"  4. Razorpay modal should open WITHOUT 403 error")
print(f"  5. Complete payment with test card: 4111 1111 1111 1111, 12/25, 123")
print("=" * 80)
