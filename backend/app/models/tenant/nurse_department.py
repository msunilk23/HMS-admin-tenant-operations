import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NurseDepartment(Base):
    """Maps a nurse (user_id from public.users) to a department in this tenant schema."""
    __tablename__ = "nurse_departments"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(nullable=False, index=True)  # public.users.id
    department_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("departments.id"), nullable=False, index=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    assigned_by: Mapped[uuid.UUID] = mapped_column(nullable=False)  # public.users.id
