# ~/.local/bin on PATH for every shell, not only interactive: tools dropped in
# there (claude, oh-my-posh) work, and the ryoku-fastfetch wrapper below
# resolves. fish_add_path is idempotent.
if test -d $HOME/.local/bin
  fish_add_path $HOME/.local/bin
end

# point `go install` and `cargo install` at ~/.local/bin, and keep an existing
# editor choice.
set -gx GOBIN $HOME/.local/bin
set -gx CARGO_INSTALL_ROOT $HOME/.local
set -q EDITOR; or set -gx EDITOR nvim
set -q VISUAL; or set -gx VISUAL nvim

if status is-interactive
  set -g fish_greeting

  # Terminal Session Persistence (tmux auto-attach for SSH & Default TTY)
  if test -z "$TMUX"
    and test -z "$NO_AUTO_TMUX"
    and test -t 1
    if test -n "$SSH_CONNECTION" -o -n "$SSH_CLIENT" -o -n "$SSH_TTY"; or string match -rq '^/dev/tty[0-9]+$' (tty 2>/dev/null)
      exec tmux new-session -A -s main
    end
  end

  # branded system readout on terminal open (skipped in embedded terminals like Dolphin/Konsole).
  if command -v ryoku-fastfetch >/dev/null 2>&1
    and not set -q KONSOLE_VERSION
    and not set -q KONSOLE_DBUS_SERVICE
    and not set -q DOLPHIN_CONTROL_PID
    and not set -q NO_FASTFETCH
    ryoku-fastfetch
  end

  # prompt.
  if command -v starship >/dev/null 2>&1
    starship init fish | source
  end

  # directory jumper: hook `cd` into zoxide so plain `cd` learns and jumps to
  # frecent dirs (`cdi` for an interactive pick).
  if command -v zoxide >/dev/null 2>&1
    zoxide init fish --cmd cd | source
  end

  # runtime version manager: shims + per-project tool versions.
  if command -v mise >/dev/null 2>&1
    mise activate fish | source
  end

  # fzf walks the tree via fd when present.
  if command -v fd >/dev/null 2>&1
    set -gx FZF_DEFAULT_COMMAND 'fd --hidden --follow --exclude .git'
    set -gx FZF_CTRL_T_COMMAND $FZF_DEFAULT_COMMAND
    set -gx FZF_ALT_C_COMMAND 'fd --type d --hidden --follow --exclude .git'
  end

  # fzf keys: Ctrl-R history, Ctrl-T files, Alt-C cd.
  if command -v fzf >/dev/null 2>&1
    fzf --fish | source
  end

  # eza listings.
  if command -v eza >/dev/null 2>&1
    alias ls 'eza -lh --group-directories-first --icons=auto'
    alias lsa 'ls -a'
    alias lt 'eza --tree --level=2 --long --icons --git'
    alias lta 'lt -a'
  end
end

# user overrides: ~/.config/fish/user.fish is never shipped, never touched on
# update, and loads last so your stuff wins.
test -f $__fish_config_dir/user.fish && source $__fish_config_dir/user.fish
