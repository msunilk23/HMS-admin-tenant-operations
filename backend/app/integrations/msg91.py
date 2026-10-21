"""MSG91 SMS and OTP adapter."""
from __future__ import annotations

from collections.abc import Mapping
import logging
import re
from typing import Any

import httpx

from app.core.sms import _normalise_phone


class MSG91Error(RuntimeError):
    """Safe provider error that never includes credentials, OTPs, or response bodies."""


class MSG91TimeoutError(MSG91Error):
    """MSG91 did not respond within the configured request timeout."""


class MSG91ProviderError(MSG91Error):
    """MSG91 returned an unsuccessful response."""


class _MSG91RequestLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        redacted = re.sub(
            r"(https://control\.msg91\.com/api/v5/[^\s\"?]+)\?[^\s\"]+",
            r"\1?<redacted>",
            message,
        )
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return True


logging.getLogger("httpx").addFilter(_MSG91RequestLogFilter())


class MSG91Provider:
    provider_name = "msg91"
    BASE_URL = "https://control.msg91.com/api/v5"

    def __init__(
        self,
        *,
        auth_key: str,
        otp_template_id: str,
        sms_template_id: str,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not auth_key.strip():
            raise ValueError("MSG91 auth key is required")
        if not otp_template_id.strip() or not sms_template_id.strip():
            raise ValueError("MSG91 OTP and SMS template IDs are required")
        if timeout_seconds <= 0:
            raise ValueError("MSG91 timeout must be positive")
        self._auth_key = auth_key
        self._otp_template_id = otp_template_id
        self._sms_template_id = sms_template_id
        self._timeout_seconds = timeout_seconds
        self._client = client

    async def send_otp(
        self,
        *,
        to: str,
        otp_length: int = 6,
        expiry_minutes: int | None = None,
    ) -> dict[str, Any]:
        if not 4 <= otp_length <= 10:
            raise ValueError("MSG91 OTP length must be between 4 and 10")
        if expiry_minutes is not None and expiry_minutes <= 0:
            raise ValueError("MSG91 OTP expiry must be positive")
        params: dict[str, str | int] = {
            "template_id": self._otp_template_id,
            "mobile": _normalise_phone(to),
            "otp_length": otp_length,
        }
        if expiry_minutes is not None:
            params["otp_expiry"] = expiry_minutes
        result = await self._request("POST", "/otp", params=params)
        self._raise_provider_error(result)
        return self._safe_result(result)

    async def verify_otp(self, *, to: str, otp: str) -> bool:
        result = await self._request(
            "GET",
            "/otp/verify",
            params={"mobile": _normalise_phone(to), "otp": otp},
        )
        response_type = str(result.get("type", "")).lower()
        if response_type == "error":
            message = str(result.get("message", "")).lower()
            if any(
                phrase in message
                for phrase in (
                    "invalid otp",
                    "otp not match",
                    "otp did not match",
                    "otp does not match",
                    "otp mismatch",
                    "otp expired",
                    "wrong otp",
                )
            ):
                return False
            raise MSG91ProviderError("MSG91 rejected OTP verification")
        if response_type != "success":
            raise MSG91ProviderError("MSG91 returned an invalid verification response")
        return True

    async def resend_otp(self, *, to: str, retry_type: str = "text") -> dict[str, Any]:
        if retry_type not in {"text", "voice"}:
            raise ValueError("MSG91 retry type must be text or voice")
        result = await self._request(
            "GET",
            "/otp/retry",
            params={"mobile": _normalise_phone(to), "retrytype": retry_type},
        )
        self._raise_provider_error(result)
        return self._safe_result(result)

    async def send_sms(
        self,
        *,
        to: str,
        variables: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        recipient: dict[str, str] = {"mobiles": _normalise_phone(to)}
        if variables:
            for name, value in variables.items():
                if re.fullmatch(r"var\d+", name) is None or not isinstance(value, str):
                    raise ValueError("Invalid MSG91 SMS template variable")
                recipient[name] = value
        result = await self._request(
            "POST",
            "/flow",
            json_body={
                "template_id": self._sms_template_id,
                "recipients": [recipient],
            },
        )
        self._raise_provider_error(result)
        return self._safe_result(result)

    async def send_message(self, *, to: str, body: str, **kwargs: Any) -> dict[str, Any]:
        variables = kwargs.get("variables")
        if variables is None:
            variables = {"var1": body}
        if not isinstance(variables, Mapping) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in variables.items()
        ):
            raise ValueError("MSG91 SMS variables must be a mapping of strings")
        return await self.send_sms(to=to, variables=variables)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, str | int] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        url = f"{self.BASE_URL}{path}"
        headers = {"authkey": self._auth_key}
        try:
            if self._client is None:
                async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                    response = await client.request(
                        method,
                        url,
                        params=params,
                        json=json_body,
                        headers=headers,
                    )
            else:
                response = await self._client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                    headers=headers,
                    timeout=self._timeout_seconds,
                )
        except httpx.TimeoutException:
            raise MSG91TimeoutError("MSG91 request timed out") from None
        except httpx.HTTPError:
            raise MSG91ProviderError("MSG91 request failed") from None

        if not response.is_success:
            raise MSG91ProviderError(f"MSG91 returned HTTP {response.status_code}")
        try:
            result = response.json()
        except ValueError:
            raise MSG91ProviderError("MSG91 returned an invalid response") from None
        if not isinstance(result, dict):
            raise MSG91ProviderError("MSG91 returned an invalid response")
        return result

    @staticmethod
    def _raise_provider_error(result: dict[str, Any]) -> None:
        response_type = str(result.get("type", "")).lower()
        if response_type == "error":
            raise MSG91ProviderError("MSG91 rejected the request")
        if response_type != "success":
            raise MSG91ProviderError("MSG91 returned an invalid response")

    @staticmethod
    def _safe_result(result: dict[str, Any]) -> dict[str, Any]:
        return {
            key: result[key]
            for key in ("type", "request_id")
            if key in result and isinstance(result[key], (str, int, bool))
        }
