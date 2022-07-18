#!/bin/sh

# This script clears out the PostgreSQL database with the given name and
# loads in the data from the given dump file generated by pg_dump. It
# skips loading entries from the Job table.

DB_NAME=${@:(-2):1}
DUMP_FILE=${@: -1}

BIN=/usr/pgsql-9.6/bin/pg_restore

if [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]] ; then
    echo "Usage: `basename $0` [OPTION...] name-of-database absolute-path-to-dump-file"
    echo $'  -k, --kill-connections\t\tterminates all connections to the database so it can be dropped'
    echo $'  -e, --exclude-jobs\t\tdoes not load in job data (which can take up a lot of space)'
    exit 0
else
  if ! [[ "$DUMP_FILE" = /* ]] ; then
      echo "Path to database dump file must be absolute."
      exit 1
  fi

  if ! [[ -f $DUMP_FILE ]] ; then
      echo "Database dump file must be a file."
      exit 1
  fi
fi

EXCLUDE_JOBS=0
for arg in "$@" ; do
    if [[ "$arg" == "-k" || "$arg" == "--kill-connections" ]] ; then
      echo "TERMINATING DATABASE CONNECTIONS..."
      sudo -u postgres psql -c "SELECT pg_terminate_backend(pid) 
        FROM pg_stat_activity 
        WHERE pid <> pg_backend_pid() AND datname = '$DB_NAME';"
    elif [[ "$arg" == "-e" || "$arg" == "--exclude-jobs" ]] ; then
      EXCLUDE_JOBS=1
    fi
done
sudo -u postgres /bin/bash -c "echo DROPPING DATABASE... \
                        && psql -c \"DROP DATABASE $DB_NAME;\"; \
                        \
                        echo RECREATING DATABASE... \
                        && psql -c \"CREATE DATABASE $DB_NAME;\" \
                        \
                        && echo LOADING DATABASE... \
                        && (if [[ $EXCLUDE_JOBS -eq 1 ]] ; then \
                        $BIN -L <($BIN -l $DUMP_FILE | grep -v 'statistics_job') -d $DB_NAME $DUMP_FILE -c; \
                        else $BIN -d $DB_NAME $DUMP_FILE; fi)"
