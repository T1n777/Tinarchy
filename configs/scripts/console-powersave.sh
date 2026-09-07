# Enforce DPMS hardware powerdown and 1-minute screen blanking on Linux virtual consoles
if [ "$TERM" = "linux" ] && [ -t 0 ]; then
    sudo -n /usr/bin/setterm --term linux --blank 1 --powersave powerdown --powerdown 1 < /dev/tty > /dev/tty 2>/dev/null || /usr/bin/setterm --blank 1 2>/dev/null || true
fi
