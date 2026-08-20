from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    login_id: str   # accepts email OR username
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1)
    new_password: str = Field(..., min_length=8, description="Minimum 8 characters")


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    must_change_password: bool = False
    logo_url: str | None = None
    primary_color: str | None = None
    secondary_color: str | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class UserPublic(BaseModel):
    id: str
    email: str
    full_name: str
    role: str
    tenant_schema: str
