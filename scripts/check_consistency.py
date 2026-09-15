#!/usr/bin/env python3
"""
OmniPal Consistency Checker
Validates that profiles adhere strictly to schema/actions.json
and ensures no duplicate keybindings exist within any profile.
"""

import json
import os
import sys
from pathlib import Path
from typing import Optional

def _validate_profile_file(p_file: Path, valid_action_ids: dict) -> bool:
    try:
        with open(p_file, "r", encoding="utf-8") as f:
            p_data = json.load(f)
    except Exception as e:
        print(f"❌ Error in {p_file.name}: JSON parse failure: {e}", file=sys.stderr)
        return False

    p_id = p_data.get("id")
    p_name = p_data.get("name", p_id)
    bindings = p_data.get("bindings", [])
    print(f"🔍 Validating profile: {p_name} ({p_file.name}) [{len(bindings)} bindings]...")

    seen_keys = set()
    file_passed = True
    for i, b in enumerate(bindings):
        action = b.get("action")
        mod = b.get("mod", "").strip()
        key = b.get("key", "").strip()

        if not action or action not in valid_action_ids:
            print(f"  ❌ [{p_file.name} #binding {i+1}] Invalid action ID: '{action}'", file=sys.stderr)
            file_passed = False

        if not key:
            print(f"  ❌ [{p_file.name} #binding {i+1}] Missing key definition", file=sys.stderr)
            file_passed = False

        key_combo = f"{mod.upper()} + {key.upper()}" if mod else key.upper()
        if key_combo in seen_keys:
            print(f"  ❌ [{p_file.name} #binding {i+1}] Duplicate key combination: '{key_combo}'", file=sys.stderr)
            file_passed = False
        seen_keys.add(key_combo)

    display = p_data.get("display")
    if display is not None:
        if not isinstance(display, dict):
            print(f"  ❌ [{p_file.name}] 'display' must be an object", file=sys.stderr)
            file_passed = False
        else:
            if "icon" in display and not isinstance(display["icon"], str):
                print(f"  ❌ [{p_file.name}] 'display.icon' must be a string", file=sys.stderr)
                file_passed = False
            if "brief" in display and (not isinstance(display["brief"], str) or len(display["brief"]) > 8):
                print(f"  ❌ [{p_file.name}] 'display.brief' must be a string (<= 8 chars)", file=sys.stderr)
                file_passed = False
            if "color" in display:
                color = display["color"]
                if not isinstance(color, str) or not color.startswith("#") or len(color) not in (4, 7, 9):
                    print(f"  ❌ [{p_file.name}] 'display.color' must be a valid hex color string", file=sys.stderr)
                    file_passed = False

    return file_passed

def check_consistency(project_root: Path, user_profiles_dir: Optional[Path] = None) -> bool:
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
        if not _validate_profile_file(p_file, valid_action_ids):
            all_passed = False

    target_user_dir = user_profiles_dir
    if target_user_dir is None and "OMNIPAL_USER_PROFILES_DIR" in os.environ:
        target_user_dir = Path(os.environ["OMNIPAL_USER_PROFILES_DIR"])

    if target_user_dir and target_user_dir.exists() and target_user_dir.is_dir():
        user_profile_files = list(target_user_dir.glob("*.json"))
        if user_profile_files:
            print(f"\n👤 Validating {len(user_profile_files)} user custom profiles in {target_user_dir}...")
            for u_file in user_profile_files:
                if not _validate_profile_file(u_file, valid_action_ids):
                    all_passed = False

    # Validate Quickshell plugins
    plugins_dir = project_root / "plugins"
    if plugins_dir.exists():
        plugin_dirs = [p for p in plugins_dir.iterdir() if p.is_dir()]
        print(f"\n🧩 Validating {len(plugin_dirs)} Quickshell plugins in {plugins_dir.name}...")
        for p_dir in sorted(plugin_dirs):
            manifest_file = p_dir / "manifest.json"
            if not manifest_file.exists():
                print(f"  ❌ [{p_dir.name}] Missing manifest.json", file=sys.stderr)
                all_passed = False
                continue

            try:
                with open(manifest_file, "r", encoding="utf-8") as f:
                    m = json.load(f)
            except Exception as e:
                print(f"  ❌ [{p_dir.name}] Invalid manifest.json JSON: {e}", file=sys.stderr)
                all_passed = False
                continue

            if m.get("schemaVersion") != 1:
                print(f"  ❌ [{p_dir.name}] schemaVersion must be 1, got {m.get('schemaVersion')}", file=sys.stderr)
                all_passed = False

            required_fields = ["id", "name", "version", "kinds", "entryPoints"]
            for rf in required_fields:
                if rf not in m:
                    print(f"  ❌ [{p_dir.name}] Missing required manifest field: '{rf}'", file=sys.stderr)
                    all_passed = False

            entry_points = m.get("entryPoints", {})
            if not isinstance(entry_points, dict) or not entry_points:
                print(f"  ❌ [{p_dir.name}] entryPoints must be a non-empty object", file=sys.stderr)
                all_passed = False
            else:
                for ep_kind, ep_rel in entry_points.items():
                    target_qml = p_dir / ep_rel
                    if not target_qml.exists():
                        print(f"  ❌ [{p_dir.name}] Entry point '{ep_kind}': file not found: {ep_rel}", file=sys.stderr)
                        all_passed = False
                    else:
                        print(f"  ✅ [{p_dir.name}] ({m.get('id')}) -> {ep_kind}: {ep_rel}")

    if all_passed:
        print("\n🎉 All consistency and plugin validation checks passed cleanly!")
    else:
        print("\n💥 Consistency check failed.", file=sys.stderr)
    return all_passed

if __name__ == "__main__":
    root = Path(__file__).resolve().parent.parent
    success = check_consistency(root)
    sys.exit(0 if success else 1)
