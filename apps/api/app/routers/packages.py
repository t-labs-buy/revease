"""Brand Packages — reusable brand kits (intro/outro, logo, fonts, colours) that
skills can reference to brand generated output."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import CurrentUser
from app.db import get_session
from app.models import BrandPackage
from app.ownership import owned_row

router = APIRouter(prefix="/packages", tags=["packages"])


class PackageIn(BaseModel):
    name: str
    settings: dict = Field(default_factory=dict)


class PackageOut(BaseModel):
    id: str
    name: str
    settings: dict


def _out(p: BrandPackage) -> PackageOut:
    return PackageOut(id=p.id, name=p.name, settings=p.settings_json or {})


@router.get("", response_model=list[PackageOut])
def list_packages(
    user: CurrentUser,
    scope: str = Query(default="mine", pattern="^(mine|all)$"),
    db: Session = Depends(get_session),
) -> list[PackageOut]:
    q = select(BrandPackage).order_by(BrandPackage.created_at.desc())
    if not (scope == "all" and user.is_admin):
        q = q.where(BrandPackage.user_id == user.id)
    return [_out(p) for p in db.scalars(q)]


@router.get("/{package_id}", response_model=PackageOut)
def get_package(
    package_id: str, user: CurrentUser, db: Session = Depends(get_session)
) -> PackageOut:
    return _out(owned_row(db, user, BrandPackage, package_id, "package"))


@router.post("", response_model=PackageOut)
def create_package(
    payload: PackageIn, user: CurrentUser, db: Session = Depends(get_session)
) -> PackageOut:
    p = BrandPackage(
        user_id=user.id,
        name=payload.name.strip() or "Untitled package",
        settings_json=payload.settings,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return _out(p)


@router.put("/{package_id}", response_model=PackageOut)
def update_package(
    package_id: str, payload: PackageIn, user: CurrentUser, db: Session = Depends(get_session)
) -> PackageOut:
    p = owned_row(db, user, BrandPackage, package_id, "package")
    p.name = payload.name.strip() or p.name
    p.settings_json = payload.settings
    db.commit()
    db.refresh(p)
    return _out(p)


@router.delete("/{package_id}")
def delete_package(
    package_id: str, user: CurrentUser, db: Session = Depends(get_session)
) -> dict:
    db.delete(owned_row(db, user, BrandPackage, package_id, "package"))
    db.commit()
    return {"ok": True}
