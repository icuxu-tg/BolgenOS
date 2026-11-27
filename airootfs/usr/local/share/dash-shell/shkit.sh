#!/bin/sh
# DESCRIPTION: Библиотека-помощник для POSIX sh-скриптов (подключать через .)
# shkit.sh — компактная "оболочка" для POSIX sh-скриптов: логи, проверки,
# безопасный запуск команд, подтверждения, временные файлы и cleanup-хуки.
#
# Подключение в начале скрипта:
#     . "$(dirname "$0")/shkit.sh"
#
# Возможности:
#   log_info / log_ok / log_warn / log_error / log_step / log_debug
#   die СООБЩЕНИЕ [КОД]        — выход с ошибкой
#   need КОМАНДА ...           — проверить наличие команд
#   require_dir / require_file — проверить пути
#   run КОМАНДА ...            — выполнить (или только показать при DRY_RUN=1)
#   confirm ВОПРОС             — запрос y/N (UNDER ASSUME_YES=1 всегда "да")
#   shkit_tmpdir               — создать $SHKIT_TMPDIR (удаляется при выходе)
#                                 ВАЖНО: вызывайте как `shkit_tmpdir >/dev/null`,
#                                 не в подстановке команд $(...), иначе хук
#                                 очистки будет потерян.
#   on_exit КОМАНДА            — выполнить команду при выходе
#
# Переменные окружения: DEBUG=1, DRY_RUN=1, ASSUME_YES=1, NO_COLOR=1, TMPDIR.

SHKIT_VERSION='0.1.0'
set -eu

# --- Цвета (только если вывод в терминал и не задан NO_COLOR) -------------
if [ -t 2 ] && [ -z "${NO_COLOR:-}" ]; then
    SHK_RESET=$(printf '\033[0m')
    SHK_RED=$(printf '\033[31m')
    SHK_GREEN=$(printf '\033[32m')
    SHK_YELLOW=$(printf '\033[33m')
    SHK_BLUE=$(printf '\033[34m')
    SHK_CYAN=$(printf '\033[36m')
else
    SHK_RESET=''
    SHK_RED=''
    SHK_GREEN=''
    SHK_YELLOW=''
    SHK_BLUE=''
    SHK_CYAN=''
fi

SHKIT_PROG=${0##*/}
SHKIT_EXIT_HOOKS=''
SHKIT_TMPDIR=''

# --- Логирование: всё пишется в stderr, stdout остаётся чистым ------------
_shk_log() {
    _level=$1
    _color=$2
    shift 2
    printf '%s%s%-5s%s %s\n' \
        "$(date '+%H:%M:%S')" "$_color" "$_level" "$SHK_RESET" "$*" >&2
}

log_debug() { [ "${DEBUG:-0}" = 1 ] && _shk_log DEBUG "$SHK_CYAN" "$@" || true; }
log_info()  { _shk_log INFO  "$SHK_BLUE"   "$@"; }
log_step()  { _shk_log STEP  "$SHK_BLUE"   "$@"; }
log_ok()    { _shk_log OK    "$SHK_GREEN"  "$@"; }
log_warn()  { _shk_log WARN  "$SHK_YELLOW" "$@"; }
log_error() { _shk_log ERROR "$SHK_RED"    "$@"; }

die() {
    log_error "${1:-Неизвестная ошибка}"
    exit "${2:-1}"
}

# --- Проверки --------------------------------------------------------------
need() {
    for _cmd in "$@"; do
        command -v "$_cmd" >/dev/null 2>&1 || die "Не найдена команда: $_cmd"
    done
}

require_dir() {
    [ -d "${1:-}" ] || die "Каталог не найден: ${1:-<не задан>}"
}

require_file() {
    [ -f "${1:-}" ] || die "Файл не найден: ${1:-<не задан>}"
}

# --- Выполнение команд с поддержкой "сухого прогона" ----------------------
run() {
    if [ "${DRY_RUN:-0}" = 1 ]; then
        _shk_log DRY "$SHK_YELLOW" "$*"
        return 0
    fi
    _shk_log EXEC "$SHK_CYAN" "$*"
    "$@"
}

# --- Подтверждение ---------------------------------------------------------
confirm() {
    [ "${ASSUME_YES:-0}" = 1 ] && return 0
    printf '%s [y/N]: ' "$*" >&2
    IFS= read -r _answer || return 1
    case $_answer in
        y|Y|yes|YES|да|Да|ДА) return 0 ;;
        *) return 1 ;;
    esac
}

# --- Хуки выхода и временные файлы ----------------------------------------
on_exit() {
    if [ -n "$SHKIT_EXIT_HOOKS" ]; then
        SHKIT_EXIT_HOOKS="$SHKIT_EXIT_HOOKS
$*"
    else
        SHKIT_EXIT_HOOKS=$*
    fi
}

_shk_on_exit() {
    _code=$?
    trap - EXIT HUP INT TERM
    if [ -n "$SHKIT_EXIT_HOOKS" ]; then
        printf '%s\n' "$SHKIT_EXIT_HOOKS" | while IFS= read -r _hook; do
            [ -n "$_hook" ] || continue
            eval "$_hook" >/dev/null 2>&1 || true
        done
    fi
    exit "$_code"
}

shkit_tmpdir() {
    if [ -z "$SHKIT_TMPDIR" ]; then
        SHKIT_TMPDIR=$(mktemp -d "${TMPDIR:-/tmp}/shkit.XXXXXX")
        on_exit "rm -rf '$SHKIT_TMPDIR'"
        log_debug "временный каталог: $SHKIT_TMPDIR"
    fi
    printf '%s\n' "$SHKIT_TMPDIR"
}

# --- Инициализация (не в интерактивной оболочке) --------------------------
shkit_init() {
    [ $# -gt 0 ] && SHKIT_PROG=$1
    trap '_shk_on_exit' EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM
    log_debug "shkit $SHKIT_VERSION готов"
}

case $- in
    *i*) ;;
    *)   shkit_init "${0##*/}" ;;
esac
