from pydantic import BaseModel, EmailStr, field_validator


class TenantCreate(BaseModel):
    hospital_name: str
    schema_name: str  # e.g. "shankar" — used as PostgreSQL schema name
    contact_email: EmailStr
    admin_email: EmailStr
    admin_full_name: str
    admin_password: str


class TenantPublic(BaseModel):
    id: str
    hospital_name: str
    schema_name: str
    contact_email: str
    is_active: bool


class DisplayTokenRead(BaseModel):
    display_token: str
    display_url_path: str  # frontend route: /display/{schema_name}/{display_token}


class TenantBrandingRead(BaseModel):
    hospital_name: str
    logo_url: str | None
    primary_color: str | None
    secondary_color: str | None


class TenantBrandingUpdate(BaseModel):
    primary_color: str | None = None
    secondary_color: str | None = None

    @field_validator("primary_color", "secondary_color")
    @classmethod
    def validate_hex_color(cls, value: str | None) -> str | None:
        if value is None:
            return None
        color = value.strip()
        if not color:
            return None
        import re
        if not re.match(r"^#[0-9a-fA-F]{6}$", color):
            raise ValueError("Color must be a 6-digit hex value such as #2563eb.")
        return color.lower()
