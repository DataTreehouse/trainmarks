#!/bin/bash
# Minimal repro: 3 xsd:double literals, ORDER BY DESC. Correct output: 4999.47 994.66 50.1
# usage: virtuoso_orderby_check.sh openlink/virtuoso-opensource-7:7.2.17
IMG=$1
docker rm -f vt >/dev/null 2>&1; docker run -d --name vt -e DBA_PASSWORD=dba $IMG >/dev/null
for i in $(seq 1 60); do sleep 2; docker exec vt isql 1111 dba dba exec="SELECT 1;" >/dev/null 2>&1 && break; done
docker exec vt isql 1111 dba dba exec="SELECT sys_stat('st_dbms_ver');" | grep -E "^0"
docker exec vt isql 1111 dba dba exec="SPARQL INSERT DATA { GRAPH <http://t/> { <http://t/a> <http://t/p> \"994.66\"^^<http://www.w3.org/2001/XMLSchema#double> . <http://t/b> <http://t/p> \"4999.47\"^^<http://www.w3.org/2001/XMLSchema#double> . <http://t/c> <http://t/p> \"50.1\"^^<http://www.w3.org/2001/XMLSchema#double> . } };" >/dev/null 2>&1
docker exec vt isql 1111 dba dba exec="SPARQL SELECT ?o FROM <http://t/> WHERE { ?s <http://t/p> ?o } ORDER BY DESC(?o);" 2>&1 | grep -E "^[0-9]" | tr '\n' ' '; echo
docker rm -f vt >/dev/null
