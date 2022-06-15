command! SpellSync call spellsync#Run()

" Options
if !exists('g:spellsync_run_at_startup')
    let g:spellsync_run_at_startup = 1
endif

if !exists('g:spellsync_enable_git_union_merge')
    let g:spellsync_enable_git_union_merge = 1
endif

if !exists('g:spellsync_enable_git_ignore')
    let g:spellsync_enable_git_ignore = 1
endif

" Run at startup
if g:spellsync_run_at_startup
  autocmd VimEnter * SpellSync 
endif