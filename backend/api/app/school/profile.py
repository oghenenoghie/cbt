"""The school profile: name, contact details, motto and logo (ADR 0002 decision 12).

- Every signed-in member of the school can read it, because the web app shows the school's name
  and logo to everyone. Only school admins change it, with the CSRF token.
- The school code isn't part of what can be changed: everyone signs in with it.
- A logo is uploaded as a PNG or JPEG of at most 2 MB and 25 million pixels. The server
  re-encodes it as a PNG of at most 512 pixels a side and keeps only that, so metadata (such as
  where a photo was taken) and anything else hidden in the upload are dropped. Each logo gets a
  new storage key, so its URL changes with it and can be cached.
"""

from io import BytesIO
from uuid import uuid4

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile, status
from sqlalchemy.orm import Session

from app.auth.sessions import SessionPrincipal
from app.core.config import get_settings
from app.core.storage import Storage, get_storage
from app.db.session import get_db
from app.models import Tenant
from app.models.tenant import utc_now
from app.school.common import audit, invalid, member_access, write_access
from app.school.schemas import SchoolProfile, SchoolProfileUpdate

router = APIRouter(prefix="/school", tags=["school profile"])

LOGO_MAX_BYTES = 2 * 1024 * 1024
LOGO_MAX_PIXELS = 25_000_000
LOGO_SIZE = 512


class LogoError(ValueError):
    """An upload that can't be used as a logo; the message is for the person uploading."""


def clean_logo(data: bytes) -> bytes:
    """The upload re-encoded as a PNG of at most LOGO_SIZE pixels a side, or LogoError."""
    from PIL import Image, ImageOps, UnidentifiedImageError

    if not data:
        raise LogoError("The file is empty.")
    damaged = "This picture looks damaged and couldn't be opened. Upload a PNG or JPEG."
    try:
        with Image.open(BytesIO(data)) as upload:
            if upload.format not in {"PNG", "JPEG"}:
                raise LogoError("Upload the logo as a PNG or JPEG picture.")
            width, height = upload.size
            if width * height > LOGO_MAX_PIXELS:
                raise LogoError(
                    f"This picture is larger than {LOGO_MAX_PIXELS // 1_000_000} million pixels. "
                    "Make it smaller and upload it again."
                )
            image = ImageOps.exif_transpose(upload)
            image.load()
        transparent = image.mode in {"RGBA", "LA", "PA"} or (
            image.mode == "P" and "transparency" in image.info
        )
        image = image.convert("RGBA" if transparent else "RGB")
        image.thumbnail((LOGO_SIZE, LOGO_SIZE), Image.Resampling.LANCZOS)
        out = BytesIO()
        image.save(out, format="PNG", optimize=True)
    except LogoError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError) as error:
        raise LogoError(damaged) from error
    return out.getvalue()


def logo_url(tenant: Tenant) -> str | None:
    if tenant.logo_key is None:
        return None
    version = tenant.logo_key.rsplit("-", 1)[-1].removesuffix(".png")[:12]
    return f"{get_settings().api_v1_prefix}/school/profile/logo?v={version}"


def _profile(tenant: Tenant) -> SchoolProfile:
    return SchoolProfile(
        name=tenant.name,
        code=tenant.slug,
        address=tenant.address,
        phone=tenant.phone,
        email=tenant.email,
        motto=tenant.motto,
        logo_url=logo_url(tenant),
    )


def _tenant(db: Session, principal: SessionPrincipal) -> Tenant:
    return db.get(Tenant, principal.tenant_id)


def _remove_quietly(storage: Storage, key: str | None) -> None:
    """Delete a replaced logo after the change is committed. A leftover file is harmless."""
    if key is None:
        return
    try:
        storage.delete(key)
    except OSError:
        pass


@router.get("/profile", response_model=SchoolProfile)
def get_profile(
    principal: SessionPrincipal = Depends(member_access),
    db: Session = Depends(get_db),
) -> SchoolProfile:
    return _profile(_tenant(db, principal))


@router.patch("/profile", response_model=SchoolProfile)
def update_profile(
    body: SchoolProfileUpdate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> SchoolProfile:
    tenant = _tenant(db, principal)
    changes = body.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"] is None:
        raise invalid("The school's name can't be empty.")
    changed = sorted(f for f, v in changes.items() if getattr(tenant, f) != v)
    for field in changed:
        setattr(tenant, field, changes[field])
    if changed:
        details: dict = {"fields": changed}
        if "name" in changed:
            details["name"] = tenant.name
        audit(db, principal, request, "school.profile_updated", "school", tenant.id, details)
    db.commit()
    return _profile(tenant)


@router.put("/profile/logo", response_model=SchoolProfile)
async def upload_logo(
    request: Request,
    file: UploadFile = File(...),
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> SchoolProfile:
    """Set or replace the logo (PNG or JPEG). The server keeps only its own re-encoded PNG."""
    data = await file.read(LOGO_MAX_BYTES + 1)
    if len(data) > LOGO_MAX_BYTES:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE,
            detail=f"The logo is larger than {LOGO_MAX_BYTES // (1024 * 1024)} MB.",
        )
    try:
        png = clean_logo(data)
    except LogoError as error:
        raise invalid(str(error)) from error

    tenant = _tenant(db, principal)
    previous = tenant.logo_key
    key = f"{tenant.id}/school/logo-{uuid4().hex}.png"
    storage.put(key, png)
    tenant.logo_key = key
    tenant.logo_updated_at = utc_now()
    audit(
        db,
        principal,
        request,
        "school.logo_updated",
        "school",
        tenant.id,
        {"bytes": len(png), "replaced": previous is not None},
    )
    try:
        db.commit()
    except Exception:
        _remove_quietly(storage, key)
        raise
    _remove_quietly(storage, previous)
    return _profile(tenant)


@router.delete("/profile/logo", response_model=SchoolProfile)
def remove_logo(
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> SchoolProfile:
    tenant = _tenant(db, principal)
    previous = tenant.logo_key
    if previous is not None:
        tenant.logo_key = None
        tenant.logo_updated_at = utc_now()
        audit(db, principal, request, "school.logo_removed", "school", tenant.id)
        db.commit()
        _remove_quietly(storage, previous)
    return _profile(tenant)


@router.get(
    "/profile/logo",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}, 404: {"description": "No logo."}},
)
def get_logo(
    principal: SessionPrincipal = Depends(member_access),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
) -> Response:
    """The school's logo as a PNG. Its URL (`logo_url`) changes whenever the logo does."""
    tenant = _tenant(db, principal)
    if tenant.logo_key is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="This school has no logo.")
    try:
        data = storage.get(tenant.logo_key)
    except FileNotFoundError as error:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="This school has no logo.") from error
    return Response(
        content=data,
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=86400",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'",
        },
    )
