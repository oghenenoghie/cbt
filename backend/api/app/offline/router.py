"""Offline exams on lab computers (ADR 0007).

Three groups of endpoints:
- `/school/devices`: school admins register, rename and revoke lab computers.
- `/devices`: lab computers register themselves with a one-time code, then use their device
  token to list and download exam packages and upload results.
- `/exams/{id}/offline`: staff who can release an exam's results print its students' codes,
  export its package for USB, upload results brought back by USB, and see its offline status.
"""

import json
from datetime import timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth import throttle
from app.auth.dependencies import require_school_role
from app.auth.sessions import SessionPrincipal
from app.core.audit import record_audit
from app.core.config import get_settings
from app.db.session import get_db
from app.exams.access import viewer_for, visible_exam
from app.models import (
    Candidate,
    DeviceRegistration,
    Exam,
    LabDevice,
    OfflineCode,
    OfflinePackage,
    OfflineSubmission,
    Subject,
    Tenant,
    User,
)
from app.models.tenant import as_utc, normalize_school_code
from app.offline import crypto, releases, service
from app.offline.schemas import (
    REQUEST_FORMAT,
    SETUP_FORMAT,
    CodesOut,
    CodesRequest,
    DeviceExam,
    DeviceExamList,
    DeviceInfo,
    DeviceOut,
    DeviceRegister,
    DeviceRegistered,
    DeviceUpdate,
    Envelope,
    FileRegistered,
    FileRegistration,
    LabAppOut,
    OfflineStatus,
    OfflineStudent,
    OfflineSubmissionOut,
    PackageOut,
    RegistrationCodeOut,
    ResultsFile,
    ResultsFileOut,
    SchoolOut,
    StudentCode,
    SubmissionResult,
)
from app.school.common import audit, flush_or_conflict, get_owned, invalid, write_access

DEVICE_TOKEN_PREFIX = "cbt_device_"

admin_router = APIRouter(prefix="/school/devices", tags=["lab computers"])
device_router = APIRouter(prefix="/devices", tags=["lab computers"])
exam_router = APIRouter(prefix="/exams", tags=["offline exams"])
public_router = APIRouter(prefix="/offline", tags=["offline exams"])

admin_read = require_school_role("school_admin")
staff_read = require_school_role("school_admin", "teacher")
staff_write = require_school_role("school_admin", "teacher", write=True)


def _signing_public_key() -> str:
    try:
        return crypto.signing_public_key()
    except crypto.SigningNotConfigured as error:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error


def _school(tenant: Tenant) -> SchoolOut:
    return SchoolOut(id=tenant.id, code=tenant.slug, name=tenant.name)


def _devices_out(db: Session, devices: list[LabDevice]) -> list[DeviceOut]:
    names = dict(
        db.execute(
            select(User.id, User.display_name).where(
                User.id.in_({d.registered_by_id for d in devices if d.registered_by_id})
            )
        ).all()
    )
    return [
        DeviceOut(
            id=d.id,
            name=d.name,
            status=d.status,
            method=d.method,
            registered_at=as_utc(d.registered_at),
            registered_by_name=names.get(d.registered_by_id),
            last_seen_at=as_utc(d.last_seen_at) if d.last_seen_at else None,
            revoked_at=as_utc(d.revoked_at) if d.revoked_at else None,
        )
        for d in devices
    ]


# --- School admins: lab computers ----------------------------------------------------------------


@admin_router.get("", response_model=list[DeviceOut])
def list_devices(
    principal: SessionPrincipal = Depends(admin_read), db: Session = Depends(get_db)
) -> list[DeviceOut]:
    """The school's lab computers, active first, by name."""
    devices = list(db.scalars(select(LabDevice).where(LabDevice.tenant_id == principal.tenant_id)))
    devices.sort(key=lambda d: (d.status != "active", d.name.casefold()))
    return _devices_out(db, devices)


@admin_router.post("/registrations", response_model=RegistrationCodeOut, status_code=201)
def create_registration(
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> RegistrationCodeOut:
    """A one-time code to register one lab computer online. It is shown once and expires."""
    code = crypto.new_code()
    expires = service.now() + timedelta(hours=get_settings().device_registration_hours)
    registration = DeviceRegistration(
        tenant_id=principal.tenant_id,
        code_hash=crypto.sha256_hex(crypto.normalize_code(code)),
        created_by_id=principal.user_id,
        expires_at=expires,
    )
    db.add(registration)
    flush_or_conflict(db, "Try again.")
    audit(
        db,
        principal,
        request,
        "device.registration_created",
        "device_registration",
        registration.id,
    )
    db.commit()
    return RegistrationCodeOut(code=crypto.show_code(code), expires_at=expires)


@admin_router.post("/file-registration", response_model=FileRegistered, status_code=201)
def register_by_file(
    body: FileRegistration,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> FileRegistered:
    """Register a lab computer that never goes online, from the request file it wrote. Returns
    the setup file to carry back to it."""
    envelope = body.request
    try:
        data = json.loads(envelope.body)
    except ValueError as error:
        raise invalid("That registration request couldn't be read.") from error
    if envelope.format != REQUEST_FORMAT or not isinstance(data, dict):
        raise invalid("That isn't a registration request from the lab computer app.")
    name = str(data.get("name") or "").strip()[:120]
    public_key = str(data.get("public_key") or "")
    exchange_key = str(data.get("exchange_key") or "")
    if (
        not name
        or not crypto.valid_public_key(public_key)
        or not crypto.valid_exchange_key(exchange_key)
    ):
        raise invalid("That registration request is incomplete.")
    if not crypto.verify(envelope.model_dump(), public_key):
        raise invalid("That registration request's signature doesn't match: it may be damaged.")
    signing_public = _signing_public_key()
    device = LabDevice(
        tenant_id=principal.tenant_id,
        name=name,
        method="file",
        public_key=public_key,
        registered_by_id=principal.user_id,
    )
    db.add(device)
    flush_or_conflict(db, "That lab computer clashed with another change. Try again.")
    tenant = db.get(Tenant, principal.tenant_id)
    setup = crypto.seal(
        SETUP_FORMAT,
        {
            "device_id": device.id,
            "name": device.name,
            "school": _school(tenant).model_dump(),
            "signing_public_key": signing_public,
            # Only this computer can read the school key (decision 2).
            "school_key": crypto.seal_for(
                exchange_key, {"key": service.school_key(db, tenant.id)}, device.id
            ),
            "issued_at": service.now().isoformat(),
        },
        crypto.signing_key(),
    )
    audit(db, principal, request, "device.registered", "lab_device", device.id, {"method": "file"})
    db.commit()
    return FileRegistered(device=_devices_out(db, [device])[0], setup=Envelope(**setup))


def _release() -> tuple[dict, dict, object]:
    found = releases.latest()
    if found is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="No lab app has been published on this server yet."
        )
    return found


def _installer(path, name: str) -> FileResponse:
    return FileResponse(path, media_type="application/vnd.microsoft.portable-executable", filename=name)


@admin_router.get("/app", response_model=LabAppOut)
def lab_app(principal: SessionPrincipal = Depends(admin_read)) -> LabAppOut:
    """The newest lab app on this server, to install on lab computers."""
    _, body, _ = _release()
    return LabAppOut(**body)


@admin_router.get("/app/installer")
def lab_app_installer(principal: SessionPrincipal = Depends(admin_read)) -> FileResponse:
    """The newest installer, for a first install or a computer that never goes online."""
    _, body, path = _release()
    return _installer(path, body["file"])


def _admin_device(db: Session, principal: SessionPrincipal, device_id: str) -> LabDevice:
    return get_owned(db, LabDevice, device_id, principal, "Lab computer")


@admin_router.patch("/{device_id}", response_model=DeviceOut)
def rename_device(
    device_id: str,
    body: DeviceUpdate,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> DeviceOut:
    device = _admin_device(db, principal, device_id)
    device.name = body.name
    audit(db, principal, request, "device.renamed", "lab_device", device.id)
    db.commit()
    return _devices_out(db, [device])[0]


@admin_router.post("/{device_id}/revoke", response_model=DeviceOut)
def revoke_device(
    device_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(write_access),
    db: Session = Depends(get_db),
) -> DeviceOut:
    """Remove a lab computer: it can no longer download packages or upload results."""
    device = _admin_device(db, principal, device_id)
    if device.status != "revoked":
        device.status = "revoked"
        device.revoked_at = service.now()
        device.revoked_by_id = principal.user_id
        audit(db, principal, request, "device.revoked", "lab_device", device.id)
        db.commit()
    return _devices_out(db, [device])[0]


# --- Lab computers ---------------------------------------------------------------------------------


def current_device(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> LabDevice:
    """The lab computer making the request, from `Authorization: Device <token>`."""
    scheme, _, token = (authorization or "").partition(" ")
    device = None
    if scheme.lower() == "device" and token.startswith(DEVICE_TOKEN_PREFIX):
        device = db.scalar(
            select(LabDevice).where(LabDevice.token_hash == crypto.sha256_hex(token.strip()))
        )
    tenant = db.get(Tenant, device.tenant_id) if device else None
    if device is None or device.status != "active" or tenant is None or tenant.status != "active":
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="This lab computer isn't registered, or was removed. Ask a school admin.",
            headers={"WWW-Authenticate": "Device"},
        )
    device.last_seen_at = service.now()
    db.flush()
    return device


@device_router.post("/register", response_model=DeviceRegistered, status_code=201)
def register_device(
    body: DeviceRegister, request: Request, db: Session = Depends(get_db)
) -> DeviceRegistered:
    """Register this computer with a school admin's one-time code."""
    refused = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail="That school code and registration code don't match a valid registration.",
    )
    school_code = normalize_school_code(body.school_code)
    # Guessing codes is throttled per school, like failed sign-ins per account.
    throttled = throttle.throttle_key("device-registration", school_code)
    if throttle.is_blocked(db, throttled):
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many wrong registration codes for this school. Try again later.",
        )
    tenant = db.scalar(select(Tenant).where(Tenant.slug == school_code))
    code_hash = crypto.sha256_hex(crypto.normalize_code(body.registration_code))
    registration = (
        db.scalar(
            select(DeviceRegistration).where(
                DeviceRegistration.code_hash == code_hash,
                DeviceRegistration.tenant_id == tenant.id,
            )
        )
        if tenant is not None and tenant.status == "active"
        else None
    )
    at = service.now()
    if registration is None or registration.used_at or as_utc(registration.expires_at) <= at:
        record_audit(
            db,
            tenant_id=tenant.id if tenant else None,
            actor_type="anonymous",
            actor_id=None,
            action="device.registration_failed",
            resource_type="device_registration",
            request=request,
        )
        throttle.record_failure(db, throttled)
        db.commit()
        raise refused
    if not crypto.valid_public_key(body.public_key):
        raise invalid("The computer's public key isn't a valid Ed25519 key.")
    signing_public = _signing_public_key()
    token = crypto.new_token(DEVICE_TOKEN_PREFIX)
    device = LabDevice(
        tenant_id=tenant.id,
        name=body.name,
        method="online",
        public_key=body.public_key,
        token_hash=crypto.sha256_hex(token),
        registered_by_id=registration.created_by_id,
        last_seen_at=at,
    )
    db.add(device)
    db.flush()
    # One use only, even if two computers try the same code at once.
    claimed = db.execute(
        update(DeviceRegistration)
        .where(DeviceRegistration.id == registration.id, DeviceRegistration.used_at.is_(None))
        .values(used_at=at, device_id=device.id)
    ).rowcount
    if claimed != 1:
        db.rollback()
        raise refused
    record_audit(
        db,
        tenant_id=tenant.id,
        actor_type="device",
        actor_id=device.id,
        action="device.registered",
        resource_type="lab_device",
        resource_id=device.id,
        request=request,
        details={"method": "online", "name": device.name},
    )
    key = service.school_key(db, tenant.id)
    db.commit()
    return DeviceRegistered(
        device_id=device.id,
        device_token=token,
        school=_school(tenant),
        signing_public_key=signing_public,
        school_key=key,
    )


@device_router.get("/app/latest", response_model=Envelope)
def device_app_manifest(device: LabDevice = Depends(current_device)) -> Envelope:
    """The newest lab app's manifest, signed with the key that signs packages (decision 10)."""
    envelope, _, _ = _release()
    return Envelope(**envelope)


@device_router.get("/app/installer")
def device_app_installer(device: LabDevice = Depends(current_device)) -> FileResponse:
    _, body, path = _release()
    return _installer(path, body["file"])


@device_router.get("/me", response_model=DeviceInfo)
def device_info(
    device: LabDevice = Depends(current_device), db: Session = Depends(get_db)
) -> DeviceInfo:
    tenant = db.get(Tenant, device.tenant_id)
    db.commit()
    return DeviceInfo(
        device_id=device.id,
        name=device.name,
        school=_school(tenant),
        signing_public_key=_signing_public_key(),
    )


@device_router.get("/me/exams", response_model=DeviceExamList)
def device_exams(
    device: LabDevice = Depends(current_device), db: Session = Depends(get_db)
) -> DeviceExamList:
    """Published exams this computer can download now, soonest first."""
    at = service.now()
    exams = [
        e
        for e in db.scalars(
            select(Exam)
            .where(
                Exam.tenant_id == device.tenant_id,
                Exam.status == "published",
                Exam.offline_allowed.is_(True),
                Exam.closes_at > at,
            )
            .order_by(Exam.opens_at, Exam.id)
        )
        if service.downloadable(e, at)
    ]
    subjects = dict(
        db.execute(
            select(Subject.id, Subject.name).where(Subject.id.in_({e.subject_id for e in exams}))
        ).all()
    )
    out = []
    for exam in exams:
        batch = service.codes_batch(db, exam.id)
        out.append(
            DeviceExam(
                id=exam.id,
                title=exam.title,
                subject_name=subjects.get(exam.subject_id, ""),
                opens_at=as_utc(exam.opens_at),
                closes_at=as_utc(exam.closes_at),
                duration_minutes=exam.duration_minutes,
                instant_scores=exam.offline_instant_scores,
                codes_ready=batch > 0,
                codes_batch=batch,
            )
        )
    db.commit()
    return DeviceExamList(exams=out)


@device_router.get("/me/exams/{exam_id}/package", response_model=Envelope)
def device_package(
    exam_id: str,
    request: Request,
    device: LabDevice = Depends(current_device),
    db: Session = Depends(get_db),
) -> Envelope:
    """The signed package for an exam, recorded as issued to this computer."""
    exam = db.scalar(select(Exam).where(Exam.id == exam_id, Exam.tenant_id == device.tenant_id))
    if exam is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Exam not found.")
    _signing_public_key()
    envelope, package = service.build_package(db, exam, device=device)
    record_audit(
        db,
        tenant_id=device.tenant_id,
        actor_type="device",
        actor_id=device.id,
        action="offline.package_issued",
        resource_type="offline_package",
        resource_id=package.id,
        request=request,
        details={"exam": exam.id},
    )
    db.commit()
    return Envelope(**envelope)


@device_router.post("/me/submissions", response_model=SubmissionResult)
def device_submission(
    envelope: Envelope,
    request: Request,
    device: LabDevice = Depends(current_device),
    db: Session = Depends(get_db),
) -> SubmissionResult:
    """Upload one signed result. Uploading the same result again returns the first answer."""
    result = service.receive(
        db, device.tenant_id, envelope, via="device", device=device, request=request
    )
    db.commit()
    return result


@public_router.get("/signing-key")
def signing_key() -> dict:
    """The server's public key for checking exam packages (Ed25519, base64)."""
    return {"alg": "Ed25519", "public_key": _signing_public_key()}


# --- Staff: an exam's offline side -----------------------------------------------------------------


def _releasable(db: Session, principal: SessionPrincipal, exam_id: str) -> Exam:
    viewer = viewer_for(db, principal)
    exam, arm_ids = visible_exam(db, viewer, exam_id)
    if not viewer.can_release(exam, arm_ids):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail="Only the exam's teachers or a school admin can manage it on lab computers.",
        )
    return exam


@exam_router.post("/{exam_id}/offline/codes", response_model=CodesOut)
def create_codes(
    exam_id: str,
    body: CodesRequest,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> CodesOut:
    """Codes for students to sign in on lab computers, shown once for printing. Making codes
    again replaces those students' earlier codes; lab computers must download the exam again."""
    exam = _releasable(db, principal, exam_id)
    if exam.status != "published":
        raise HTTPException(409, detail="Codes can be printed once the exam is published.")
    if not exam.offline_allowed:
        raise HTTPException(
            409, detail="This exam's author turned off sitting it on lab computers."
        )
    if as_utc(exam.closes_at) <= service.now():
        raise HTTPException(409, detail="This exam has closed.")
    students = service.eligible_students(db, exam)
    if body.candidate_ids is not None:
        wanted = set(body.candidate_ids)
        if wanted - {s.candidate_id for s in students}:
            raise invalid("Codes can only be made for students the exam is set for.")
        students = [s for s in students if s.candidate_id in wanted]
    if not students:
        raise invalid("No students are enrolled in this exam's classes.")
    batch = service.codes_batch(db, exam.id) + 1
    iterations = get_settings().offline_code_iterations
    existing = {
        c.candidate_id: c
        for c in db.scalars(select(OfflineCode).where(OfflineCode.exam_id == exam.id))
    }
    codes = []
    for student in students:
        code = crypto.new_code()
        salt, digest = crypto.hash_code(code, iterations)
        row = existing.get(student.candidate_id)
        if row is None:
            row = OfflineCode(
                tenant_id=exam.tenant_id, exam_id=exam.id, candidate_id=student.candidate_id
            )
            db.add(row)
        row.salt, row.code_hash, row.iterations, row.batch = salt, digest, iterations, batch
        row.created_by_id, row.created_at = principal.user_id, service.now()
        codes.append(
            StudentCode(
                candidate_id=student.candidate_id,
                name=student.name,
                username=student.username,
                class_name=student.class_name,
                code=crypto.show_code(code),
            )
        )
    flush_or_conflict(db, "Codes were being made at the same time. Try again.")
    audit(
        db,
        principal,
        request,
        "offline.codes_created",
        "exam",
        exam.id,
        {"students": len(codes), "batch": batch},
    )
    db.commit()
    return CodesOut(exam_id=exam.id, batch=batch, codes=codes)


@exam_router.get("/{exam_id}/offline/package", response_model=Envelope)
def export_package(
    exam_id: str,
    request: Request,
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> Envelope:
    """The signed package as a file, for lab computers that never go online."""
    exam = _releasable(db, principal, exam_id)
    _signing_public_key()
    envelope, package = service.build_package(db, exam, exported_by=principal.user_id)
    audit(db, principal, request, "offline.package_exported", "offline_package", package.id)
    db.commit()
    return Envelope(**envelope)


@exam_router.post("/{exam_id}/offline/results", response_model=ResultsFileOut)
def upload_results(
    exam_id: str,
    body: ResultsFile,
    request: Request,
    principal: SessionPrincipal = Depends(staff_write),
    db: Session = Depends(get_db),
) -> ResultsFileOut:
    """Upload results brought back from lab computers by USB. Each is checked like an upload from
    the computer itself; results already received are recognised, not added twice."""
    exam = _releasable(db, principal, exam_id)
    results = []
    for envelope in body.submissions:
        try:
            result = service.receive(
                db,
                principal.tenant_id,
                envelope,
                via="file",
                uploaded_by=principal.user_id,
                exam_id=exam.id,
                request=request,
            )
        except HTTPException as error:
            submission_id = "?"
            try:
                submission_id = str(json.loads(envelope.body).get("submission_id") or "?")[:36]
            except (ValueError, AttributeError, ValidationError):
                pass
            result = SubmissionResult(
                submission_id=submission_id,
                status="rejected",
                reason=str(error.detail),
                flags=[],
                attempt_id=None,
            )
        db.flush()
        results.append(result)
    db.commit()
    return ResultsFileOut(results=results)


@exam_router.get("/{exam_id}/offline", response_model=OfflineStatus)
def offline_status(
    exam_id: str,
    principal: SessionPrincipal = Depends(staff_read),
    db: Session = Depends(get_db),
) -> OfflineStatus:
    """Codes, packages issued and results received for an exam sat on lab computers."""
    exam, _ = visible_exam(db, viewer_for(db, principal), exam_id)
    students = service.eligible_students(db, exam)
    codes = list(db.scalars(select(OfflineCode).where(OfflineCode.exam_id == exam.id)))
    batches = {c.candidate_id: c.batch for c in codes}
    packages = list(
        db.scalars(
            select(OfflinePackage)
            .where(OfflinePackage.exam_id == exam.id)
            .order_by(OfflinePackage.created_at.desc())
        )
    )
    submissions = list(
        db.scalars(
            select(OfflineSubmission)
            .where(OfflineSubmission.exam_id == exam.id)
            .order_by(OfflineSubmission.received_at.desc())
        )
    )
    device_ids = {p.device_id for p in packages if p.device_id} | {s.device_id for s in submissions}
    device_names = dict(
        db.execute(select(LabDevice.id, LabDevice.name).where(LabDevice.id.in_(device_ids))).all()
    )
    user_names = dict(
        db.execute(
            select(User.id, User.display_name).where(
                User.id.in_({p.exported_by_id for p in packages if p.exported_by_id})
            )
        ).all()
    )
    candidate_names = dict(
        db.execute(
            select(Candidate.id, Candidate.display_name).where(
                Candidate.id.in_({s.candidate_id for s in submissions})
            )
        ).all()
    )
    return OfflineStatus(
        exam_id=exam.id,
        offline_allowed=exam.offline_allowed,
        instant_scores=exam.offline_instant_scores,
        students=len(students),
        codes_issued=len(codes),
        codes_batch=max((c.batch for c in codes), default=0),
        roster=[
            OfflineStudent(
                candidate_id=s.candidate_id,
                name=s.name,
                username=s.username,
                class_name=s.class_name,
                code_batch=batches.get(s.candidate_id),
            )
            for s in students
        ],
        packages=[
            PackageOut(
                id=p.id,
                device_id=p.device_id,
                device_name=device_names.get(p.device_id) if p.device_id else None,
                exported_by_name=user_names.get(p.exported_by_id),
                codes_batch=p.codes_batch,
                instant_scores=p.instant_scores,
                created_at=as_utc(p.created_at),
            )
            for p in packages
        ],
        submissions=[
            OfflineSubmissionOut(
                submission_id=s.submission_id,
                candidate_id=s.candidate_id,
                candidate_name=candidate_names.get(s.candidate_id, ""),
                device_id=s.device_id,
                device_name=device_names.get(s.device_id, ""),
                status=s.status,
                reason=s.reason,
                flags=s.flags or [],
                attempt_id=s.attempt_id,
                received_via=s.received_via,
                received_at=as_utc(s.received_at),
            )
            for s in submissions
        ],
    )
