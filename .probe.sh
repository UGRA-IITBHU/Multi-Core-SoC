#!/bin/bash
# Isolate exactly how GNU sed 4.9 -E reads `\$` next to a quantifier.
export PATH="/c/oss-cad-suite/bin:/c/oss-cad-suite/lib:/c/msys64/usr/bin:$PATH"
cd /e/Multicore_soc/Multi-Core-SoC-main || exit 1

printf 'a $b\n' > build/s.txt

run() { printf '%-34s -> %s\n' "$1" "$(sed -nE "$2" build/s.txt | wc -l)"; }

run 'literal \$'          '/\$/p'
run 'class [$]'           '/[$]/p'
run 'space then \$'       '/[[:space:]]\$/p'
run 'space+ then \$'      '/[[:space:]]+\$/p'
run 'space* then \$'      '/[[:space:]]*\$/p'
run '[[:space:]] then [$] (class)'  '/[[:space:]][$]/p'
run 'a.*\$'               '/a.*\$/p'
run 'a.*[$]'              '/a.*[$]/p'
run '\$b'                 '/\$b/p'
run '[$]b'                '/[$]b/p'