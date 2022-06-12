command! SpellSync call s:spellSync()

function! s:spellSync()
  call s:syncSpellDirs()
  call s:syncSpellFiles()
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
    call s:buildSpellFile(l:spellFile)

    let l:dir = fnamemodify(l:spellFile,':h')
    call s:gitSetupUnionMerge(l:dir)
    call s:gitIgnoreSpellFiles(l:dir)
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
  let l:gitattributes = a:dir . '/.gitattributes'
  if !filereadable(l:gitattributes)
    silent! call writefile(['*.add merge=union'], l:gitattributes)
  endif
endfunction

function! s:gitIgnoreSpellFiles(dir)
  let l:gitignore = a:dir . '/.gitignore'
  if !filereadable(l:gitignore)
    silent! call writefile(['*.spl', '*.sug'], l:gitignore)
  endif
endfunction

"Run at startup
SpellSync