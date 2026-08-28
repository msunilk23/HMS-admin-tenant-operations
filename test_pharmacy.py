import requests
sess = requests.Session()
login_res = sess.post("http://127.0.0.1:8000/api/v1/auth/login", json={"username": "e2e_pharmacist_task7", "password": "E2ePharmacist@123"})
print("login status:", login_res.status_code)
print("login response:", login_res.text)

if login_res.status_code == 200:
    # list pharmacy queue
    queue_res = sess.get("http://127.0.0.1:8000/api/v1/pharmacy")
    print("queue status:", queue_res.status_code)
    queue_data = queue_res.json()
    print("queue data:", queue_data)

    target_id = None
    for item in queue_data:
        patient = item.get("patient", {})
        patient_name = f"{patient.get('first_name', '')} {patient.get('last_name', '')}".strip()
        if "E2E" in patient_name or "Patient" in patient_name:
            target_id = item.get("id")
            print("Found target item id:", target_id)

    if target_id:
        payload = {
            "facility_id": "016e30e1-d9b4-555f-b538-7ce7747376a3",
            "location_id": "9cb201ea-b1b8-5857-8f7a-764967d21f17"
        }
        start_res = sess.post(f"http://127.0.0.1:8000/api/v1/pharmacy/{target_id}/start", json=payload)
        print("start status:", start_res.status_code)
        print("start response:", start_res.text)
    else:
        print("E2E Patient not found in queue")
