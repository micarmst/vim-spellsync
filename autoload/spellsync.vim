" vim-spellsync: Magically rebuild Vim spell files
" maintainer:    micarmst <https://github.com/micarmst>
" version:       0.1.0

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

function! spellsync#Run()
  call s:syncSpellDirs()
  call s:syncSpellFiles()
  call s:spellReload()
endfunction

function! s:syncSpellDirs()
  let l:dirs = split(globpath(&runtimepath, 'spell'), '\n')

  for l:dir in l:dirs
    call s:gitSetupUnionMerge(l:dir)
    call s:gitIgnoreSpellFiles(l:dir)
    let l:wordlists = split(globpath(l:dir, '*.add'), '\n')
    for l:wordlist in l:wordlists
      call s:buildSpellFile(l:wordlist)
    endfor
  endfor
endfunction

function! s:syncSpellFiles()
  let l:customSpellFiles = split(&spellfile, ',')
  for l:spellFile in l:customSpellFiles
    let l:dir = fnamemodify(l:spellFile,':h')
    call s:gitSetupUnionMerge(l:dir)
    call s:gitIgnoreSpellFiles(l:dir)
    call s:buildSpellFile(l:spellFile)
  endfor
endfunction

function! s:buildSpellFile(wordlist)
  " Check user has write access to this location
  if !filewritable(a:wordlist)
    return
  endif

  let l:spell_file = a:wordlist . '.spl'

  " Call mkspell if the spell file is out of date
  if getftime(a:wordlist) > getftime(l:spell_file)
    silent! exec 'mkspell! ' . fnameescape(a:wordlist)
  endif
endfunction

function! s:gitSetupUnionMerge(dir)
  if g:spellsync_enable_git_union_merge
    let l:gitattributes = a:dir . '/.gitattributes'
    if !filereadable(l:gitattributes)
      silent! call writefile(['*.add merge=union'], l:gitattributes)
    endif
  endif
endfunction

function! s:gitIgnoreSpellFiles(dir)
  if g:spellsync_enable_git_ignore
    let l:gitignore = a:dir . '/.gitignore'
    if !filereadable(l:gitignore)
      silent! call writefile(['*.spl', '*.sug'], l:gitignore)
    endif
  endif
endfunction

function! s:spellReload()
  " Even after rebuilding the spell file, Vim will still highlight new words as
  " mistakes until it is restarted. Misusing the spellundo command as below
  " forces Vim to reload its spell check as it attempts to remove a fake word.
  silent! spellundo U1BFTExTWU5D
endfunction
