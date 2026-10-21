# MSG91 SMS/OTP Manual Test

Automated MSG91 tests use mocked HTTP responses and do not contact MSG91. Live
requests are manual only; do not add provider credentials to source control,
environment files, command-line arguments, test output, or logs.

## Prerequisites

- A development/test HMS tenant and its tenant UUID.
- A valid MSG91 auth key entered in the tenant's Integrations page as the
  write-only `Auth Key`.
- Approved MSG91 OTP and SMS Flow templates configured for that connection.
- The matching OTP and SMS template IDs saved as public integration
  configuration.
- The test communication connection enabled in `TEST`, with the tenant's `SMS`
  route selecting MSG91.
- A controlled test mobile number able to receive the approved template.

Never perform this procedure against production or a number without consent.
The HMS `TEST` connection label does not guarantee that MSG91 is in a sandbox;
the adapter makes real MSG91 API requests and can deliver real messages.

## Send and verify a test OTP

From the backend virtual environment, start a Python prompt in the backend
directory. The tenant UUID, mobile number, and received OTP are entered
interactively; the MSG91 auth key is read from the encrypted tenant integration
record and is never printed.

```python
import asyncio
import getpass
import uuid

from app.db.engine import AsyncSessionLocal
from app.services.tenant_integration_service import get_msg91_sms_provider


async def main():
    tenant_id = uuid.UUID(input("Development tenant UUID: ").strip())
    phone = input("Controlled test mobile number: ").strip()
    async with AsyncSessionLocal() as session:
        provider = await get_msg91_sms_provider(session=session, tenant_id=tenant_id)
        await provider.send_otp(to=phone)
        otp = getpass.getpass("OTP received on the test phone: ")
        verified = await provider.verify_otp(to=phone, otp=otp)
        print("OTP verified" if verified else "OTP was rejected")


asyncio.run(main())
```

Use `provider.resend_otp(to=phone)` only when manually testing the approved
template's resend behavior. A false verification result means MSG91 rejected
the OTP; network, timeout, authentication, and other provider failures raise a
safe provider error without returning response bodies, auth keys, or OTPs.

## Run the mocked tests

From the backend directory:

```powershell
..\.venv\Scripts\python.exe -m pytest tests\test_msg91_provider.py tests\test_tenant_communication_routes.py -q
```
