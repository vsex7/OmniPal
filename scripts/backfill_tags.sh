#!/usr/bin/env bash
#
# backfill_tags.sh — 回填 OmniPal 缺失的 git release tag（v1.3.0 ~ v1.8.0）
#
# 背景（2026-10-17 核查）：git tag 只打到 v1.2.0，而 CHANGELOG.md 已记录到
# v1.8.0（v1.9.0 仍是未发布草稿，不打 tag）。本脚本在有 push 权限的机器上运行，
# 把每个已发布版本对应的 commit 打上 annotated tag。
#
# 用法：
#   cd /path/to/OmniPal        # 你的本地仓库（main 分支最新）
#   DRY_RUN=1 bash scripts/backfill_tags.sh   # 先干跑，验证定位逻辑
#   bash scripts/backfill_tags.sh             # 实际创建 tag（本地），最后会询问是否 push
#
# 定位规则（绝不猜测）：
#   1. 优先找 release 标记 commit：subject 形如 "chore(release): vX.Y.Z" /
#      "release: vX.Y.Z"；若命中多条或零条则走第 2 步；
#   2. 再找 feat 标记 commit：subject 形如 "feat(vX.Y.Z): ..." 或 "feat(...): ... (vX.Y.Z)"；
#      若仍不是唯一一条，报错退出；
#   3. 校验该 commit 的作者日期（%cs）必须等于 CHANGELOG 中的发布日期，否则报错退出。
#
# 已存在的 tag 会被跳过（幂等，可重复运行）。

set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

# 版本 → CHANGELOG 发布日期（YYYY-MM-DD）
VERSIONS="
1.3.0 2026-09-15
1.4.0 2026-09-15
1.5.0 2026-09-15
1.6.0 2026-09-15
1.7.0 2026-09-15
1.7.1 2026-10-14
1.8.0 2026-10-14
"

DRY_RUN="${DRY_RUN:-0}"
CREATED=()

# annotated tag 需要 tagger 身份；用户机器上通常已配好 git identity，
# 没配时给一个明确的兜底，避免脚本中途报错。
if ! git config user.email >/dev/null 2>&1; then
    export GIT_COMMITTER_NAME="${GIT_COMMITTER_NAME:-OmniPal}"
    export GIT_COMMITTER_EMAIL="${GIT_COMMITTER_EMAIL:-omnipal@localhost}"
fi

# 在 commit 列表中按 subject 正则挑出唯一候选；打印 sha 或空行
pick_unique() {
    local pattern="$1"; shift
    local -a shas=()
    while IFS= read -r line; do
        local sha="${line%% *}"
        local subject="${line#* }"
        if [[ "$subject" =~ $pattern ]]; then
            shas+=("$sha")
        fi
    done < <(git log --all --date=short --pretty='%H %s' -i --grep="v${ver_escaped}")
    if ((${#shas[@]} == 1)); then
        echo "${shas[0]}"
    fi
}

locate_commit() {
    local ver="$1"
    local ver_escaped="${ver//'.'/[.]}"   # -> v1[.]8[.]0, safe for git --grep and bash [[ =~ ]]

    local candidates
    candidates="$(git log --all --date=short --pretty='%H %s' -i --grep="v${ver_escaped}")"
    if [[ -z "$candidates" ]]; then
        echo "ERROR: v${ver}: no commit mentions this version" >&2
        return 1
    fi

    local sha
    # 规则 1：release 标记 commit
    sha="$(pick_unique "^[Cc][Hh][Oo][Rr][Ee]\([^)]*\)?:[[:space:]]*v?${ver_escaped}([[:space:]]|$)" )"
    if [[ -z "$sha" ]]; then
        sha="$(pick_unique "^[Rr][Ee][Ll][Ee][Aa][Ss][Ee](\([^)]*\))?:[[:space:]]*v?${ver_escaped}([[:space:]]|$)" )"
    fi
    # 规则 2：feat 标记 commit（版本在 scope 括号里，如 feat(v1.3.0): ...）
    if [[ -z "$sha" ]]; then
        sha="$(pick_unique "^[Ff][Ee][Aa][Tt]\(v?${ver_escaped}\):")"
    fi
    # 规则 3：subject 末尾括号里带版本，如 feat(ui): ... (v1.6.0)
    if [[ -z "$sha" ]]; then
        sha="$(pick_unique "\(v${ver_escaped}\)[[:space:]]*$")"
    fi
    if [[ -z "$sha" ]]; then
        echo "ERROR: v${ver}: cannot locate a UNIQUE commit." >&2
        echo "Candidates were:" >&2
        echo "$candidates" | sed 's/^/  /' >&2
        echo "Fix the ambiguity manually (e.g. git tag -a v${ver} <sha>) and re-run." >&2
        return 1
    fi
    echo "$sha"
}

while read -r ver expect_date; do
    [[ -z "$ver" ]] && continue
    if git rev-parse -q --verify "refs/tags/v${ver}" >/dev/null; then
        echo "SKIP v${ver}: tag already exists"
        continue
    fi
    sha="$(locate_commit "$ver")" || exit 1
    actual_date="$(git show -s --format=%cs "$sha")"
    if [[ "$actual_date" != "$expect_date" ]]; then
        echo "ERROR: v${ver}: located commit $sha has date $actual_date, expected $expect_date (CHANGELOG)." >&2
        echo "Refusing to tag. Investigate manually." >&2
        exit 1
    fi
    subject="$(git log -1 --pretty=%s "$sha")"
    if [[ "$DRY_RUN" == "1" ]]; then
        echo "DRY-RUN v${ver} -> ${sha:0:7} ($actual_date) \"$subject\""
    else
        git tag -a "v${ver}" -m "OmniPal v${ver} (backfilled 2026-10-17; CHANGELOG date $expect_date)" "$sha"
        echo "TAGGED v${ver} -> ${sha:0:7} ($actual_date) \"$subject\""
        CREATED+=("v${ver}")
    fi
done <<< "$VERSIONS"

if [[ "$DRY_RUN" == "1" ]]; then
    echo "Dry run done. All versions located unambiguously."
    exit 0
fi

if ((${#CREATED[@]} == 0)); then
    echo "Nothing new to push."
    exit 0
fi

echo
echo "Created ${#CREATED[@]} tag(s): ${CREATED[*]}"
read -r -p "Push them to origin now? [y/N] " ans
if [[ "$ans" =~ ^[Yy]$ ]]; then
    git push origin "${CREATED[@]}"
    echo "Pushed."
else
    echo "Not pushed. Run later:  git push origin ${CREATED[*]}"
fi
