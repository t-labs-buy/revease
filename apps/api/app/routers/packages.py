"""Brand Packages — reusable brand kits (intro/outro, logo, fonts, colours) that
skills can reference to brand generated output."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_session
from app.models import BrandPackage

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
def list_packages(db: Session = Depends(get_session)) -> list[PackageOut]:
    return [_out(p) for p in db.scalars(select(BrandPackage).order_by(BrandPackage.created_at.desc()))]


@router.get("/{package_id}", response_model=PackageOut)
def get_package(package_id: str, db: Session = Depends(get_session)) -> PackageOut:
    p = db.get(BrandPackage, package_id)
    if p is None:
        raise HTTPException(status_code=404, detail="package not found")
    return _out(p)


@router.post("", response_model=PackageOut)
def create_package(payload: PackageIn, db: Session = Depends(get_session)) -> PackageOut:
    p = BrandPackage(name=payload.name.strip() or "Untitled package", settings_json=payload.settings)
    db.add(p)
    db.commit()
    db.refresh(p)
    return _out(p)


@router.put("/{package_id}", response_model=PackageOut)
def update_package(package_id: str, payload: PackageIn, db: Session = Depends(get_session)) -> PackageOut:
    p = db.get(BrandPackage, package_id)
    if p is None:
        raise HTTPException(status_code=404, detail="package not found")
    p.name = payload.name.strip() or p.name
    p.settings_json = payload.settings
    db.commit()
    db.refresh(p)
    return _out(p)


@router.delete("/{package_id}")
def delete_package(package_id: str, db: Session = Depends(get_session)) -> dict:
    p = db.get(BrandPackage, package_id)
    if p:
        db.delete(p)
        db.commit()
    return {"ok": True}
