# Tinarchy Live ISO - Root Bash Profile

# Auto-launch pastel pink tmux session 'main' on interactive TTY
if [ -z "$TMUX" ] && [ -t 0 ] && [[ $- == *i* ]]; then
    exec tmux new-session -A -s main
fi

# Set pastel-tinted prompt
PS1='\[\033[38;2;255;175;211m\]tinarchy-live\[\033[0m\] \[\033[38;2;160;139;147m\]\w\[\033[0m\] \[\033[38;2;148;215;129m\]#\[\033[0m\] '

# Show branded telemetry readout on shell entry
if command -v tinarchy-fetch >/dev/null 2>&1; then
    tinarchy-fetch
elif [ -f /etc/motd ]; then
    cat /etc/motd
fi

echo -e "\033[38;2;83;66;73m╭──────────────────────────────────────────────────────────────────────────╮\033[0m"
echo -e "\033[38;2;83;66;73m│\033[0m  🍍 \033[1mTo install Tinarchy OS to your drive, run:\033[0m                           \033[38;2;83;66;73m│\033[0m"
echo -e "\033[38;2;83;66;73m│\033[0m     \033[38;2;255;175;211m\033[1m# tinarchy-installer\033[0m                                               \033[38;2;83;66;73m│\033[0m"
echo -e "\033[38;2;83;66;73m╰──────────────────────────────────────────────────────────────────────────╯\033[0m"
echo ""
