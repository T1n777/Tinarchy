# Enforce DPMS hardware powerdown and 3-minute screen blanking on Linux virtual consoles
if [ "$TERM" = "linux" ] && [ -t 0 ]; then
    sudo -n /usr/bin/setterm --term linux --blank 3 --powersave powerdown --powerdown 3 < /dev/tty > /dev/tty 2>/dev/null || /usr/bin/setterm --blank 3 2>/dev/null || true
fi
