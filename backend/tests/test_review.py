"""Problems found in the step-by-step review. Each test failed before its fix."""
from datetime import timedelta

from app.api import today

T = today()
D = T.isoformat()
TOMORROW = (T + timedelta(days=1)).isoformat()
LAST_WEEK = (T - timedelta(days=7)).isoformat()


def post(g, path, body, headers=None):
    return g.client.post(f"/api{path}", json=body, headers=headers or g.owner)


def test_entries_cannot_be_dated_in_the_future(group):
    u = group.units["hospital"]
    assert post(group, "/documents/collection", {"unit_id": u, "date": TOMORROW, "amount": "1", "payment_mode": "cash"}).status_code == 422
    assert post(group, "/documents/expense", {"unit_id": u, "date": TOMORROW, "amount": "1", "paid": True, "payment_mode": "cash"}).status_code == 422
    assert post(group, "/documents/claim", {"unit_id": u, "date": TOMORROW, "amount": "1", "payer": "TPA"}).status_code == 422
    assert post(group, "/documents/investment", {"project_id": group.project, "date": TOMORROW, "amount": "1"}).status_code == 422


def test_a_payment_cannot_be_dated_before_its_bill(group):
    u = group.units["hospital"]
    claim = post(group, "/documents/claim", {"unit_id": u, "date": D, "amount": "1000", "payer": "TPA"}).json()
    assert post(group, f"/documents/{claim['id']}/settle", {"date": LAST_WEEK, "received": "1000"}).status_code == 422
    assert post(group, f"/documents/{claim['id']}/settle", {"date": TOMORROW, "received": "1000"}).status_code == 422
    bill = post(group, "/documents/expense", {"unit_id": u, "date": D, "amount": "500", "paid": False, "paid_to": "Vendor"}).json()
    assert post(group, f"/documents/{bill['id']}/pay", {"date": LAST_WEEK, "amount": "500", "payment_mode": "cash"}).status_code == 422
    assert post(group, f"/documents/{bill['id']}/pay", {"date": D, "amount": "500", "payment_mode": "cash"}).status_code == 201


def test_closing_a_month_in_one_project_leaves_other_projects_open(group):
    other = post(group, "/projects", {"name": "City Lab", "units": ["path_lab"]}).json()
    lab = next(u["id"] for u in other["units"] if u["kind"] == "path_lab")
    month = T.strftime("%Y-%m")
    assert post(group, f"/projects/{group.project}/periods/{month}/lock", {}).status_code == 200
    closed = post(group, "/documents/collection", {"unit_id": group.units["hospital"], "date": D, "amount": "1", "payment_mode": "cash"})
    assert closed.status_code == 409 and "closed" in closed.json()["detail"]
    still_open = post(group, "/documents/collection", {"unit_id": lab, "date": D, "amount": "1", "payment_mode": "cash"})
    assert still_open.status_code == 201
    get = lambda pid: group.client.get(f"/api/periods?project_id={pid}", headers=group.owner).json()
    assert get(group.project) == {"locked": [month]} and get(other["id"]) == {"locked": []}


def test_unit_staff_cannot_see_the_projects_loans(group):
    post(group, "/loans", {"project_id": group.project, "lender": "City Bank", "loan_type": "Term loan", "amount": "100000",
                           "start_date": D, "payment_mode": "bank", "rate": "12", "emi": "5000", "first_due": D})
    staff = group.add_user("9000000050", "unit_incharge", ["pharmacy"])
    seen = group.client.get(f"/api/loans?project_id={group.project}", headers=staff).json()
    assert seen["loans"] == [] and seen["overview"]["count"] == 0
    assert group.client.get(f"/api/loans?project_id={group.project}", headers=group.owner).json()["overview"]["count"] == 1


def test_phone_number_can_be_typed_with_spaces_or_country_code(group):
    for typed in ["90000 00001", "+91 9000000001", "09000000001", "+91-90000-00001"]:
        r = group.client.post("/api/auth/login", json={"phone": typed, "pin": "4321"})
        assert r.status_code == 200, typed
