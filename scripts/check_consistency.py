#!/usr/bin/env python3
"""
OmniPal Consistency Checker
Validates that profiles adhere strictly to schema/actions.json
and ensures no duplicate keybindings exist within any profile.
"""

import json
import sys
from pathlib import Path

def check_consistency(project_root: Path) -> bool:
    schema_file = project_root / "schema" / "actions.json"
    profiles_dir = project_root / "profiles"

    if not schema_file.exists():
        print(f"❌ Error: Schema file not found: {schema_file}", file=sys.stderr)
        return False

    try:
        with open(schema_file, "r", encoding="utf-8") as f:
            schema_data = json.load(f)
    except Exception as e:
        print(f"❌ Error: Failed to parse schema: {e}", file=sys.stderr)
        return False

    valid_action_ids = {a["id"]: a for a in schema_data.get("actions", [])}
    print(f"✅ Loaded {len(valid_action_ids)} actions from {schema_file.name}")

    if not profiles_dir.exists():
        print(f"❌ Error: Profiles directory not found: {profiles_dir}", file=sys.stderr)
        return False

    all_passed = True
    profile_files = list(profiles_dir.glob("*.json"))
    if not profile_files:
        print(f"❌ Error: No profile JSON files found in {profiles_dir}", file=sys.stderr)
        return False

    for p_file in profile_files:
        try:
            with open(p_file, "r", encoding="utf-8") as f:
                p_data = json.load(f)
        except Exception as e:
            print(f"❌ Error in {p_file.name}: JSON parse failure: {e}", file=sys.stderr)
            all_passed = False
            continue

        p_id = p_data.get("id")
        p_name = p_data.get("name", p_id)
        bindings = p_data.get("bindings", [])
        print(f"🔍 Validating profile: {p_name} ({p_file.name}) [{len(bindings)} bindings]...")

        seen_keys = set()
        for i, b in enumerate(bindings):
            action = b.get("action")
            mod = b.get("mod", "").strip()
            key = b.get("key", "").strip()

            if not action or action not in valid_action_ids:
                print(f"  ❌ [{p_file.name} #binding {i+1}] Invalid action ID: '{action}'", file=sys.stderr)
                all_passed = False

            if not key:
                print(f"  ❌ [{p_file.name} #binding {i+1}] Missing key definition", file=sys.stderr)
                all_passed = False

            key_combo = f"{mod.upper()} + {key.upper()}" if mod else key.upper()
            if key_combo in seen_keys:
                print(f"  ❌ [{p_file.name} #binding {i+1}] Duplicate key combination: '{key_combo}'", file=sys.stderr)
                all_passed = False
            seen_keys.add(key_combo)

    if all_passed:
        print("🎉 All consistency checks passed cleanly!")
    else:
        print("💥 Consistency check failed.", file=sys.stderr)
    return all_passed

if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    success = check_consistency(root)
    sys.exit(0 if success else 1)
