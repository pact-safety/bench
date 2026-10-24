#!/usr/bin/env bash
# Bench UI style gate. Mechanical checks for the five laws in docs/STYLEGUIDE.md.
# Exits non-zero on any violation. Run before every UI PR.
set -uo pipefail

CSS_DIR="static/css"
TEMPLATES="templates"
SRC="static/src"
fail=0

report() {           # report <heading> <grep-output>
  if [ -n "$2" ]; then
    printf '\n\033[31mFAIL\033[0m  %s\n' "$1"
    printf '%s\n' "$2" | sed 's/^/      /'
    fail=1
  else
    printf '\033[32m ok \033[0m  %s\n' "$1"
  fi
}

# --- Law 2: shadows must be a bare var(--shadow-N) -------------------------
hits=$(grep -rnE 'box-shadow[[:space:]]*:' "$CSS_DIR" "$SRC" "$TEMPLATES" 2>/dev/null \
  | grep -vE 'box-shadow[[:space:]]*:[[:space:]]*(none|var\(--shadow-[a-z0-9-]+\)|var\(--[a-z0-9-]+-shadow\)|var\(--focus-ring\)|var\(--inset-hi\))[[:space:]]*;' \
  | grep -vE '^\s*[^:]+:[0-9]+:\s*(/\*|\*)')
report "Law 2 — box-shadow is a bare var(--shadow-1..5)" "$hits"

# --- Law 3: no ad-hoc gradients --------------------------------------------
hits=$(grep -rnE '(linear|radial|conic)-gradient\(' "$CSS_DIR" "$SRC" "$TEMPLATES" 2>/dev/null \
  | grep -vE '^[^:]*:[0-9]+:\s*--(grad-|iris-)' \
  | grep -v 'bench-void-allowed')
report "Law 3 — gradients only in --grad-* tokens" "$hits"

# --- Law 4: theme scopes contain custom properties only ---------------------
hits=$(awk '
  /\[data-theme="[a-z-]+"\][^{]*\{/ {
    # a theme selector followed by anything other than the bare block open
    # the pearl-void backdrop is the one sanctioned theme-scoped rule
    if ($0 !~ /^[[:space:]]*:root\[data-theme="[a-z-]+"\][[:space:]]*\{/ &&
        $0 !~ /body::before/) {
      printf "%s:%d: %s\n", FILENAME, FNR, $0
    }
  }
' "$CSS_DIR"/*.css)
report "Law 4 — [data-theme] scopes hold no component selectors" "$hits"

# --- Law 1: no literal hex outside token definitions ------------------------
hits=$(grep -rnE '#[0-9a-fA-F]{3,8}\b' "$CSS_DIR" 2>/dev/null \
  | grep -vE '^[^:]*:[0-9]+:\s*--' \
  | grep -v 'bench-void-allowed' \
  | grep -vE '^[^:]*:[0-9]+:\s*(/\*|\*)')
report "Law 1 — hex literals only in token definitions" "$hits"

# --- Law 5: animate opacity/transform only ----------------------------------
hits=$(grep -rnE 'transition[[:space:]]*:[^;]*(box-shadow|width|height|top|left|right|bottom|filter|background-position)' "$CSS_DIR" "$SRC" 2>/dev/null)
report "Law 5 — no transitions on layout/paint-heavy properties" "$hits"

# --- Law 5: motion uses duration + ease tokens ------------------------------
hits=$(grep -rnE '(transition|animation)[^;]*[0-9]+(ms|s)\b' "$CSS_DIR" "$SRC" 2>/dev/null \
  | grep -vE '^[^:]*:[0-9]+:\s*--' \
  | grep -v '!important')
report "Law 5 — durations come from var(--duration-*)" "$hits"

# --- Law 5: every @keyframes has a reduce-motion off-switch -----------------
kf=$(grep -rhoE '@keyframes[[:space:]]+[a-z0-9-]+' "$CSS_DIR" | awk '{print $2}' | sort -u)
missing=""
for name in $kf; do
  if ! grep -rqE "animation[^;]*$name" "$CSS_DIR" ; then missing="$missing\n  orphan keyframe: $name"; fi
done
report "Law 5 — no orphan @keyframes" "$(printf '%b' "$missing" | sed '/^$/d')"

# --- Regression guards from docs/UI-AUDIT.md --------------------------------
# D1: a light theme scope must declare color-scheme, or the browser paints
# checkboxes, date inputs, and scrollbars in dark mode.
if grep -rqE '\[data-theme="hyperbolic"\]' "$CSS_DIR" 2>/dev/null; then
  if ! grep -rqE 'color-scheme[[:space:]]*:[[:space:]]*light' "$CSS_DIR" 2>/dev/null; then
    report "D1 — hyperbolic scope declares color-scheme: light" "hyperbolic theme found but no 'color-scheme: light' anywhere in $CSS_DIR"
  else
    report "D1 — hyperbolic scope declares color-scheme: light" ""
  fi
fi

# D7/D8: a scrollable child inside a flex column needs min-height:0.
hits=$(grep -rn 'overflow-y[[:space:]]*:[[:space:]]*auto' "$CSS_DIR" 2>/dev/null \
  | while IFS=: read -r f l rest; do
      start=$((l>40 ? l-40 : 1))
      if ! sed -n "${start},${l}p" "$f" | grep -q 'min-height[[:space:]]*:[[:space:]]*0'; then
        printf '%s:%s: scroll container without a min-height:0 ancestor rule nearby\n' "$f" "$l"
      fi
    done)
report "D7 — scroll containers pair with min-height: 0" "$hits"


# --- Onboarding bubbles: three regression guards ----------------------------
# 1. Law 4 — no .ob-bubble rule inside a theme scope. The strip reads the
#    panel indirection tokens; a themed copy is the duplication the
#    indirection exists to prevent.
hits=$(grep -rnE ':root\[data-theme[^{]*\.ob-bubble' "$CSS_DIR" 2>/dev/null)
report "Bubbles — no .ob-bubble rules inside theme scopes (Law 4)" "$hits"

# 2. Keyframes belong to motion.css: a bubble animation in main.css escapes
#    the global reduce-motion off-switch review.
hits=$(grep -n '@keyframes ob-bubble' static/css/main.css 2>/dev/null)
report "Bubbles — keyframes live in motion.css only" "$hits"

# 3. Bubble state is server-side. localStorage would un-sync the tour across
#    machines and reintroduce the first-paint flash.
hits=$(grep -rn 'localStorage.*\(bubble\|onboarding_bubbles\)' static/js templates 2>/dev/null)
report "Bubbles — state persists to settings_json, never localStorage" "$hits"

printf '\n'
if [ "$fail" -ne 0 ]; then
  printf '\033[31mStyle gate failed.\033[0m See docs/STYLEGUIDE.md.\n'
  exit 1
fi
printf '\033[32mStyle gate passed.\033[0m\n'
