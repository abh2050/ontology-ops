import csv
from datetime import date
from pathlib import Path

import pytest

from ops.data import sources as S
from ops.data.importer import FIXTURE_BATCH, ImportError_, validate_sources
from ops.data.manifest import build_manifest, manifest_hash


def rows(path: Path) -> list[list[str]]:
    with open(path, newline="") as fh:
        return list(csv.reader(fh))


def write(path: Path, data: list[list[str]]) -> None:
    with open(path, "w", newline="") as fh:
        csv.writer(fh, lineterminator="\n").writerows(data)


def mutate(directory: Path, name: str, fn) -> None:
    path = directory / S.SOURCES[name][0]
    data = rows(path)
    fn(data)
    write(path, data)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("10.125", 1013), ("99.995", 10000), ("0.005", 1), ("0.004", 0), ("129.90", 12990),
     ("1e2", 10000), ("0", 0)],
)
def test_money_half_up_integer_centavos(value, expected):
    result = S.parse_money_centavos(value, "price")
    assert result == expected and type(result) is int


@pytest.mark.parametrize(("value", "reason"), [("-0.01", "NEG_MONEY"), ("abc", "BAD_MONEY"),
                                               ("NaN", "BAD_MONEY"), ("", "BAD_MONEY"),
                                               ("Infinity", "BAD_MONEY")])
def test_money_rejections(value, reason):
    with pytest.raises(S.FieldError) as exc:
        S.parse_money_centavos(value, "price")
    assert exc.value.reason == reason


def test_fixture_batch_validates(fixture_dir):
    batch = validate_sources(fixture_dir, FIXTURE_BATCH)
    assert batch.provenance == "authored"
    assert batch.quarantine_counts() == {"BROKEN_FK": 1, "DUPLICATE_IDENTICAL": 1}
    assert batch.loaded_counts()["orders"] == 73


@pytest.mark.parametrize("name", list(S.SOURCES))
def test_header_mismatch_fails_import(fixture_dir, name):
    def rename(data):
        data[0][-1] = data[0][-1] + "_x"

    mutate(fixture_dir, name, rename)
    with pytest.raises(ImportError_, match="header mismatch"):
        validate_sources(fixture_dir, FIXTURE_BATCH)


def test_corrected_spelling_is_a_mismatch(fixture_dir):
    mutate(fixture_dir, "products",
           lambda d: d[0].__setitem__(2, "product_name_length"))
    with pytest.raises(ImportError_, match="header mismatch"):
        validate_sources(fixture_dir, FIXTURE_BATCH)


def test_only_five_files_are_read(fixture_dir):
    (fixture_dir / "olist_order_reviews_dataset.csv").write_text("not,read\n")
    (fixture_dir / "olist_order_payments_dataset.csv").write_text("not,read\n")
    batch = validate_sources(fixture_dir, FIXTURE_BATCH)
    assert {s["file"] for s in batch.file_stats.values()} == {f for f, _ in S.SOURCES.values()}


def test_missing_file_fails(fixture_dir):
    (fixture_dir / "olist_sellers_dataset.csv").unlink()
    with pytest.raises(ImportError_, match="missing source files"):
        validate_sources(fixture_dir, FIXTURE_BATCH)


def test_conflicting_duplicate_fails_whole_import(fixture_dir):
    def dup(data):
        copy = list(data[1])
        copy[-1] = "ZZ"  # same customer_id, different state
        data.append(copy)

    mutate(fixture_dir, "customers", dup)
    with pytest.raises(ImportError_, match="CONFLICTING_DUPLICATE"):
        validate_sources(fixture_dir, FIXTURE_BATCH)


def test_identical_duplicate_kept_once(fixture_dir):
    base = validate_sources(fixture_dir, FIXTURE_BATCH)
    mutate(fixture_dir, "sellers", lambda d: d.append(list(d[1])))
    batch = validate_sources(fixture_dir, FIXTURE_BATCH)
    assert batch.loaded_counts()["sellers"] == base.loaded_counts()["sellers"]
    assert batch.quarantine_counts()["DUPLICATE_IDENTICAL"] == 2


def _order_lines(directory: Path, order_id: str) -> int:
    return sum(1 for r in rows(directory / S.SOURCES["order_items"][0])[1:] if r[0] == order_id)


@pytest.mark.parametrize(
    ("column", "value", "reason"),
    [
        (4, "2000-01-01 00:00:00", "APPROVED_BEFORE_PURCHASE"),
        (5, "2000-01-01 00:00:00", "CARRIER_BEFORE_PURCHASE"),
        (6, "2000-01-01 00:00:00", "DELIVERED_BEFORE_PURCHASE"),
        (7, "", "MISSING_ESTIMATE"),
        (3, "not a time", "BAD_TIMESTAMP"),
        (0, "XYZ", "BAD_ID"),
    ],
)
def test_order_quarantine_and_cascade(fixture_dir, column, value, reason):
    order_rows = rows(fixture_dir / S.SOURCES["orders"][0])
    target = order_rows[1][0]
    lines = _order_lines(fixture_dir, target)
    assert lines >= 1

    def change(data):
        data[1][column] = value

    mutate(fixture_dir, "orders", change)
    batch = validate_sources(fixture_dir, FIXTURE_BATCH)
    counts = batch.quarantine_counts()
    assert counts[reason] == 1
    if reason == "BAD_ID":
        # the items still reference the original id, which is now quarantined under XYZ;
        # the original key was never accepted, so items fail the order foreign key
        assert counts["BROKEN_FK"] == 1 + lines
    else:
        assert counts["ORDER_QUARANTINED"] == lines
    assert target not in {r[1] for r in batch.rows["orders"]}
    assert target not in {r[1] for r in batch.rows["order_items"]}


def test_delivered_before_carrier(fixture_dir):
    def change(data):
        from datetime import datetime, timedelta

        row = next(r for r in data[1:] if r[5] and r[6])
        # delivered one second before the carrier handoff
        carrier = datetime.strptime(row[5], "%Y-%m-%d %H:%M:%S")
        row[6] = (carrier - timedelta(seconds=1)).strftime("%Y-%m-%d %H:%M:%S")

    mutate(fixture_dir, "orders", change)
    assert validate_sources(fixture_dir, FIXTURE_BATCH).quarantine_counts()[
        "DELIVERED_BEFORE_CARRIER"] == 1


@pytest.mark.parametrize(("value", "reason"), [("-5.00", "NEG_MONEY"), ("12,50", "BAD_MONEY")])
def test_item_money_quarantine(fixture_dir, value, reason):
    mutate(fixture_dir, "order_items", lambda d: d[1].__setitem__(5, value))
    assert validate_sources(fixture_dir, FIXTURE_BATCH).quarantine_counts()[reason] == 1


def test_quarantine_record_keeps_raw_row(fixture_dir):
    batch = validate_sources(fixture_dir, FIXTURE_BATCH)
    broken = next(q for q in batch.quarantine if q.reason_code == "BROKEN_FK")
    assert broken.source_file == "olist_order_items_dataset.csv"
    assert broken.source_row_number > 1
    assert set(broken.raw_row) == set(S.SOURCES["order_items"][1])


def test_manifest_is_deterministic(fixture_dir, tmp_path):
    a = build_manifest(validate_sources(fixture_dir), "v", date(2026, 10, 17))
    b = build_manifest(validate_sources(fixture_dir), "v", date(2026, 10, 17))
    assert manifest_hash(a) == manifest_hash(b)
    assert a["batch_id"].startswith("olist-full-v1-")
    assert a["files"]["orders"]["sha256"] and a["files"]["orders"]["rows"] == 73
    assert a["order_quarantine_cascade"]["order_items_order_quarantined"] == 0


def test_only_fixture_batch_may_be_named(fixture_dir):
    with pytest.raises(ImportError_, match="only 'fixtures-v1'"):
        validate_sources(fixture_dir, "olist-mine")
