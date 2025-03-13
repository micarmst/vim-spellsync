" vim-spellsync: Magically rebuild Vim spell files
" maintainer:    micarmst <https://github.com/micarmst>
" version:       1.0.0

" Copyright (c) 2022 micarmst
"
" MIT License
"
" Permission is hereby granted, free of charge, to any person obtaining a copy
" of this software and associated documentation files (the "Software"), to deal
" in the Software without restriction, including without limitation the rights
" to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
" copies of the Software, and to permit persons to whom the Software is
" furnished to do so, subject to the following conditions:
"
" The above copyright notice and this permission notice shall be included in all
" copies or substantial portions of the Software.
"
" THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
" IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
" FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
" AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
" LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
" OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
" SOFTWARE.

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
