#!/usr/bin/env bash
# Against a running stack with docker-compose.fabs.yml: create a shift in each fab through the
# API, then query every database directly. Each fab's shift must exist only in its own database.
set -euo pipefail
api=${API:-http://localhost:8080/api}
compose=(docker compose -f docker-compose.yml -f docker-compose.fabs.yml)
count() {  # count <service> <db> <shift id>
  "${compose[@]}" exec -T "$1" psql -U fab -d "$2" -tAc "SELECT COUNT(*) FROM shifts WHERE id = '$3'"
}
token=$(curl -sf -X POST "$api/auth/demo" -H 'content-type: application/json' -d '{"role":"dispatcher"}' \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['access_token'])")
auth=(-H "Authorization: Bearer $token" -H 'content-type: application/json')
shift_for() {
  sc=$(curl -sf "${auth[@]}" -X POST "$api/scenario" -d "{\"fab_id\":\"$1\",\"n_engineers\":6,\"n_jobs\":16}")
  curl -sf "${auth[@]}" -X POST "$api/shifts" -d "{\"scenario\":$sc,\"algorithm\":\"greedy\"}" \
    | python3 -c "import json,sys; print(json.load(sys.stdin)['state']['id'])"
}
one=$(shift_for fab1-300mm-logic); two=$(shift_for fab2-200mm-analog)
echo "fab 1 shift $one, fab 2 shift $two"
curl -sf "$api/health" | python3 -c "import json,sys; h=json.load(sys.stdin); print(h); assert h['databases']==3 and h['schema_ok'], h"
fail=0
check() {  # check <label> <actual> <expected>
  if [ "$2" = "$3" ]; then echo "ok   $1 = $2"; else echo "FAIL $1 = $2, expected $3"; fail=1; fi
}
check "fab1 database has fab 1's shift" "$(count postgres-fab1 fab1 "$one")" 1
check "fab1 database has fab 2's shift" "$(count postgres-fab1 fab1 "$two")" 0
check "fab2 database has fab 2's shift" "$(count postgres-fab2 fab2 "$two")" 1
check "fab2 database has fab 1's shift" "$(count postgres-fab2 fab2 "$one")" 0
check "default database has fab 1's shift" "$(count postgres fab "$one")" 0
check "default database has fab 2's shift" "$(count postgres fab "$two")" 0
exit $fail
