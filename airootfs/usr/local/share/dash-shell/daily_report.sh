#!/bin/sh
# DESCRIPTION: Ежедневный отчёт по git-коммитам в Markdown
# daily_report.sh — ежедневный отчёт по коммитам в формате Markdown.
# Использует shkit.sh: логирование, проверки, DRY_RUN и временный каталог.
#
# Примеры:
#   ./daily_report.sh ~/projects/myapp
#   SINCE='7 days ago' ./daily_report.sh ~/projects/myapp
#   FETCH=1 DEBUG=1 ./daily_report.sh ~/projects/myapp

. "$(dirname "$0")/shkit.sh"

usage() {
    cat <<EOF
Использование: $SHKIT_PROG [ОПЦИИ] [КАТАЛОГ]

  -s ПЕРИОД  передаётся в git --since (по умолчанию: ${SINCE:-yesterday})
  -a АВТОР   фильтр git --author
  -h         показать эту справку

Переменные окружения:
  SINCE      период по умолчанию
  AUTHOR     автор по умолчанию
  FETCH=1    выполнить git fetch перед отчётом
  DRY_RUN=1  не выполнять fetch, только показать команду
  DEBUG=1    подробные логи
  NO_COLOR=1 без цвета
EOF
}

SINCE=${SINCE:-yesterday}
AUTHOR=${AUTHOR:-}
repo=''

while getopts 'hs:a:' _opt; do
    case $_opt in
        h) usage; exit 0 ;;
        s) SINCE=$OPTARG ;;
        a) AUTHOR=$OPTARG ;;
        *) usage >&2; exit 2 ;;
    esac
done
shift $((OPTIND - 1))
[ $# -gt 0 ] && repo=$1
[ -z "$repo" ] && repo=.

need git awk
require_dir "$repo"

REPO=$(cd "$repo" && pwd)
git -C "$REPO" rev-parse --is-inside-work-tree >/dev/null 2>&1 \
    || die "Не git-репозиторий: $REPO"

if [ "${FETCH:-0}" = 1 ]; then
    log_step 'Обновляю удалённые ветки'
    run git -C "$REPO" fetch --quiet --all --prune
fi

log_info "Репозиторий: $REPO"
log_info "Период: $SINCE"

# Собираем аргументы для git log
set -- log --no-merges --since="$SINCE" --pretty='format:%an%x09%h%x09%s'
[ -n "$AUTHOR" ] && set -- "$@" --author="$AUTHOR"

shkit_tmpdir >/dev/null
DATA="$SHKIT_TMPDIR/commits.tsv"
git -C "$REPO" "$@" > "$DATA" || die 'Не удалось получить git log'

printf '# Отчёт за %s\n\n' "$(date '+%Y-%m-%d')"
printf 'Репозиторий: `%s` · период: `%s`\n\n' "${REPO##*/}" "$SINCE"

awk -F '\t' '
{
    if ($1 == "") next
    author = $1
    if (!(author in seen)) {
        seen[author] = 1
        order[++n] = author
    }
    list[author] = list[author] sprintf("  - `%s` %s\n", $2, $3)
    count[author]++
    total++
}
END {
    if (total == 0) {
        print "_За выбранный период коммитов нет._"
        exit
    }
    printf "**Всего коммитов:** %d\n\n", total
    for (i = 1; i <= n; i++) {
        a = order[i]
        printf "### %s — %d\n%s\n", a, count[a], list[a]
    }
}' "$DATA"

log_ok 'Отчёт готов'
