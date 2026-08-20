#!/usr/bin/env python3
"""
Test Pharmacy Payment Flow with Online Payment via Razorpay
"""
import json
import urllib.request
import time
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
print("PHARMACY PAYMENT FLOW TEST")
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
print(f"✓ Login successful. Token: {token[:20]}...")

# Step 2: Create a patient
print("\n[2] Creating test patient...")
patient_data = {
    "first_name": "Test",
    "last_name": f"Patient{int(time.time())}",
    "dob": "1990-01-01",
    "gender": "M",
    "contact": "9876543210",
    "phone": "9876543210",
    "email": f"patient{int(time.time())}@test.com",
    "address": "Test Address",
    "aadhar_number": f"123456{int(time.time()) % 1000000:06d}"
}
status, patient_response = make_request("POST", "/patients", patient_data, token)
if status not in [200, 201]:
    print(f"❌ Patient creation failed: {patient_response}")
    exit(1)

patient_id = patient_response["id"]
print(f"✓ Patient created: {patient_id}")

# Step 3: Create a visit
print("\n[3] Creating a visit...")
visit_data = {
    "patient_id": patient_id,
    "visit_type": "opd"
}
status, visit_response = make_request("POST", "/visits", visit_data, token)
if status not in [200, 201]:
    print(f"❌ Visit creation failed: {visit_response}")
    exit(1)

visit_id = visit_response["id"]
print(f"✓ Visit created: {visit_id}")

# Step 4: Create a consultation
print("\n[4] Creating a consultation with prescription...")
# First get a doctor ID
status, doctors_response = make_request("GET", "/doctors?limit=1", None, token)
if status != 200 or not doctors_response:
    print(f"❌ Failed to get doctor: {doctors_response}")
    exit(1)

doctor_id = doctors_response[0]["id"]
consultation_data = {
    "visit_id": visit_id,
    "doctor_id": doctor_id,
    "chief_complaint": "Test complaint",
    "diagnosis": "Test diagnosis",
    "examination": "Test examination",
    "medicines": [
        {
            "name": "Amoxicillin",
            "dosage": "500mg",
            "frequency": "3 times daily",
            "duration": "5 days",
            "quantity": 15
        }
    ]
}
status, consultation_response = make_request("POST", "/consultations", consultation_data, token)
if status not in [200, 201]:
    print(f"❌ Consultation creation failed: {consultation_response}")
    exit(1)

consultation_id = consultation_response["id"]
print(f"✓ Consultation created with prescription: {consultation_id}")

# Skip send-to-pharmacy step - it's automatic when prescription is created
print("\n[6] Getting pharmacy queue items...")
status, queue_response = make_request("GET", "/pharmacy/queue", None, token)
if status != 200:
    print(f"❌ Failed to get pharmacy queue: {queue_response}")
    exit(1)

if not queue_response:
    print(f"❌ No items in pharmacy queue")
    exit(1)

pq_id = queue_response[0]["id"]
print(f"✓ Found pharmacy queue item: {pq_id}")

# Step 7: CRITICAL - Test ONLINE payment (what we're testing)
print("\n[7] TESTING PHARMACY ONLINE PAYMENT FLOW NOW")
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

if status not in [200, 201]:
    print(f"\n❌ Dispense failed: Status {status}")
    print(json.dumps(dispense_response, indent=2))
    exit(1)

print(f"\n✓ Dispense successful. Response:")
print(json.dumps(dispense_response, indent=2))

invoice_id = dispense_response.get("id")
razorpay_order_id = dispense_response.get("razorpay_order_id")

print(f"\nInvoice ID: {invoice_id}")
print(f"Razorpay Order ID: {razorpay_order_id}")

if not razorpay_order_id:
    print(f"❌ ERROR: razorpay_order_id not returned!")
    exit(1)

print(f"\n✓ razorpay_order_id properly set: {razorpay_order_id}")

# Step 8: Check backend logs
print("\n[8] Checking backend logs for payment broadcasting...")
print("Command to run:")
print("  docker logs hospital_backend 2>&1 | grep -E 'Pharmacy bill:|Broadcasting|razorpay'")

print("\n" + "=" * 80)
print("✅ STEP 4 COMPLETE - Pharmacy online payment request successfully created")
print("=" * 80)
print(f"\nNext steps:")
print(f"1. Check backend logs show: 'Broadcasting payload to pos:payment'")
print(f"2. Open POS screen at: http://localhost:5173/pos/{TENANT}")
print(f"3. Check browser console (F12) for WebSocket message")
print(f"4. Complete payment with test card: 4111 1111 1111 1111, 12/25, 123")
print(f"5. Check webhook logs and verify invoice.status = 'paid'")
