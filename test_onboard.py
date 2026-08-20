import urllib.request, json

def post(url, data, headers={}):
    req = urllib.request.Request(url, data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json", **headers}, method="POST")
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

# Login
_, auth = post("http://localhost:8000/api/v1/auth/login",
    {"login_id": "admin@shankar-hospital.in", "password": "ChangeMe@123"})
token = auth["access_token"]
hdrs = {"Authorization": f"Bearer {token}"}

# Onboard a fresh doctor (new email each run to avoid 409)
import time
email = f"dr.test{int(time.time())}@shankar-hospital.in"
status, result = post("http://localhost:8000/api/v1/doctors/onboard", {
    "email": email,
    "password": "Doctor@123",
    "full_name": "Dr. Test Doctor",
    "specialization": "Cardiology",
    "consultation_fee": 800
}, hdrs)
print(f"Status: {status}")
print(json.dumps(result, indent=2))
