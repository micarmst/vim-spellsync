" If spellfile exists use that directory
if (len(&spellfile) > 0)
	let s:dirs = split(fnamemodify(&spellfile,":h"), '\n')
" Otherwise get available built-in spell directories
else
	let s:dirs = split(globpath(&rtp, 'spell'), '\n')
endif

" Search each spell directory for word lists
for s:dir in s:dirs

  let s:active = 0
  let s:wordlists = split(globpath(s:dir, '*.add'), '\n')

  " Regenerate spell file for each word list
  for s:wordlist in s:wordlists

    if !filewritable(s:wordlist)
      continue
    endif

    let s:active = 1
    let s:spell_file = s:wordlist . '.spl'

    " Call mkspell if the spell file is out of date
    if getftime(s:wordlist) > getftime(s:spell_file)
      silent exec 'mkspell! ' . fnameescape(s:wordlist)
    endif

  endfor

  " Create gitignore and gitattributes for active spell folders
  if s:active

    " gitignore
    let s:gitignore = s:dir . '/' . '.gitignore'
    if !filereadable(s:gitignore)
      call writefile(['*.spl', '*.sug'], s:gitignore)
    endif

    " gitattributes
    let s:gitattributes = s:dir . '/' . '.gitattributes'
    if !filereadable(s:gitattributes)
      call writefile(['*.add merge=union'], s:gitattributes)
    endif

  endif

endfor
