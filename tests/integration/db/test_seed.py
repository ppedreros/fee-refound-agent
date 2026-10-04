"""The seed (SPEC-data, "Seed"): the brief's rows verbatim, idempotent, and a reset."""

import pytest
import sqlalchemy as sa
from sqlalchemy import Connection, Engine, text

from backend.db.seed import reset, seed

# The brief's tables, transcribed from the PDF. Cells the PDF wraps onto two lines are one string
# joined by a space. Timestamps are UTC.
BRIEF_ROWS = {
    "conversations": (
        "SELECT id::text, member_id::text, subject, status, "
        "to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') "
        "FROM conversations WHERE id BETWEEN 5008 AND 5012 ORDER BY id DESC",
        [
            ("5012", "301", "Overdraft fee", "waiting_for_bank", "2026-09-15 08:12:44"),
            ("5011", "288", "Card not working", "read_by_bank", "2026-09-14 17:03:10"),
            ("5010", "276", "Update my address", "waiting_for_member", "2026-09-14 11:40:02"),
            ("5009", "301", "Statement question", "closed", "2026-08-02 09:15:30"),
            ("5008", "254", "Fee on my savings", "waiting_for_bank", "2026-09-13 19:22:51"),
        ],
    ),
    "messages": (
        "SELECT id::text, conversation_id::text, author_id, body, "
        "to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS') "
        "FROM messages WHERE id BETWEEN 9116 AND 9120 ORDER BY id DESC",
        [
            (
                "9120",
                "5012",
                "301",
                "My paycheck came the same day. Can you refund this?",
                "2026-09-15 08:12:44",
            ),
            (
                "9119",
                "5011",
                "S14",
                "Thanks, we are checking your card now.",
                "2026-09-14 17:40:12",
            ),
            (
                "9118",
                "5011",
                "288",
                "My card gets declined at the gas station.",
                "2026-09-14 17:03:10",
            ),
            (
                "9117",
                "5010",
                "276",
                "I moved, how do I change my address?",
                "2026-09-14 11:40:02",
            ),
            (
                "9116",
                "5008",
                "254",
                "Why was I charged $5 on my savings?",
                "2026-09-13 19:22:51",
            ),
        ],
    ),
    "accounts": (
        "SELECT id::text, member_id::text, credit_union_id::text, account_number, "
        "is_primary::text FROM accounts WHERE id IN (710, 711, 702, 699, 655) "
        "ORDER BY id DESC",
        [
            ("711", "301", "7", "884211", "false"),
            ("710", "301", "7", "884210", "true"),
            ("702", "288", "7", "883977", "true"),
            ("699", "276", "7", "883540", "true"),
            ("655", "254", "9", "510332", "true"),
        ],
    ),
    "sub_accounts": (
        "SELECT id::text, account_id::text, type, name, balance::text, available::text "
        "FROM sub_accounts WHERE id IN (1301, 1302, 1303, 1290, 1255) ORDER BY id DESC",
        [
            ("1303", "711", "SAVINGS", "Vacation Savings", "48.00", "48.00"),
            ("1302", "710", "CHECKING", "Everyday Checking", "1325.00", "1325.00"),
            ("1301", "710", "SAVINGS", "Primary Savings", "215.40", "210.40"),
            ("1290", "702", "CHECKING", "Everyday Checking", "92.17", "92.17"),
            ("1255", "655", "SAVINGS", "Primary Savings", "1040.00", "1040.00"),
        ],
    ),
    "transactions": (
        "SELECT id::text, sub_account_id::text, date::text, description, amount::text, "
        "balance_after::text, posting_ref FROM transactions "
        "WHERE id IN (88001, 88002, 88003, 87410, 87390) ORDER BY id DESC",
        [
            (
                "88003",
                "1302",
                "2026-09-14",
                "Deposit ACH ACME LOGISTICS*PAYROLL",
                "1400.00",
                "1325.00",
                "20260914-0010",
            ),
            (
                "88002",
                "1302",
                "2026-09-14",
                "Fee Withdrawal ; Courtesy Pay fee",
                "-35.00",
                "-75.00",
                "20260914-0005",
            ),
            (
                "88001",
                "1302",
                "2026-09-14",
                "Withdrawal Debit Card CITY POWER & LIGHT",
                "-60.00",
                "-40.00",
                "20260914-0000",
            ),
            (
                "87410",
                "1302",
                "2026-03-03",
                "Deposit Fee Refund Courtesy Pay Fee",
                "35.00",
                "412.10",
                "20260303-0002",
            ),
            (
                "87390",
                "1301",
                "2026-01-20",
                "Deposit Fee Refund Out of Network Fee",
                "5.00",
                "880.45",
                "20260120-0002",
            ),
        ],
    ),
}

COUNTED_TABLES = [
    "conversations",
    "messages",
    "accounts",
    "sub_accounts",
    "transactions",
    "member_profiles",
    "staff",
]


def row_counts(connection: Connection) -> dict[str, int]:
    return {
        table: connection.execute(
            sa.select(sa.func.count()).select_from(sa.table(table))
        ).scalar_one()
        for table in COUNTED_TABLES
    }


@pytest.mark.parametrize("table", BRIEF_ROWS)
def test_the_brief_rows_are_loaded_verbatim(seeded: Engine, table: str) -> None:
    query, expected = BRIEF_ROWS[table]

    with seeded.connect() as connection:
        rows = [tuple(row) for row in connection.execute(text(query))]

    assert rows == expected


def test_seeding_twice_leaves_the_same_counts(seeded: Engine) -> None:
    with seeded.connect() as connection:
        before = row_counts(connection)
    with seeded.begin() as connection:
        seed(connection)
    with seeded.connect() as connection:
        after = row_counts(connection)

    assert after == before


def test_every_member_in_the_data_has_a_name(seeded: Engine) -> None:
    with seeded.connect() as connection:
        nameless = connection.execute(
            text(
                "SELECT member_id FROM conversations UNION SELECT member_id FROM accounts "
                "EXCEPT SELECT member_id FROM member_profiles"
            )
        ).scalars()

        assert list(nameless) == []


def test_anas_profile_and_the_staff_are_seeded(seeded: Engine) -> None:
    with seeded.connect() as connection:
        ana = connection.execute(
            text("SELECT first_name, last_name FROM member_profiles WHERE member_id = 301")
        ).one()
        staff = {
            row.id: row.display_name
            for row in connection.execute(text("SELECT id, display_name FROM staff"))
        }

    assert tuple(ana) == ("Ana", "Torres")
    assert staff == {"S07": "Luis", "S14": "Sam", "SYSTEM": "Automatic approval"}


def test_seeding_again_never_overwrites_what_changed_after_it(seeded: Engine) -> None:
    with seeded.begin() as connection:
        connection.execute(text("UPDATE sub_accounts SET balance = 1360.00 WHERE id = 1302"))
        connection.execute(text("UPDATE conversations SET status = 'closed' WHERE id = 5012"))

    with seeded.begin() as connection:
        seed(connection)

    with seeded.connect() as connection:
        balance = connection.execute(
            text("SELECT balance::text FROM sub_accounts WHERE id = 1302")
        ).scalar_one()
        status = connection.execute(
            text("SELECT status FROM conversations WHERE id = 5012")
        ).scalar_one()
    assert (balance, status) == ("1360.00", "closed")


def test_reset_restores_the_demo_state(seeded: Engine) -> None:
    with seeded.connect() as connection:
        pristine = {table: rows_of(connection, table) for table in COUNTED_TABLES}
    with seeded.begin() as connection:
        connection.execute(text("UPDATE sub_accounts SET balance = 1360.00 WHERE id = 1302"))
        connection.execute(
            text(
                "INSERT INTO messages (conversation_id, author_id, body, created_at) "
                "VALUES (5012, 'S07', 'Refunded!', now())"
            )
        )
        connection.execute(text("INSERT INTO audit_events (actor, action) VALUES ('S07', 'x')"))

    with seeded.begin() as connection:
        reset(connection)
        seed(connection)

    with seeded.connect() as connection:
        restored = {table: rows_of(connection, table) for table in COUNTED_TABLES}
        audit_rows = connection.execute(text("SELECT count(*) FROM audit_events")).scalar_one()
    assert restored == pristine
    assert audit_rows == 0


def test_after_a_reset_app_generated_ids_start_again_above_the_seed(seeded: Engine) -> None:
    insert_reply = (
        "INSERT INTO messages (conversation_id, author_id, body, created_at) "
        "VALUES (5012, 'S07', 'Hi', now()) RETURNING id"
    )
    with seeded.begin() as connection:
        connection.execute(text(insert_reply))
    with seeded.begin() as connection:
        reset(connection)
        seed(connection)

    with seeded.begin() as connection:
        new_id = connection.execute(text(insert_reply)).scalar_one()

    assert new_id == 1_000_000


def rows_of(connection: Connection, table: str) -> list[tuple[object, ...]]:
    every_column = sa.select(sa.text("*")).select_from(sa.table(table)).order_by(sa.text("1"))
    return [tuple(row) for row in connection.execute(every_column)]
