"""First-run guide flag and the Omarchy menu extension block.

Both live outside ~/.config/hypr (H-1) and never touch /usr/share/omarchy (H-6):
  * first-run flag: <OmniPal config dir>/onboarding.json, created once (O_EXCL),
    so the cheat sheet auto-opens the guide exactly one time.
  * menu: Omarchy 4's menu merges ~/.config/omarchy/extensions/omarchy-menu.jsonc
    over its defaults (official user extension). We own one marked block in that
    file and nothing else; uninstall removes only that block.
"""

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ONBOARDING_FILE = "onboarding.json"
MENU_STATE_FILE = "menu.json"
BLOCK_BEGIN = "// >>> OmniPal: managed by `omni-profile menu install`, do not edit inside this block"
BLOCK_END = "// <<< OmniPal"
MENU_ROOT_ID = "setup.omnipal"


def _config_dir() -> Path:
    from engine.engine import resolve_config_dir
    return resolve_config_dir()


# ---------------------------------------------------------------- first run

def onboarding_path(config_dir: Optional[Path] = None) -> Path:
    return (config_dir or _config_dir()) / ONBOARDING_FILE


def onboarding_status(config_dir: Optional[Path] = None) -> Dict[str, Any]:
    p = onboarding_path(config_dir)
    info: Dict[str, Any] = {"shown": p.exists(), "path": str(p)}
    if p.exists():
        try:
            info.update(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        info["shown"] = True
    return info


def onboarding_claim(config_dir: Optional[Path] = None) -> bool:
    """True exactly once: the first caller creates the flag and should show the guide.
    Any later call (or a concurrent second caller) gets False. Errors -> False, so a
    read-only config dir never makes the guide pop up on every login."""
    p = onboarding_path(config_dir)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(p), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return False
    except OSError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"shown_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}, f)
        f.write("\n")
    return True


def onboarding_reset(config_dir: Optional[Path] = None) -> bool:
    p = onboarding_path(config_dir)
    if p.exists():
        p.unlink()
        return True
    return False


# --------------------------------------------------------------------- menu

def menu_extension_path() -> Path:
    env = os.environ.get("OMNIPAL_OMARCHY_MENU_FILE")
    if env:
        return Path(env).expanduser()
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "omarchy" / "extensions" / "omarchy-menu.jsonc"


def strip_jsonc(raw: str) -> str:
    """Same rules as Omarchy's MenuModel.stripJsonc: whole-line // comments and
    trailing commas. Used to verify the file still parses for the menu."""
    s = re.sub(r"^\s*//[^\n]*(\n|$)", "", raw, flags=re.M)
    return re.sub(r",(\s*[}\]])", r"\1", s)


def parse_menu_items(raw: str) -> Optional[Dict[str, Any]]:
    """Item map the Omarchy menu would see, or None when the file would not parse."""
    s = strip_jsonc(raw)
    if not s.strip():
        return {}
    try:
        data = json.loads(s)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    items = data.get("items")
    return items if isinstance(items, dict) else data


def _row(item_id: str, entry: Dict[str, str]) -> str:
    return "  " + json.dumps(item_id, ensure_ascii=False) + ": " + json.dumps(entry, ensure_ascii=False) + ","


def _sh_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def render_menu_block(profiles: List[Dict[str, Any]], cli: str) -> str:
    """The managed block. Mode rows are a snapshot of `omni-profile list --json`;
    install/import re-render it. `checked` reads the tmpfs state broadcast (cheap,
    no Python start per row)."""
    q = _sh_quote(cli)
    state = '"${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/omnipal/state.json"'
    lines = [BLOCK_BEGIN,
             _row(MENU_ROOT_ID, {"icon": "\uf11c", "label": "快捷键模式", "aliases": ["omnipal", "keymode"],
                                 "description": "OmniPal：切换模式、打开设置与速查表"})]
    for p in profiles:
        pid = str(p.get("id", ""))
        if not re.match(r"^[a-z0-9][a-z0-9_-]{0,31}$", pid):
            continue
        lines.append(_row(f"{MENU_ROOT_ID}.mode-{pid}", {
            "icon": "\uf11c",
            "label": str(p.get("name") or pid),
            "description": str(p.get("description") or ""),
            "checked": f"[[ \"$(jq -r .mode {state} 2>/dev/null)\" == {pid} ]]",
            "action": f"{q} switch {pid}",
        }))
    lines.append(_row(f"{MENU_ROOT_ID}.settings", {
        "icon": "\uf013", "label": "打开设置",
        "action": "omarchy-shell shell summon omni.settings '{}'"}))
    lines.append(_row(f"{MENU_ROOT_ID}.cheatsheet", {
        "icon": "\uf059", "label": "速查表",
        "action": "omarchy-shell shell summon omni.cheat-sheet '{}'"}))
    lines.append(_row(f"{MENU_ROOT_ID}.guide", {
        "icon": "\uf05a", "label": "上手指南",
        "action": "omarchy-shell shell summon omni.cheat-sheet '{\"guide\":true}'"}))
    lines.append(BLOCK_END)
    return "\n".join(lines) + "\n"


_BLOCK_RE = re.compile(r"^[ \t]*" + re.escape(BLOCK_BEGIN) + r".*?^[ \t]*" + re.escape(BLOCK_END) + r"[ \t]*\n?",
                       re.S | re.M)


def remove_block(raw: str) -> str:
    return _BLOCK_RE.sub("", raw)


def _needs_comma(before: str) -> bool:
    code = strip_jsonc(before).rstrip()
    return bool(code) and code[-1] not in "{,"


def insert_block(raw: str, block: str) -> str:
    """Replaces our block, or inserts it before the top-level closing brace."""
    base = remove_block(raw)
    if not base.strip():
        return "{\n" + block + "}\n"
    end = base.rstrip().rfind("}")
    if end < 0:
        raise ValueError("not a JSON object")
    head, tail = base[:end], base[end:]
    if _needs_comma(head):
        head = head.rstrip() + ",\n"
    elif not head.endswith("\n"):
        head += "\n"
    return head + block + tail


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".omnipal-tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _state_path(config_dir: Optional[Path]) -> Path:
    return (config_dir or _config_dir()) / MENU_STATE_FILE


def menu_install(profiles: List[Dict[str, Any]], cli: str, path: Optional[Path] = None,
                 config_dir: Optional[Path] = None) -> Dict[str, Any]:
    path = path or menu_extension_path()
    existed = path.exists()
    raw = path.read_text(encoding="utf-8") if existed else ""
    if existed:
        if parse_menu_items(raw) is None:
            raise ValueError(f"{path} 不是可解析的 JSONC，未做修改")
        top = json.loads(strip_jsonc(raw)) if strip_jsonc(raw).strip() else {}
        if isinstance(top.get("items"), dict):
            raise ValueError(f"{path} 使用了 \"items\" 包裹结构，请手动添加 OmniPal 菜单")
    new = insert_block(raw, render_menu_block(profiles, cli))
    parsed = parse_menu_items(new)
    if parsed is None or MENU_ROOT_ID not in parsed:
        raise ValueError(f"写入后 {path} 无法解析，已放弃修改")
    path.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write(path, new)
    sp = _state_path(config_dir)
    prior = {}
    if sp.exists():
        try:
            prior = json.loads(sp.read_text(encoding="utf-8"))
        except ValueError:
            prior = {}
    created = prior.get("created_file", False) if prior.get("path") == str(path) else not existed
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps({"path": str(path), "created_file": created}) + "\n", encoding="utf-8")
    return {"path": str(path), "modes": [k for k in parsed if k.startswith(MENU_ROOT_ID + ".mode-")],
            "created_file": created}


def menu_installed(path: Optional[Path] = None) -> bool:
    path = path or menu_extension_path()
    try:
        return BLOCK_BEGIN in path.read_text(encoding="utf-8")
    except OSError:
        return False


def menu_uninstall(path: Optional[Path] = None, config_dir: Optional[Path] = None) -> Dict[str, Any]:
    sp = _state_path(config_dir)
    state: Dict[str, Any] = {}
    if sp.exists():
        try:
            state = json.loads(sp.read_text(encoding="utf-8"))
        except ValueError:
            state = {}
    path = path or (Path(state["path"]) if state.get("path") else menu_extension_path())
    result = {"path": str(path), "removed_block": False, "removed_file": False}
    if path.exists():
        raw = path.read_text(encoding="utf-8")
        new = remove_block(raw)
        if new != raw:
            result["removed_block"] = True
            leftover = strip_jsonc(new).replace("{", "").replace("}", "").strip()
            if state.get("created_file") and not leftover:
                path.unlink()
                result["removed_file"] = True
            else:
                _atomic_write(path, new)
    if sp.exists():
        sp.unlink()
    return result
