# Ryoku palette for fish and fzf. Rendered by the theme daemon; do not edit.
#
# Dropped straight into conf.d, which fish sources on its own, so nothing in the
# shipped config has to include it. Your ~/.config/fish/user.fish loads last and
# still wins.

# Syntax highlighting.
set -g fish_color_normal eedfe3
set -g fish_color_command ffafd3
set -g fish_color_keyword 94d781
set -g fish_color_quote edb8ce
set -g fish_color_redirection d7c1c8
set -g fish_color_end 94d781
set -g fish_color_error ffb4ab
set -g fish_color_param eedfe3
set -g fish_color_comment d7c1c8
set -g fish_color_selection --background=db79a9
set -g fish_color_operator 94d781
set -g fish_color_escape edb8ce
set -g fish_color_autosuggestion d7c1c8
set -g fish_color_cancel ffb4ab
set -g fish_color_search_match --background=db79a9
set -g fish_color_valid_path --underline

# Completion pager.
set -g fish_pager_color_progress d7c1c8
set -g fish_pager_color_prefix ffafd3
set -g fish_pager_color_completion eedfe3
set -g fish_pager_color_description d7c1c8
set -g fish_pager_color_selected_background --background=db79a9

# fzf takes the same palette, so Ctrl-R and Ctrl-T match the terminal they open
# in. Appended to whatever options are already set rather than replacing them.
set -gx FZF_DEFAULT_OPTS "$FZF_DEFAULT_OPTS \
--color=fg:#eedfe3,bg:-1,hl:#ffafd3 \
--color=fg+:#eedfe3,bg+:#db79a9,hl+:#ffafd3 \
--color=info:#edb8ce,prompt:#ffafd3,pointer:#94d781 \
--color=marker:#94d781,spinner:#edb8ce,header:#d7c1c8 \
--color=border:#534249"
