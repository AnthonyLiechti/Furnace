#!/usr/bin/env python3
"""
Snapshot CSV import script for Furnace Supabase.
Imports budget data from Google Sheets CSV exports.
"""

import csv
import json
import re
import sys
import urllib.request
import urllib.error
import urllib.parse
from io import StringIO

# === CONFIG ===
SUPABASE_URL = "https://jnwdscddyqujjikesdpb.supabase.co"
ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Impud2RzY2RkeXF1amppa2VzZHBiIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzQyODgxOTEsImV4cCI6MjA4OTg2NDE5MX0.EQueTlfX30ULmpLDF7ijSv0xR0_baAT2kPjYoK_RnpA"
EMAIL = "anthony@createdbyforge.com"
PASSWORD = "tJeEnwT5Ueuokl2X"

DOWNLOADS = "/Users/anthonyliechti/Downloads"

# OOP section slug mapping
OOP_FILE_TO_SLUG = {
    "Creative Depo's": "creative",
    "Camera Depo's": "camera",
    "Talent": "talent",
    "Travel_Meals": "travel-meals",
}

# Phase column mapping for labor
PHASE_MAP = {
    "P1": "phase1",
    "P2": "phase2",
    "P3.1": "phase3_1",
    "P3.2": "phase3_2",
    "P4": "phase4",
    "P5": "phase5",
}

# === HTTP HELPERS ===

TOKEN = None

def authenticate():
    global TOKEN
    url = f"{SUPABASE_URL}/auth/v1/token?grant_type=password"
    data = json.dumps({"email": EMAIL, "password": PASSWORD}).encode()
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/json",
        "apikey": ANON_KEY,
    })
    resp = urllib.request.urlopen(req)
    TOKEN = json.loads(resp.read())["access_token"]
    print("Authenticated successfully")


def api_request(method, path, data=None, params=None):
    """Make an authenticated request to Supabase REST API."""
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)

    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "apikey": ANON_KEY,
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }

    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        resp = urllib.request.urlopen(req)
        text = resp.read().decode()
        return json.loads(text) if text.strip() else []
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        print(f"  API ERROR {e.code}: {error_body}")
        raise


def api_get(path, params=None):
    return api_request("GET", path, params=params)


def api_post(path, data):
    return api_request("POST", path, data=data)


def api_patch(path, data, params=None):
    return api_request("PATCH", path, data=data, params=params)


def api_delete(path, params=None):
    return api_request("DELETE", path, params=params)


# === DATA LOADERS ===

def load_reference_data():
    """Load team_members, oop_sections, oop_categories from Supabase."""
    team_members = api_get("team_members", {"select": "*"})
    oop_sections = api_get("oop_sections", {"select": "*"})
    oop_categories = api_get("oop_categories", {"select": "*,section_id"})

    # Build lookup dicts
    tm_by_name = {}
    for tm in team_members:
        name = tm["name"].strip()
        tm_by_name[name.lower()] = tm

    sec_by_slug = {s["slug"]: s for s in oop_sections}

    cat_by_section_name = {}
    for cat in oop_categories:
        key = (cat["section_id"], cat["name"].lower().strip())
        cat_by_section_name[key] = cat

    return tm_by_name, sec_by_slug, cat_by_section_name


def find_team_member(tm_by_name, name):
    """Find team member by name with fuzzy matching."""
    name = name.strip()
    if not name:
        return None

    # Direct match
    key = name.lower()
    if key in tm_by_name:
        return tm_by_name[key]

    # Try without trailing spaces/special chars
    cleaned = re.sub(r'\s+', ' ', name).strip().lower()
    if cleaned in tm_by_name:
        return tm_by_name[cleaned]

    # Try last name match
    for tm_key, tm in tm_by_name.items():
        if name.lower().split()[-1] == tm_key.split()[-1]:
            # Check first name initial too
            if name.lower()[0] == tm_key[0]:
                return tm

    return None


# === CSV PARSERS ===

def parse_dollar(val):
    """Parse a dollar string like '$13,300' or '-$1,200' to float."""
    if not val:
        return 0.0
    val = val.strip().replace("$", "").replace(",", "").replace('"', '')
    if not val or val == "-":
        return 0.0
    try:
        return float(val)
    except ValueError:
        return 0.0


def parse_num(val):
    """Parse a numeric string to float, return 0 if empty."""
    if not val:
        return 0.0
    val = val.strip().replace(",", "").replace('"', '')
    if not val or val == "-":
        return 0.0
    try:
        return float(val)
    except ValueError:
        return 0.0


def parse_int_val(val):
    """Parse an integer string, return None if empty."""
    if not val:
        return None
    val = val.strip().replace(",", "").replace('"', '')
    if not val or val == "-":
        return None
    try:
        return int(float(val))
    except ValueError:
        return None


def parse_snapshot_csv(filepath):
    """Parse Snapshot tab CSV to extract key budget fields."""
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        rows = list(csv.reader(f))

    result = {
        "client_price": 0,
        "budget_amount": 0,
        "discount_pct": 0,
        "has_discount": False,
        "oop_estimated": 0,
        "labor_estimated": 0,
        "total_price": 0,
        "oop_markup_pct": 20,
        "reserve_pct": 10,
        "project_code": "",
        "project_name": "",
        "client_name": "",
    }

    for i, row in enumerate(rows):
        text = ",".join(row)

        # Budget amount
        if "Budget" in text and not "After" in text and not "OOP" in text:
            for j, cell in enumerate(row):
                if "Budget" in cell:
                    # Look for dollar value in subsequent cells
                    for k in range(j+1, min(j+6, len(row))):
                        val = parse_dollar(row[k])
                        if val > 0:
                            result["budget_amount"] = val
                            break
                    break

        # Discount
        if "Discount" in text and "0.9" in text:
            for j, cell in enumerate(row):
                if cell.strip().startswith("0.9"):
                    result["discount_pct"] = round((1 - float(cell.strip())) * 100, 2)
                    result["has_discount"] = True
                    break

        # Client price (Budget After Discount and CO)
        if "Budget After Discount" in text:
            for j, cell in enumerate(row):
                if "Budget After" in cell:
                    for k in range(j+1, min(j+6, len(row))):
                        val = parse_dollar(row[k])
                        if val > 0:
                            result["client_price"] = val
                            break
                    break

        # If no discount, client_price = budget
        if "Estimated Total Price" in text:
            for j, cell in enumerate(row):
                if "Estimated Total Price" in cell:
                    for k in range(j+1, min(j+6, len(row))):
                        val = parse_dollar(row[k])
                        if val > 0:
                            result["total_price"] = val
                            break
                    break

        # OOP estimated
        if "OOP (W/Contingency)" in text or "OOP (W/" in text:
            for j, cell in enumerate(row):
                if "OOP" in cell and "W/" in cell:
                    for k in range(j+1, min(j+4, len(row))):
                        val = parse_dollar(row[k])
                        if val > 0:
                            result["oop_estimated"] = val
                            break
                    break

        # FMG Labor estimated
        if "FMG Labor (W/MU)" in text or "FMG Labor (W/" in text:
            for j, cell in enumerate(row):
                if "FMG Labor" in cell and "W/" in cell:
                    for k in range(j+1, min(j+4, len(row))):
                        val = parse_dollar(row[k])
                        if val > 0:
                            result["labor_estimated"] = val
                            break
                    break

        # Project code and name
        if "320_" in text or "322_" in text or "321_" in text:
            for j, cell in enumerate(row):
                cell_stripped = cell.strip()
                m = re.match(r'(\d{3}_\d{2}_\d{2}(?:_[A-Z]\d+)?)\s*[-–]\s*(.+)', cell_stripped)
                if m:
                    result["project_code"] = m.group(1).strip()
                    result["project_name"] = m.group(2).strip()
                    break

        # Client
        if "320 - " in text or "322 - " in text:
            for j, cell in enumerate(row):
                m2 = re.match(r'(\d{3})\s*[-–]\s*(.+)', cell.strip())
                if m2:
                    result["client_name"] = m2.group(2).strip()
                    break

        # OOP Markup
        if "OOP" in text and ("20%" in text or "MU" in text):
            for j, cell in enumerate(row):
                if "%" in cell and cell.strip().endswith("%"):
                    try:
                        pct = float(cell.strip().replace("%", ""))
                        if 5 <= pct <= 50:
                            result["oop_markup_pct"] = pct
                    except ValueError:
                        pass

        # OPR / Labor MU percentage
        if "OPR" in text or "Labor MU" in text:
            for j, cell in enumerate(row):
                if cell.strip().endswith("%"):
                    try:
                        pct = float(cell.strip().replace("%", ""))
                        if pct > 50:
                            # It's the markup multiplier as percentage e.g. 108%
                            pass
                    except ValueError:
                        pass

    # If no "Budget After Discount" was found, use budget_amount as client_price
    if result["client_price"] == 0 and result["budget_amount"] > 0:
        result["client_price"] = result["budget_amount"]

    return result


def parse_labor_csv(filepath):
    """Parse FMG Labor CSV to extract person-phase hours."""
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        rows = list(csv.reader(f))

    entries = []  # list of {name, department, phase, estimated_hours}
    current_phase = None
    current_dept = None

    for row in rows:
        # Skip empty rows
        text = ",".join(row).strip(",").strip()
        if not text:
            continue

        # Detect phase
        for cell in row:
            cell_s = cell.strip()
            if cell_s.startswith("Phase "):
                m = re.match(r'Phase\s+(\d+(?:\.\d+)?)', cell_s)
                if m:
                    phase_num = m.group(1)
                    # Map "1" -> "P1", "3.1" -> "P3.1" etc.
                    # But actually the CSV already has P1, P2 etc. in col 1
                    break

        # Detect department headers
        for cell in row:
            cell_s = cell.strip()
            if cell_s in ("Executive/Admin", "Account", "Creative", "Post"):
                current_dept = cell_s if cell_s != "Creative" else "Creative"
                # Handle "Creative " with trailing space
                if cell_s.startswith("Creative"):
                    current_dept = "Creative"
                break

        # Detect person rows: phase code in col 1, name in col 2, hours in col 4
        if len(row) >= 5:
            phase_code = row[1].strip()
            if phase_code in PHASE_MAP:
                current_phase = phase_code
                name = row[2].strip().rstrip()
                if name and name != "Other" and name != "Sub Total":
                    est_hours = parse_num(row[4])
                    if est_hours > 0:
                        entries.append({
                            "name": name,
                            "department": current_dept,
                            "phase": PHASE_MAP[phase_code],
                            "estimated_hours": est_hours,
                        })

    return entries


def parse_oop_csv(filepath, section_slug):
    """Parse an OOP tab CSV to extract line items."""
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        rows = list(csv.reader(f))

    entries = []
    current_category = None
    in_data_section = False

    # The CSV structure varies by section:
    # Creative/Camera: Count, Rate, Total (Estimated) | Count, Rate, Total (Active) | Delta | Paid | Total (Actual) | Notes
    # Talent: Count, Rate, Days, Total (Estimated) | Count, Rate, Days, Total (Active) | Delta | Paid | Total (Actual) | Notes
    # Travel/Meals: Count, Rate, Days, Head, Total (Estimated) | Count, Rate, Days, Head, Total (Active) | Delta | Paid | Total (Actual) | Notes

    has_days = section_slug in ("talent",)
    has_head = section_slug in ("travel-meals",)

    for i, row in enumerate(rows):
        text = ",".join(row)

        # Skip header area - look for "Estimated" header row
        if "Estimated" in text and "Active" in text and "Actual" in text:
            in_data_section = True
            continue

        if not in_data_section:
            continue

        # Detect category headers - they have "Count" and "Rate" in them
        if "Count" in text and "Rate" in text and "Total" in text:
            # The category name is in column 1
            cat_name = row[1].strip() if len(row) > 1 else ""
            if cat_name and cat_name != "Count":
                current_category = cat_name
            continue

        # Detect "Sub Total" rows - skip them
        if "Sub Total" in text:
            continue

        # Detect total footer
        if len(row) > 2 and row[2] and row[2].strip() == "Total":
            continue
        if len(row) > 1 and row[1] and row[1].strip() == "Total":
            continue

        # Parse data rows
        if current_category and len(row) >= 8:
            line_name = row[1].strip() if len(row) > 1 else ""
            if not line_name:
                continue
            if line_name in ("Sub Total", "Total", "Count", "Rate"):
                continue

            if has_head:
                # Travel/Meals: col1=name, col2=count, col3=rate, col4=days, col5=head, col6=total,
                # col7=spacer, col8=a_count, col9=a_rate, col10=a_days, col11=a_head, col12=a_total,
                # col13=spacer, col14=delta, col15=spacer, col16=paid, col17=spacer, col18=actual_total
                est_count = parse_int_val(row[2]) if len(row) > 2 else None
                est_rate = parse_num(row[3]) if len(row) > 3 else 0
                est_days = parse_int_val(row[4]) if len(row) > 4 else None
                est_head = parse_int_val(row[5]) if len(row) > 5 else None
                est_total = parse_dollar(row[6]) if len(row) > 6 else 0

                adj_count = parse_int_val(row[8]) if len(row) > 8 else None
                adj_rate = parse_num(row[9]) if len(row) > 9 else 0
                adj_days = parse_int_val(row[10]) if len(row) > 10 else None
                adj_head = parse_int_val(row[11]) if len(row) > 11 else None
                adj_total = parse_dollar(row[12]) if len(row) > 12 else 0

                paid_str = row[16].strip() if len(row) > 16 else ""
                actual_total = parse_dollar(row[18]) if len(row) > 18 else 0

            elif has_days:
                # Talent: col1=name, col2=count, col3=rate, col4=days, col5=total,
                # col6=spacer, col7=a_count, col8=a_rate, col9=a_days, col10=a_total,
                # col11=spacer, col12=delta, col13=spacer, col14=paid, col15=spacer, col16=actual_total
                est_count = parse_int_val(row[2]) if len(row) > 2 else None
                est_rate = parse_num(row[3]) if len(row) > 3 else 0
                est_days = parse_int_val(row[4]) if len(row) > 4 else None
                est_head = None
                est_total = parse_dollar(row[5]) if len(row) > 5 else 0

                adj_count = parse_int_val(row[7]) if len(row) > 7 else None
                adj_rate = parse_num(row[8]) if len(row) > 8 else 0
                adj_days = parse_int_val(row[9]) if len(row) > 9 else None
                adj_head = None
                adj_total = parse_dollar(row[10]) if len(row) > 10 else 0

                paid_str = row[14].strip() if len(row) > 14 else ""
                actual_total = parse_dollar(row[16]) if len(row) > 16 else 0

            else:
                # Creative/Camera: col1=name, col2=count, col3=rate, col4=total,
                # col5=spacer, col6=a_count, col7=a_rate, col8=a_total,
                # col9=spacer, col10=delta, col11=spacer, col12=paid, col13=spacer, col14=actual_total
                est_count = parse_int_val(row[2]) if len(row) > 2 else None
                est_rate = parse_num(row[3]) if len(row) > 3 else 0
                est_days = None
                est_head = None
                est_total = parse_dollar(row[4]) if len(row) > 4 else 0

                adj_count = parse_int_val(row[6]) if len(row) > 6 else None
                adj_rate = parse_num(row[7]) if len(row) > 7 else 0
                adj_days = None
                adj_head = None
                adj_total = parse_dollar(row[8]) if len(row) > 8 else 0

                paid_str = row[12].strip() if len(row) > 12 else ""
                actual_total = parse_dollar(row[14]) if len(row) > 14 else 0

            # Skip if all zeros/empty
            if est_rate == 0 and est_total == 0 and adj_rate == 0 and adj_total == 0 and actual_total == 0:
                # Still include if there's a line name with a rate placeholder
                if est_rate == 0 and (adj_rate == 0 or adj_rate is None):
                    continue

            notes_col = row[-1].strip() if len(row) > 0 else ""

            entry = {
                "category": current_category,
                "line_item_name": line_name,
                "count": est_count if est_count and est_count > 0 else (1 if est_total > 0 else 0),
                "rate": est_rate,
                "days": est_days if est_days and est_days > 0 else 1,
                "head_count": est_head if est_head and est_head > 0 else 1,
                "adjusted_count": adj_count,
                "adjusted_rate": adj_rate if adj_rate else None,
                "adjusted_days": adj_days,
                "adjusted_head_count": adj_head,
                "actual_amount": actual_total if actual_total > 0 else None,
                "is_active": paid_str.upper() != "TRUE",
                "notes": notes_col if notes_col and notes_col not in ("Notes", "FALSE", "TRUE", "") else None,
            }

            entries.append(entry)

    return entries


# === IMPORT LOGIC ===

def find_or_create_project(project_code, project_name):
    """Find project by code, or return None if not found."""
    results = api_get("projects", {
        "select": "*",
        "project_code": f"eq.{project_code}",
    })
    if results:
        return results[0]

    print(f"  WARNING: Project {project_code} not found in database")
    return None


def find_existing_budget(project_id):
    """Check if a budget already exists for this project."""
    results = api_get("budgets", {
        "select": "*",
        "project_id": f"eq.{project_id}",
    })
    return results[0] if results else None


def delete_budget_children(budget_id):
    """Delete existing labor and OOP entries for a budget."""
    api_delete("labor_budget_entries", {"budget_id": f"eq.{budget_id}"})
    api_delete("oop_budget_entries", {"budget_id": f"eq.{budget_id}"})
    print(f"  Cleared existing labor and OOP entries for budget {budget_id[:8]}...")


def create_or_update_budget(project_id, snapshot_data, status="active"):
    """Create or update a budget for a project."""
    existing = find_existing_budget(project_id)

    budget_data = {
        "project_id": project_id,
        "name": "Snapshot",
        "status": status,
        "client_price": snapshot_data.get("client_price", 0) or snapshot_data.get("budget_amount", 0),
        "total_amount": snapshot_data.get("total_price", 0),
        "has_discount": snapshot_data.get("has_discount", False),
        "discount_percentage": snapshot_data.get("discount_pct", 0),
        "oop_markup_percentage": snapshot_data.get("oop_markup_pct", 20),
    }

    if existing:
        print(f"  Updating existing budget {existing['id'][:8]}...")
        delete_budget_children(existing["id"])
        result = api_patch("budgets", budget_data, {
            "id": f"eq.{existing['id']}",
        })
        return existing["id"] if not result else result[0]["id"]
    else:
        print(f"  Creating new budget...")
        result = api_post("budgets", budget_data)
        return result[0]["id"]


def import_labor(budget_id, labor_entries, tm_by_name):
    """Import labor budget entries."""
    if not labor_entries:
        print("  No labor entries to import")
        return

    # Group by person to consolidate phases
    person_phases = {}
    for entry in labor_entries:
        name = entry["name"]
        if name not in person_phases:
            person_phases[name] = {
                "department": entry["department"],
                "phase1": 0, "phase2": 0, "phase3_1": 0,
                "phase3_2": 0, "phase4": 0, "phase5": 0,
            }
        person_phases[name][entry["phase"]] += entry["estimated_hours"]

    imported = 0
    skipped = []
    for name, phases in person_phases.items():
        tm = find_team_member(tm_by_name, name)
        if not tm:
            skipped.append(name)
            continue

        total_hours = sum(phases[p] for p in PHASE_MAP.values())
        if total_hours == 0:
            continue

        entry_data = {
            "budget_id": budget_id,
            "team_member_id": tm["id"],
            "department": phases["department"] or tm.get("department"),
            "phase1": phases["phase1"],
            "phase2": phases["phase2"],
            "phase3_1": phases["phase3_1"],
            "phase3_2": phases["phase3_2"],
            "phase4": phases["phase4"],
            "phase5": phases["phase5"],
            "display_order": imported,
        }

        api_post("labor_budget_entries", entry_data)
        imported += 1

    print(f"  Imported {imported} labor entries")
    if skipped:
        print(f"  Skipped (no team member match): {skipped}")


def import_oop(budget_id, oop_entries, section_slug, sec_by_slug, cat_by_section_name):
    """Import OOP budget entries for a section."""
    if not oop_entries:
        print(f"  No OOP entries for {section_slug}")
        return

    section = sec_by_slug.get(section_slug)
    if not section:
        print(f"  WARNING: OOP section '{section_slug}' not found")
        return

    section_id = section["id"]
    imported = 0

    for idx, entry in enumerate(oop_entries):
        # Find category
        cat_key = (section_id, entry["category"].lower().strip())
        category = cat_by_section_name.get(cat_key)

        if not category:
            # Try partial match
            for (sid, cname), cat in cat_by_section_name.items():
                if sid == section_id and (cname in entry["category"].lower() or entry["category"].lower() in cname):
                    category = cat
                    break

        category_id = category["id"] if category else None

        entry_data = {
            "budget_id": budget_id,
            "section_id": section_id,
            "category_id": category_id,
            "line_item_name": entry["line_item_name"],
            "count": entry.get("count", 0) or 0,
            "rate": entry.get("rate", 0) or 0,
            "days": entry.get("days", 1) or 1,
            "head_count": entry.get("head_count", 1) or 1,
            "adjusted_count": entry.get("adjusted_count"),
            "adjusted_rate": entry.get("adjusted_rate"),
            "adjusted_days": entry.get("adjusted_days"),
            "adjusted_head_count": entry.get("adjusted_head_count"),
            "actual_amount": entry.get("actual_amount"),
            "is_active": entry.get("is_active", True),
            "notes": entry.get("notes"),
            "display_order": idx,
        }

        api_post("oop_budget_entries", entry_data)
        imported += 1

    print(f"  Imported {imported} OOP entries for {section_slug}")


# === PROJECT IMPORTS ===

def import_project(project_code, project_name, csv_files, status="active"):
    """Import a single project's snapshot data."""
    print(f"\n{'='*60}")
    print(f"IMPORTING: {project_code} - {project_name}")
    print(f"{'='*60}")

    # Find project
    project = find_or_create_project(project_code, project_name)
    if not project:
        print(f"  SKIPPING - project not found in DB")
        return False

    project_id = project["id"]
    print(f"  Found project: {project['name']} ({project_id[:8]}...)")

    # Parse snapshot CSV if available
    snapshot_file = csv_files.get("snapshot")
    snapshot_data = {}
    if snapshot_file:
        print(f"  Parsing Snapshot CSV...")
        snapshot_data = parse_snapshot_csv(snapshot_file)
        print(f"    Budget: ${snapshot_data.get('budget_amount', 0):,.0f}")
        print(f"    Client Price: ${snapshot_data.get('client_price', 0):,.0f}")
        print(f"    Total Price: ${snapshot_data.get('total_price', 0):,.0f}")
        print(f"    Discount: {snapshot_data.get('discount_pct', 0)}%")
    else:
        print(f"  No Snapshot CSV - will create budget with defaults")

    # Create/update budget
    budget_id = create_or_update_budget(project_id, snapshot_data, status=status)
    print(f"  Budget ID: {budget_id[:8]}...")

    # Import FMG Labor
    labor_file = csv_files.get("labor")
    if labor_file:
        print(f"  Parsing FMG Labor CSV...")
        labor_entries = parse_labor_csv(labor_file)
        print(f"    Found {len(labor_entries)} person-phase entries")
        import_labor(budget_id, labor_entries, tm_by_name)
    else:
        print(f"  No FMG Labor CSV - skipping labor import")

    # Import OOP sections
    for oop_key, slug in OOP_FILE_TO_SLUG.items():
        oop_file = csv_files.get(f"oop_{slug}")
        if oop_file:
            print(f"  Parsing OOP {oop_key} CSV...")
            oop_entries = parse_oop_csv(oop_file, slug)
            print(f"    Found {len(oop_entries)} line items")
            import_oop(budget_id, oop_entries, slug, sec_by_slug, cat_by_section_name)
        else:
            print(f"  No OOP {oop_key} CSV - skipping")

    print(f"  DONE: {project_code}")
    return True


# === MAIN ===

if __name__ == "__main__":
    authenticate()

    # Load reference data
    print("\nLoading reference data...")
    tm_by_name, sec_by_slug, cat_by_section_name = load_reference_data()
    print(f"  {len(tm_by_name)} team members")
    print(f"  {len(sec_by_slug)} OOP sections")
    print(f"  {len(cat_by_section_name)} OOP categories")

    # Define projects to import
    projects = [
        {
            "code": "320_32_00",
            "name": "Mobile App Onboarding",
            "status": "active",
            "files": {
                "snapshot": f"{DOWNLOADS}/320_32_00 - Mobile App Onboarding - Snapshot v01.18 - Snapshot.csv",
                "labor": f"{DOWNLOADS}/320_32_00 - Mobile App Onboarding - Snapshot v01.18 - FMG Labor.csv",
                "oop_creative": f"{DOWNLOADS}/320_32_00 - Mobile App Onboarding - Snapshot v01.18 - OOP - Creative Depo's.csv",
                "oop_camera": f"{DOWNLOADS}/320_32_00 - Mobile App Onboarding - Snapshot v01.18 - OOP - Camera Depo's.csv",
                "oop_talent": f"{DOWNLOADS}/320_32_00 - Mobile App Onboarding - Snapshot v01.18 - OOP - Talent.csv",
                "oop_travel-meals": f"{DOWNLOADS}/320_32_00 - Mobile App Onboarding - Snapshot v01.18 - OOP - Travel_Meals.csv",
            },
        },
        {
            "code": "320_35_00",
            "name": "Sweeps 2025",
            "status": "active",
            "files": {
                "snapshot": f"{DOWNLOADS}/320_35_00 - Sweeps 2025- Snapshot v03.22 - Snapshot.csv",
                "oop_creative": f"{DOWNLOADS}/320_35_00 - Sweeps 2025- Snapshot v03.22 - OOP - Creative Depo's.csv",
                "oop_camera": f"{DOWNLOADS}/320_35_00 - Sweeps 2025- Snapshot v03.22 - OOP - Camera Depo's.csv",
                "oop_talent": f"{DOWNLOADS}/320_35_00 - Sweeps 2025- Snapshot v03.22 - OOP - Talent.csv",
                "oop_travel-meals": f"{DOWNLOADS}/320_35_00 - Sweeps 2025- Snapshot v03.22 - OOP - Travel_Meals.csv",
            },
        },
        {
            "code": "320_38_01",
            "name": "CareCredit AI",
            "status": "complete",
            "files": {
                "labor": f"{DOWNLOADS}/320_38_01_A027 - CareCredit AI - Snapshot v03.22 - FMG Labor.csv",
                "oop_creative": f"{DOWNLOADS}/320_38_01_A027 - CareCredit AI - Snapshot v03.22 - OOP - Creative Depo's.csv",
                "oop_camera": f"{DOWNLOADS}/320_38_01_A027 - CareCredit AI - Snapshot v03.22 - OOP - Camera Depo's.csv",
                "oop_talent": f"{DOWNLOADS}/320_38_01_A027 - CareCredit AI - Snapshot v03.22 - OOP - Talent.csv",
                "oop_travel-meals": f"{DOWNLOADS}/320_38_01_A027 - CareCredit AI - Snapshot v03.22 - OOP - Travel_Meals.csv",
            },
        },
        {
            "code": "320_36_01",
            "name": "YouTube Thumbnail Refresh P2",
            "status": "active",
            "files": {
                "snapshot": f"{DOWNLOADS}/320_36_01 -YouTube Thumbnail Refresh P2 - Snapshot v03.22 - Snapshot.csv",
            },
        },
    ]

    results = []
    for proj in projects:
        success = import_project(proj["code"], proj["name"], proj["files"], proj["status"])
        results.append((proj["code"], proj["name"], success))

    # Summary
    print(f"\n{'='*60}")
    print("IMPORT SUMMARY")
    print(f"{'='*60}")
    for code, name, success in results:
        status = "OK" if success else "FAILED"
        print(f"  [{status}] {code} - {name}")
