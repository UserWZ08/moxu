"""Independent SQLite customer table; Excel is an import/export view, not the live DB."""

import re
import uuid
from datetime import datetime

FIELDS = [
    "name",
    "community",
    "building",
    "room",
    "phone",
    "qq",
    "wechat",
    "contact",
    "alias",
    "note",
]
HEADERS = [
    "客户编号",
    "姓名",
    "小区",
    "楼栋",
    "房号",
    "手机号",
    "QQ号",
    "微信号",
    "其他联系方式",
    "搜索别名",
    "备注",
]
KEYS = ["id"] + FIELDS


def clean(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def search_key(record):
    from pypinyin import Style, lazy_pinyin

    text = " ".join(clean(record.get(k, "")) for k in FIELDS)
    full = "".join(lazy_pinyin(text, style=Style.NORMAL, errors="default"))
    initial = "".join(lazy_pinyin(text, style=Style.FIRST_LETTER, errors="default"))
    return re.sub(r"[\s\-]+", "", (text + " " + full + " " + initial).casefold())


def init_table(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS customers (id TEXT PRIMARY KEY, name TEXT NOT NULL,community TEXT,building TEXT,room TEXT,phone TEXT,qq TEXT,wechat TEXT,contact TEXT,alias TEXT,note TEXT,search_key TEXT NOT NULL,updated TEXT NOT NULL)"
    )
    db.execute("CREATE INDEX IF NOT EXISTS customers_name ON customers(name)")
    db.commit()


def upsert(db, record, commit=True):
    r = {key: clean(record.get(key, "")) for key in KEYS}
    if not r["name"]:
        raise ValueError("客户姓名不能为空")
    if any(len(v) > 3000 for v in r.values()):
        raise ValueError("客户字段过长")
    if not r["id"]:
        old = db.execute(
            "SELECT id FROM customers WHERE name=? AND community=? AND building=? AND room=? AND phone=?",
            (r["name"], r["community"], r["building"], r["room"], r["phone"]),
        ).fetchone()
        r["id"] = old[0] if old else uuid.uuid4().hex
    values = [r[k] for k in KEYS] + [
        search_key(r),
        datetime.now().isoformat(timespec="seconds"),
    ]
    db.execute(
        "INSERT INTO customers ("
        + ",".join(KEYS)
        + ",search_key,updated) VALUES ("
        + ",".join("?" for _ in values)
        + ") ON CONFLICT(id) DO UPDATE SET "
        + ",".join(k + "=excluded." + k for k in FIELDS + ["search_key", "updated"]),
        values,
    )
    if commit:
        db.commit()
    return r


def search(db, text="", limit=500):
    query = re.sub(r"[\s\-]+", "", text.casefold())
    pattern = "%" + query.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%"
    rows = db.execute(
        "SELECT "
        + ",".join(KEYS)
        + " FROM customers WHERE search_key LIKE ? ESCAPE '!' ORDER BY updated DESC LIMIT ?",
        (pattern, limit),
    ).fetchall()
    return [dict(zip(KEYS, row)) for row in rows]


def get(db, identifier):
    row = db.execute(
        "SELECT " + ",".join(KEYS) + " FROM customers WHERE id=?", (identifier,)
    ).fetchone()
    return dict(zip(KEYS, row)) if row else None


def export_xlsx(db, path):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "客户档案"
    ws.append(HEADERS)
    rows = db.execute(
        "SELECT " + ",".join(KEYS) + " FROM customers ORDER BY name"
    ).fetchall()
    for row in rows:
        ws.append([clean(v) for v in row])
        for cell in ws[ws.max_row]:
            cell.data_type = "s"
            cell.number_format = "@"
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="E97824")
        c.alignment = Alignment(vertical="center")
    ws.row_dimensions[1].height = 26
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for i, width in enumerate([35, 18, 22, 16, 14, 20, 20, 23, 25, 22, 35], 1):
        ws.column_dimensions[chr(64 + i)].width = width
    wb.save(path)
    wb.close()
    return len(rows)


def import_xlsx(db, path):
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=False)
    try:
        ws = wb.active
        rows = ws.iter_rows(values_only=False)
        header = [clean(c.value) for c in next(rows)]
        mapping = {name: header.index(name) for name in HEADERS if name in header}
        if "姓名" not in mapping and "客户编号" not in mapping:
            raise ValueError(
                "Excel 第一行至少需要“姓名”或“客户编号”列；建议先导出模板再填写"
            )
        records = []
        for row_number, cells in enumerate(rows, 2):
            row = [c.value for c in cells]
            if row_number > 100002:
                raise ValueError("一次最多导入十万行")
            if not any(v is not None and clean(v) for v in row):
                continue
            if any(c.data_type == "f" for c in cells):
                raise ValueError(f"第{row_number}行含公式，请转换为文本后导入")
            # Missing columns and empty cells are patches, never instructions to erase.
            record = {
                key: clean(row[mapping[header]])
                for key, header in zip(KEYS, HEADERS)
                if header in mapping
                and mapping[header] < len(row)
                and clean(row[mapping[header]])
            }
            identifier = record.get("id", "")
            existing = get(db, identifier) if identifier else None
            if existing:
                if record.get("name") and record["name"] != existing["name"]:
                    raise ValueError(
                        f"第{row_number}行编号与原客户姓名不符，未更新任何记录"
                    )
                record = dict(existing, **record)
            elif identifier:
                # Exports from another store keep the identifier only for new records.
                if not record.get("name"):
                    raise ValueError(f"第{row_number}行的新客户缺少姓名")
            if not record.get("name"):
                raise ValueError(f"第{row_number}行缺少姓名")
            records.append(record)
        with db:
            for record in records:
                upsert(db, record, commit=False)
        return len(records)
    finally:
        wb.close()
