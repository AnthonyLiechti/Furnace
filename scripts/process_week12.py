#!/usr/bin/env python3
"""
Process Monday.com resource planner data for Week 12 (March 16-20, 2026)
and update allocations.json for Furnace.
"""

import json
import re
from datetime import datetime, timedelta
from collections import defaultdict

# === CONFIG ===

WEEK_START = datetime(2026, 3, 16)
WEEK_END = datetime(2026, 3, 20)

FILES = [
    "/Users/anthonyliechti/.claude/projects/-Users-anthonyliechti-Documents-Furnace/03cce9c6-000f-4bf1-8327-aaaafd1c704a/tool-results/mcp-b037dd22-6991-44c3-bed4-af890368a5d7-all_monday_api-1774213214248.txt",
    "/Users/anthonyliechti/.claude/projects/-Users-anthonyliechti-Documents-Furnace/03cce9c6-000f-4bf1-8327-aaaafd1c704a/tool-results/mcp-b037dd22-6991-44c3-bed4-af890368a5d7-all_monday_api-1774213296848.txt",
    "/Users/anthonyliechti/.claude/projects/-Users-anthonyliechti-Documents-Furnace/03cce9c6-000f-4bf1-8327-aaaafd1c704a/tool-results/mcp-b037dd22-6991-44c3-bed4-af890368a5d7-all_monday_api-1774213302481.txt",
    "/Users/anthonyliechti/.claude/projects/-Users-anthonyliechti-Documents-Furnace/03cce9c6-000f-4bf1-8327-aaaafd1c704a/tool-results/mcp-b037dd22-6991-44c3-bed4-af890368a5d7-all_monday_api-1774213309428.txt",
]

ALLOCATIONS_PATH = "/Users/anthonyliechti/Documents/Furnace/data/allocations.json"

PERSON_MAP = {
    "8987848044": "Matthew Givot",
    "8987848222": "Jeff Cole",
    "8987848417": "Jeff Butcher",
    "8987848743": "Anthony Liechti",
    "8987849061": "Benny Silva",
    "8987849801": "Dave MacLeod",
    "8987850235": "Richelle Butcher",
    "8987850861": "Brett Yamaoka",
    "8987852652": "Emma",
    "8987853378": "Kirk Crockett",
    "8987853489": "Lexi Golden",
    "8987853630": "Trevor",
    "8991181233": "Trevor",
    "8991181330": "Rae",
    "8991181454": "Emily Spradley",
    "8991181558": "Christian Lau",
    "8991182034": "Jordan Pereira",
    "8991182695": "Evan Figueroa",
    "8991182780": "Grace Donovan",
}

BOARD_PROJECT_MAP = {
    "386_01_01 - Synchrony Organic Social Q1 2026": "Synchrony Organic Social Q2 2026",
    "386_01_02 - Synchrony Organic Social Q2 2026": "Synchrony Organic Social Q2 2026",
    "501_03_01 - Olson Superior Marketing": "Olson Superior Marketing",
    "501_03_01 - Marketing_Post Deliverables": "Olson Superior Marketing",
    "358_16_11 - Yardtopia Website Refresh": "Yardtopia Website Refresh",
    "320_30_10 - CES4 Design": "CES4 Design",
    "320_30_10 - CES4 Post": "CES4 Post",
    "378_06_05 - NEGU Gala Video 2026": "NEGU Gala Video",
    "322_15_01 - CareCredit Organic Social Strategy": "CareCredit Organic Social Strategy",
    "322_13_01 - Walmart Partnership Social Support": "Walmart Partnership Social Support",
    "320_37_04 - Got It Final Deliverables": "Got It Final Deliverables",
    "358_16_12 - Yardtopia Spring Campaign": "Yardtopia Spring Campaign",
    "320_45_01 - P1 February 2026": "CE S5 — Development",
    "320_45_01_A083 - CE S5 - Development": "CE S5 — Development",
    "320_45_01 - CES5 Development": "CE S5 — Development",
    "358_20_01 - Rattlesnake Reservoir Videos": "Rattlesnake Reservoir Videos",
    "358_16_10 - Yardtopia Winter Campaign": "Yardtopia Winter Campaign",
    "900_00_00 - Well Connected Website": "Well Connected Website",
    "384_02_01 - OCCF Flyer Template": "OCCF Flyer Template",
    "321_17_01 - Provider Testimonial - MGMA Orlando": "Provider Testimonial - MGMA Orlando",
    "NA - New Opportunities": "New Opportunities",
    "321_08_04 - Provider Testimonial - CES4 Extras": "Provider Testimonial - CES4 Extras",
    "322_09_01 - My Story July 2025 - May 2026": "My Story July 2025 - February 2026",
    "321_08_02 - Provider Testimonial - CE Partners": "Provider Testimonial - CE Partners",
    "321_00_00 - Provider Testimonial Playbook": "Provider Testimonial Playbook",
    "321_13_01 - Provider Testimonial - Audacity": "Provider Testimonial - Audacity",
    "100_10_01 - Forge Website": "Forge Website 2.0",
    "Internal Meetings and Skill Development": "Internal Meetings and Skill Development",
    "321_08_03 - Provider Testimonial - Chiro": "Provider Testimonial - Chiro",
    "320_32_00 - Mobile App Onboarding Videos": "Mobile App Onboarding",
    "321_07_06 - Business Course #6": "Business Course #6",
    "320_12_02 - UGC 2025-2026": "UGC 2025-2026",
    "321_24_01 - Provider Testimonials (Erin Rose)": "Provider Testimonials (Erin Rose)",
    "322_07_02 - CES4 Social Media Post": "CES4 Social Media Post",
    "320_10_XXX - Small Projects": "Small Projects",
    "301_01_01 - OSP Rebrand": "OSP Rebrand",
    "334_20_01 - Peak Pro Small Projects": "Peak Pro Small Projects",
    "320_34_06 - Well U Embedded Vertical Shorts 2026 Article Test": "Well U Embedded Vertical Shorts 2026",
    "320_46_01_SBW Brand Blitz Testimonials": "SBW Brand Blitz",
    "320_34_05 - Well U - Antonio Well U Shorts": "Antonio Well U Shorts",
    "321_27_01 - Amy Anderson Video Series": "Amy Anderson Video Series",
}


def parse_board_name(raw_name):
    """Extract the board key from a raw Monday board name (strip ' - Resource planner' suffix)."""
    # Remove " - Resource planner" suffix
    name = re.sub(r'\s*-\s*Resource [Pp]lanner\s*$', '', raw_name).strip()
    return name


def map_board_to_project(board_name):
    """Map a board name to a project name using BOARD_PROJECT_MAP with substring matching."""
    clean = parse_board_name(board_name)

    # Direct match first
    if clean in BOARD_PROJECT_MAP:
        return BOARD_PROJECT_MAP[clean]

    # Substring match: check if any key is a substring of clean, or clean is a substring of any key
    for key, project in BOARD_PROJECT_MAP.items():
        if key in clean or clean in key:
            return project

    # Try matching just the prefix (project code)
    for key, project in BOARD_PROJECT_MAP.items():
        # Extract code like "386_01_01" from both
        key_code = key.split(' - ')[0].strip() if ' - ' in key else key
        clean_code = clean.split(' - ')[0].strip() if ' - ' in clean else clean
        if key_code == clean_code and key_code != "":
            return project

    return None


def get_workdays_in_range(start_str, end_str):
    """Return list of workday date strings (Mon-Fri) that overlap with Week 12."""
    try:
        start = datetime.strptime(start_str, "%Y-%m-%d")
        end = datetime.strptime(end_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        return []

    # Clamp to Week 12 range
    effective_start = max(start, WEEK_START)
    effective_end = min(end, WEEK_END)

    if effective_start > effective_end:
        return []

    days = []
    current = effective_start
    while current <= effective_end:
        if current.weekday() < 5:  # Mon-Fri
            days.append(current.strftime("%Y-%m-%d"))
        current += timedelta(days=1)

    return days


def parse_all_files():
    """Parse all Monday API result files and extract board data."""
    all_boards = []

    for filepath in FILES:
        with open(filepath, 'r') as f:
            wrapper = json.load(f)

        # The file is a JSON array with one element containing a "text" field
        if isinstance(wrapper, list) and len(wrapper) > 0:
            text_content = wrapper[0].get("text", "")
        elif isinstance(wrapper, dict):
            text_content = json.dumps(wrapper)
        else:
            continue

        data = json.loads(text_content)

        # data is a dict with keys like "b1", "b2", etc.
        for batch_key, boards in data.items():
            if isinstance(boards, list):
                for board in boards:
                    all_boards.append(board)

    return all_boards


def process_boards(boards):
    """Process all boards and extract Week 12 allocations."""
    allocations = []
    unmapped_boards = set()
    unmapped_persons = set()

    for board in boards:
        board_name = board.get("name", "")
        project = map_board_to_project(board_name)

        if project is None:
            # Track unmapped boards that have Week 12 data
            has_w12_data = False

        items = board.get("items_page", {}).get("items", [])

        for item in items:
            cols = {c["id"]: c.get("text", "") for c in item.get("cols", [])}

            timeline = cols.get("rp_timeline", "")
            effort_str = cols.get("rp_effort_per_day", "")

            if not timeline or not effort_str:
                continue

            # Parse timeline "YYYY-MM-DD - YYYY-MM-DD"
            parts = timeline.split(" - ")
            if len(parts) != 2:
                continue

            start_str, end_str = parts[0].strip(), parts[1].strip()

            workdays = get_workdays_in_range(start_str, end_str)
            if not workdays:
                continue

            try:
                effort_per_day = float(effort_str)
            except (ValueError, TypeError):
                continue

            if effort_per_day <= 0:
                continue

            # Get person
            assignees = item.get("assignee", [])
            person_ids = []
            for a in assignees:
                person_ids.extend(a.get("linked_item_ids", []))

            if not person_ids:
                continue

            person_id = str(person_ids[0])
            person_name = PERSON_MAP.get(person_id)

            if person_name is None:
                unmapped_persons.add(person_id)
                continue

            if project is None:
                unmapped_boards.add(parse_board_name(board_name))
                continue

            for day in workdays:
                allocations.append({
                    "person": person_name,
                    "project": project,
                    "date": day,
                    "hoursPerDay": effort_per_day,
                })

    if unmapped_boards:
        print(f"\nWARNING - Unmapped boards with Week 12 data: {unmapped_boards}")
    if unmapped_persons:
        print(f"WARNING - Unmapped person IDs: {unmapped_persons}")

    return allocations


def aggregate_allocations(raw_allocations):
    """Aggregate duplicate (person, project, date) entries by summing hours."""
    agg = defaultdict(float)
    for a in raw_allocations:
        key = (a["person"], a["project"], a["date"])
        agg[key] += a["hoursPerDay"]

    result = []
    for (person, project, date), hours in sorted(agg.items()):
        result.append({
            "person": person,
            "project": project,
            "date": date,
            "hoursPerDay": round(hours, 4),
        })
    return result


def build_allocation_records(aggregated):
    """Build allocation records in the format expected by allocations.json."""
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    records = []

    for i, a in enumerate(aggregated, 1):
        records.append({
            "id": f"a_w12_{i:04d}",
            "person": a["person"],
            "project": a["project"],
            "date": a["date"],
            "hoursPerDay": a["hoursPerDay"],
            "weekOf": "2026-03-16",
            "totalHours": a["hoursPerDay"],
            "days": 1,
            "notes": "From Monday.com Resource Planner - Week 12",
            "created": now,
            "modified": now,
        })

    return records


def update_allocations_file(new_records):
    """Read existing allocations.json, replace Week 12 data, write back."""
    with open(ALLOCATIONS_PATH, 'r') as f:
        data = json.load(f)

    # Remove existing Week 12 allocations (dates 2026-03-16 through 2026-03-20)
    week12_dates = {"2026-03-16", "2026-03-17", "2026-03-18", "2026-03-19", "2026-03-20"}
    preserved = [a for a in data.get("allocations", []) if a.get("date") not in week12_dates]

    print(f"\nRemoved {len(data.get('allocations', [])) - len(preserved)} existing Week 12 allocations")
    print(f"Preserved {len(preserved)} non-Week-12 allocations")

    # Add new Week 12 records
    data["allocations"] = new_records + preserved

    print(f"Added {len(new_records)} new Week 12 allocations")
    print(f"Total allocations: {len(data['allocations'])}")

    with open(ALLOCATIONS_PATH, 'w') as f:
        json.dump(data, f, indent=2)

    return data


def print_summary(aggregated):
    """Print person totals and project totals for verification."""
    person_totals = defaultdict(float)
    project_totals = defaultdict(float)

    for a in aggregated:
        person_totals[a["person"]] += a["hoursPerDay"]
        project_totals[a["project"]] += a["hoursPerDay"]

    print("\n" + "=" * 60)
    print("PERSON TOTALS (Week 12)")
    print("=" * 60)
    for person in sorted(person_totals.keys()):
        print(f"  {person:25s} {person_totals[person]:6.1f} hrs")
    print(f"  {'TOTAL':25s} {sum(person_totals.values()):6.1f} hrs")

    print("\n" + "=" * 60)
    print("PROJECT TOTALS (Week 12)")
    print("=" * 60)
    for project in sorted(project_totals.keys(), key=lambda p: -project_totals[p]):
        print(f"  {project:50s} {project_totals[project]:6.1f} hrs")
    print(f"  {'TOTAL':50s} {sum(project_totals.values()):6.1f} hrs")

    # Compare with PDF
    pdf_person = {
        "Anthony Liechti": 39.5, "Brett Yamaoka": 40, "Christian Lau": 32,
        "Emily Spradley": 34, "Emma": 45, "Grace Donovan": 35,
        "Jordan Pereira": 41, "Kirk Crockett": 40, "Lexi Golden": 39.5,
        "Rae": 40, "Trevor": 40,
    }

    print("\n" + "=" * 60)
    print("COMPARISON WITH PDF (Person Totals)")
    print("=" * 60)
    print(f"  {'Person':25s} {'Monday':>8s} {'PDF':>8s} {'Diff':>8s}")
    print(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*8}")
    for person in sorted(pdf_person.keys()):
        monday_val = person_totals.get(person, 0)
        pdf_val = pdf_person[person]
        diff = monday_val - pdf_val
        flag = " <--" if abs(diff) > 0.1 else ""
        print(f"  {person:25s} {monday_val:8.1f} {pdf_val:8.1f} {diff:+8.1f}{flag}")


def main():
    print("Parsing Monday.com API result files...")
    boards = parse_all_files()
    print(f"Found {len(boards)} boards across all files")

    print("\nProcessing boards for Week 12 allocations...")
    raw_allocations = process_boards(boards)
    print(f"Found {len(raw_allocations)} raw allocation entries")

    print("\nAggregating duplicate entries...")
    aggregated = aggregate_allocations(raw_allocations)
    print(f"Aggregated to {len(aggregated)} unique (person, project, date) entries")

    print_summary(aggregated)

    print("\nBuilding allocation records...")
    records = build_allocation_records(aggregated)

    print("\nUpdating allocations.json...")
    update_allocations_file(records)

    print("\nDone!")


if __name__ == "__main__":
    main()
