# Tinarchy Live ISO - Root Bash Profile

# Auto-launch pastel pink tmux session 'main' on interactive TTY
if [ -z "$TMUX" ] && [ -t 0 ] && [[ $- == *i* ]]; then
    exec tmux new-session -A -s main
fi

# Set pastel-tinted prompt
PS1='\[\033[38;2;255;175;211m\]tinarchy-live\[\033[0m\] \[\033[38;2;160;139;147m\]\w\[\033[0m\] \[\033[38;2;148;215;129m\]#\[\033[0m\] '

if [ -f /etc/motd ]; then
    cat /etc/motd
fi
