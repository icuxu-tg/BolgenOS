#!/bin/sh
# DESCRIPTION: Интерактивная оболочка-запускалка для shell-скриптов
# shellmenu.sh — «оболочка для shell»: находит скрипты в каталоге, показывает
# меню, позволяет запускать их с аргументами, фильтровать, повторять последний
# запуск и выполнять произвольные команды через sh. Построен на shkit.sh.
#
# Запуск:
#   ./shellmenu.sh [КАТАЛОГ]     # по умолчанию — текущий каталог

. "$(dirname "$0")/shkit.sh"

TARGET_DIR=${1:-.}
TARGET_DIR=$(cd "$TARGET_DIR" 2>/dev/null && pwd) || die "Нет каталога: $TARGET_DIR"
HOME_DIR=${HOME:-$TARGET_DIR}
HISTORY="$HOME_DIR/.shellmenu_history"
LIMIT=20

need awk sed grep head tail mv date

ROWS=''
COUNT=0
FILTER_ROWS=''
FILTER_ACTIVE=0

# --- Сканирование каталога -------------------------------------------------
_scan() {
    ROWS=''
    COUNT=0
    for f in "$TARGET_DIR"/*.sh "$TARGET_DIR"/*.py; do
        [ -f "$f" ] || continue
        name=${f##*/}
        case $name in
            shkit.sh|shellmenu.sh) continue ;;
        esac

        desc=$(sed -n 's/^[[:space:]]*#[[:space:]]*DESCRIPTION:[[:space:]]*//p' "$f" | head -n 1)
        if [ -z "$desc" ]; then
            desc=$(sed -n '2,8{s/^[[:space:]]*#[[:space:]]*//p;}' "$f" | head -n 1)
        fi
        [ -n "$desc" ] || desc='—'

        COUNT=$((COUNT + 1))
        _row=$(printf '%s\t%s\t%s' "$COUNT" "$name" "$desc")
        if [ -n "$ROWS" ]; then
            ROWS=$(printf '%s\n%s' "$ROWS" "$_row")
        else
            ROWS=$_row
        fi
    done
    FILTER_ROWS=''
    FILTER_ACTIVE=0
}

# --- Отображение -----------------------------------------------------------
_show() {
    if [ "$FILTER_ACTIVE" = 1 ]; then
        _list=$FILTER_ROWS
    else
        _list=$ROWS
    fi
    printf '\n=== Скрипты в %s ===\n' "$TARGET_DIR"
    if [ -z "$_list" ]; then
        printf '  (скриптов не найдено)\n'
    else
        printf '%s\n' "$_list" | awk -F '\t' '
            BEGIN { printf " %-4s %-24s %s\n", "№", "ФАЙЛ", "ОПИСАНИЕ" }
            { printf " %-4s %-24s %s\n", $1, $2, $3 }
        '
    fi
    printf '\nКоманды: номер — запустить · /текст — фильтр · r — повторить · '
    printf 'c путь — сменить папку · !команда — выполнить в sh · h — справка · q — выход\n'
}

_history() {
    if [ ! -f "$HISTORY" ]; then
        log_info 'История пуста'
        return 0
    fi
    printf '\n=== Последние запуски ===\n'
    awk -F '\t' '{ printf " %2d. %s  %s  %s\n", NR, $1, $2, $3 }' "$HISTORY"
}

_trim_history() {
    [ -f "$HISTORY" ] || return 0
    shkit_tmpdir >/dev/null
    TMPH="$SHKIT_TMPDIR/history"
    tail -n "$LIMIT" "$HISTORY" > "$TMPH" && mv "$TMPH" "$HISTORY" || true
}

# --- Запуск ----------------------------------------------------------------
_exec() {
    _file=$1
    shift
    log_step "Запуск: $_file $*"
    printf '%s\t%s\t%s\n' "$(date '+%m-%d %H:%M')" "$_file" "$*" >> "$HISTORY"
    _trim_history

    case $_file in
        *.py) _runner=python3 ;;
        *)    _runner=sh ;;
    esac
    if ( cd "$TARGET_DIR" && "$_runner" "$_file" "$@" ); then
        log_ok "Успешно: $_file"
    else
        _code=$?
        log_error "Код выхода $_code: $_file"
    fi
}

_run_by_number() {
    _n=$1
    _row=$(printf '%s\n' "$ROWS" | awk -F '\t' -v n="$_n" '$1 == n { print; exit }')
    if [ -z "$_row" ]; then
        log_warn "Нет скрипта с номером $_n"
        return 0
    fi
    _name=$(printf '%s\n' "$_row" | awk -F '\t' '{ print $2 }')

    printf 'Аргументы для %s (Enter — без аргументов): ' "$_name"
    IFS= read -r _args || _args=''
    # Намеренное разбиение строки на аргументы (обычная оболочка)
    set -- $_args
    _exec "$_name" "$@"
}

_rerun() {
    [ -f "$HISTORY" ] || { log_warn 'История пуста'; return 0; }
    _last=$(tail -n 1 "$HISTORY")
    [ -n "$_last" ] || { log_warn 'История пуста'; return 0; }
    _file=$(printf '%s\n' "$_last" | awk -F '\t' '{ print $2 }')
    _args=$(printf '%s\n' "$_last" | awk -F '\t' '{ print $3 }')
    set -- $_args
    _exec "$_file" "$@"
}

# --- Главный цикл ----------------------------------------------------------
main() {
    _scan
    log_info "shellmenu готов: найдено скриптов: $COUNT. Наберите h для справки."
    while :; do
        _show
        printf '\n> '
        IFS= read -r _input || break

        case $_input in
            q|Q|quit|exit) break ;;
            h|'?') log_info 'Команды меню описаны выше' ;;
            l) FILTER_ROWS=''; FILTER_ACTIVE=0 ;;
            hist) _history ;;
            r|rr) _rerun ;;
            c\ *)
                _dir=${_input#c }
                [ -n "$_dir" ] || continue
                if [ -d "$_dir" ]; then
                    TARGET_DIR=$(cd "$_dir" && pwd)
                    _scan
                    log_ok "Каталог: $TARGET_DIR"
                else
                    log_warn "Нет каталога: $_dir"
                fi
                ;;
            '!'*)
                _cmd=${_input#\!}
                [ -n "$_cmd" ] || continue
                run sh -c "$_cmd" || log_warn "Команда завершилась с ошибкой: $_cmd"
                ;;
            /*)
                _filter=${_input#/}
                if [ -z "$_filter" ]; then
                    FILTER_ROWS=''
                    FILTER_ACTIVE=0
                else
                    FILTER_ROWS=$(printf '%s\n' "$ROWS" | grep -F "$_filter" || true)
                    FILTER_ACTIVE=1
                    [ -n "$FILTER_ROWS" ] || log_warn 'Ничего не найдено'
                fi
                ;;
            *)
                case $_input in
                    ''|*[!0-9]*) log_warn 'Введите номер, /фильтр или команду' ;;
                    *) _run_by_number "$_input" ;;
                esac
                ;;
        esac
    done
    log_ok 'До встречи'
}

main "$@"
