"""Регрессионные тесты на проблемы, найденные при ревью кода ИИ (см. reports/code-review.md).

Номер в имени теста совпадает с номером находки в отчёте.
"""

import asyncio
from datetime import date, datetime, timedelta

import httpx
from sqlalchemy import func, select

from app import db
from app.main import app
from app.models import Appointment, AppointmentStatus, Patient, User, UserRole
from app.routers.appointments import get_now


async def _patient(session, policy_digit: str) -> Patient:
    patient = Patient(full_name="Пациент", birth_date=date(1990, 1, 1), policy_number=policy_digit * 16)
    session.add(patient)
    await session.commit()
    return patient


async def test_02_extreme_datetime_is_422_not_500(client: httpx.AsyncClient, session, make_user, make_doctor, auth):
    registrar = await make_user(UserRole.REGISTRAR)
    doctor = await make_doctor()
    patient = await _patient(session, "1")

    response = await client.post(
        "/api/appointments",
        json={
            "doctor_id": doctor.id,
            "patient_id": patient.id,
            "starts_at": "0001-01-01T00:00:00+05:00",
            "ends_at": "0001-01-01T01:00:00+05:00",
        },
        headers=auth(registrar),
    )

    assert response.status_code == 422
    assert "out of the supported range" in response.text


async def test_03_started_appointment_cannot_be_cancelled(
    client: httpx.AsyncClient, session, make_user, make_doctor, auth, now: datetime
):
    registrar = await make_user(UserRole.REGISTRAR)
    doctor = await make_doctor()
    doctor_user = await session.get(User, doctor.user_id)
    patient = await _patient(session, "2")
    starts_at = now + timedelta(hours=1)  # 10:00 по Москве — начало слота
    created = await client.post(
        "/api/appointments",
        json={
            "doctor_id": doctor.id,
            "patient_id": patient.id,
            "starts_at": starts_at.isoformat(),
            "ends_at": (starts_at + timedelta(minutes=30)).isoformat(),
        },
        headers=auth(registrar),
    )
    assert created.status_code == 201, created.text
    appointment_id = created.json()["id"]

    app.dependency_overrides[get_now] = lambda: starts_at + timedelta(days=1)  # приём был вчера
    cancel = await client.post(f"/api/appointments/{appointment_id}/cancel", headers=auth(registrar))
    no_show = await client.post(f"/api/appointments/{appointment_id}/no-show", headers=auth(doctor_user))

    assert cancel.status_code == 422
    assert cancel.json()["detail"].startswith("The appointment has already started")
    assert no_show.status_code == 200
    assert no_show.json()["status"] == "no_show"


async def test_04_concurrent_overlapping_bookings_one_wins(
    client: httpx.AsyncClient, session, make_user, make_doctor, auth, now: datetime
):
    registrar = await make_user(UserRole.REGISTRAR)
    doctor = await make_doctor()
    first, second = await _patient(session, "3"), await _patient(session, "4")
    start = now + timedelta(hours=1)

    def body(patient: Patient, starts_at: datetime) -> dict[str, object]:
        return {
            "doctor_id": doctor.id,
            "patient_id": patient.id,
            "starts_at": starts_at.isoformat(),
            "ends_at": (start + timedelta(hours=1)).isoformat(),
        }

    # Интервалы 10:00-11:00 и 10:30-11:00 пересекаются, но начинаются в разное время:
    # частичный уникальный индекс (doctor_id, starts_at) такую пару не ловит.
    responses = await asyncio.gather(
        client.post("/api/appointments", json=body(first, start), headers=auth(registrar)),
        client.post("/api/appointments", json=body(second, start + timedelta(minutes=30)), headers=auth(registrar)),
    )

    assert sorted(r.status_code for r in responses) == [201, 409]
    async with db.SessionFactory() as fresh:
        active = await fresh.scalar(
            select(func.count()).select_from(Appointment).where(Appointment.status != AppointmentStatus.CANCELLED)
        )
    assert active == 1
