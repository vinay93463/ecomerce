from sqlalchemy import String, Float, Integer
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


class Order(Base):

    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        index=True
    )

    customer_name: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    email: Mapped[str] = mapped_column(
        String(150),
        nullable=False
    )

    address: Mapped[str] = mapped_column(
        String(500),
        nullable=False
    )

    total: Mapped[float] = mapped_column(
        Float,
        default=0,
        nullable=False
    )

    status: Mapped[str] = mapped_column(
        String(50),
        default="Pending",
        nullable=False
    )