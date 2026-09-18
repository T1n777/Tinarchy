# Tinarchy Live ISO - Root Zsh Profile

# Auto-launch pastel pink tmux session 'main' on interactive TTY
if [ -z "$TMUX" ] && [ -t 0 ] && [[ $- == *i* ]]; then
    exec tmux new-session -A -s main
fi

# Set pastel-tinted prompt
PROMPT='%F{#ffafd3}tinarchy-live%f %F{#a08b93}%~%f %F{#94d781}#%f '

# Show motd on first shell entry if present
if [ -f /etc/motd ]; then
    cat /etc/motd
fi
