from pydantic import BaseModel, EmailStr


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
