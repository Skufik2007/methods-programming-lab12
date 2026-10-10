"""Регрессионные тесты на проблемы, найденные при ревью кода ИИ (см. reports/code-review.md).

Номер в имени теста совпадает с номером находки в отчёте.
"""

from datetime import date

import httpx

from app.models import Patient, UserRole


async def test_02_extreme_datetime_is_422_not_500(client: httpx.AsyncClient, session, make_user, make_doctor, auth):
    registrar = await make_user(UserRole.REGISTRAR)
    doctor = await make_doctor()
    patient = Patient(full_name="Пациент", birth_date=date(1990, 1, 1), policy_number="1" * 16)
    session.add(patient)
    await session.commit()

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
