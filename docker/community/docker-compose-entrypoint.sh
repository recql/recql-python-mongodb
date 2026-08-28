#!/bin/bash
# Bootstrap Community Server: replica set + users, then start with keyfile auth.
set -e

DATA_DIR="/data/db"
KEYFILE_SRC="/etc/mongodb/keyfile"
KEYFILE="/data/db/keyfile"
INIT_FLAG="$DATA_DIR/.recql_initialized"

cp "$KEYFILE_SRC" "$KEYFILE"
chmod 400 "$KEYFILE"
chown mongodb:mongodb "$KEYFILE" 2>/dev/null || true

MONGOT_PARAMS=(
  --setParameter "searchIndexManagementHostAndPort=mongot:27028"
  --setParameter "mongotHost=mongot:27028"
  --setParameter "useGrpcForSearch=true"
  --setParameter "skipAuthenticationToSearchIndexManagementServer=false"
)

if [ -f "$INIT_FLAG" ]; then
  echo "MongoDB already initialized, starting with auth..."
  exec mongod --replSet rs0 --bind_ip_all --keyFile "$KEYFILE" "${MONGOT_PARAMS[@]}"
fi

echo "First run — initializing replica set and users..."
mongod --replSet rs0 --bind_ip_all "${MONGOT_PARAMS[@]}" &
MONGOD_PID=$!

for i in $(seq 1 60); do
  if mongosh --eval "db.adminCommand('ping')" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

mongosh --eval '
try {
  rs.initiate({ _id: "rs0", members: [{ _id: 0, host: "mongodb:27017" }] });
} catch (e) {
  print("rs.initiate: " + e.message);
}
'

for i in $(seq 1 60); do
  if mongosh --eval "rs.isMaster().ismaster" 2>/dev/null | grep -q true; then
    break
  fi
  sleep 0.5
done

mongosh --eval '
db.getSiblingDB("admin").createUser({
  user: "admin",
  pwd: "adminPassword",
  roles: ["root"]
});
db.getSiblingDB("admin").createUser({
  user: "mongotUser",
  pwd: "mongotPassword",
  roles: [{ role: "searchCoordinator", db: "admin" }]
});
db.getSiblingDB("admin").createUser({
  user: "recql",
  pwd: "recql",
  roles: ["root"]
});
'

kill "$MONGOD_PID"
wait "$MONGOD_PID" 2>/dev/null || true
touch "$INIT_FLAG"

echo "Starting MongoDB with auth..."
exec mongod --replSet rs0 --bind_ip_all --keyFile "$KEYFILE" "${MONGOT_PARAMS[@]}"
