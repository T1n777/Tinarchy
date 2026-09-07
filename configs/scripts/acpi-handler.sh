#!/bin/bash
# ==============================================================================
# Tinarchy ACPI Event Handler
# Controls display backlight powerdown, laptop lid sleep, and power button toggles.
# ==============================================================================

case "$1" in
    button/power)
        case "$2" in
            PBTN|PWRF)
                logger '[Tinarchy] PowerButton pressed: toggling display sleep'
                /usr/local/bin/screen-toggle 2>/dev/null || true
                ;;
            *)
                logger "ACPI action undefined: $2"
                ;;
        esac
        ;;
    button/sleep)
        case "$2" in
            SLPB|SBTN)
                logger '[Tinarchy] SleepButton pressed: powering down display'
                /usr/local/bin/screen-off 2>/dev/null || true
                ;;
            *)
                logger "ACPI action undefined: $2"
                ;;
        esac
        ;;
    ac_adapter)
        case "$2" in
            AC|ACAD|ADP0)
                case "$4" in
                    00000000)
                        logger 'AC unplugged'
                        ;;
                    00000001)
                        logger 'AC plugged'
                        ;;
                esac
                ;;
            *)
                logger "ACPI action undefined: $2"
                ;;
        esac
        ;;
    battery)
        case "$2" in
            BAT0)
                case "$4" in
                    00000000)
                        logger 'Battery online'
                        ;;
                    00000001)
                        logger 'Battery offline'
                        ;;
                esac
                ;;
            CPU0)
                ;;
            *)  logger "ACPI action undefined: $2" ;;
        esac
        ;;
    button/lid)
        case "$3" in
            close)
                logger '[Tinarchy] Laptop lid closed: powering down display'
                /usr/local/bin/screen-off 2>/dev/null || true
                ;;
            open)
                logger '[Tinarchy] Laptop lid opened: restoring display'
                /usr/local/bin/screen-on 2>/dev/null || true
                ;;
            *)
                if grep -q "closed" /proc/acpi/button/lid/*/state 2>/dev/null; then
                    logger '[Tinarchy] Laptop lid closed (fallback): powering down display'
                    /usr/local/bin/screen-off 2>/dev/null || true
                else
                    logger '[Tinarchy] Laptop lid opened (fallback): restoring display'
                    /usr/local/bin/screen-on 2>/dev/null || true
                fi
                ;;
        esac
        ;;
    *)
        logger "ACPI group/action undefined: $1 / $2"
        ;;
esac
