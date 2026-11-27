"""Install local logging assets without granting Filebeat setup privileges."""

import base64
import json
import os
from urllib.request import Request, urlopen

TOKEN = base64.b64encode(f'elastic:{os.environ["ELASTIC_PASSWORD"]}'.encode()).decode()


def put(path, value):
    request = Request("http://elasticsearch:9200" + path, json.dumps(value).encode(), method="PUT",
                      headers={"Authorization": "Basic " + TOKEN, "Content-Type": "application/json"})
    with urlopen(request, timeout=90) as response:
        response.read()


def main():
    put("/_security/user/kibana_system/_password", {"password": os.environ["KIBANA_SYSTEM_PASSWORD"]})
    put("/_security/role/thesis_log_writer", {
        "cluster": ["monitor"],
        "indices": [{"names": ["thesis-logs-*"], "privileges": ["auto_configure", "index"]}],
    })
    put("/_security/user/filebeat_thesis", {
        "password": os.environ["FILEBEAT_WRITER_PASSWORD"], "roles": ["thesis_log_writer"],
    })
    put("/_ilm/policy/thesis-logs-7d", {"policy": {"phases": {"delete": {
        "min_age": "7d", "actions": {"delete": {}},
    }}}})
    aliases = {"service_name": "service", "trace_id": "trace_id", "span_id": "span_id",
               "request_id": "request_id", "event_id": "event_id", "level": "level", "message": "event",
               "endpoint": "route", "http_method": "method", "status_code": "status",
               "duration_ms": "duration_ms", "error_type": "code", "dependency_service": "dependency"}
    allowed = sorted(set(aliases.values()) | {"timestamp", "attempt", "attempts"})
    script = """
        if (!(ctx.app instanceof Map)) { throw new IllegalArgumentException('missing app record'); }
        for (def key : ctx.app.keySet()) {
          if (!params.allowed.contains(key)) { throw new IllegalArgumentException('unexpected app field'); }
        }
        for (def alias : params.aliases.entrySet()) {
          def v = ctx.app[alias.getValue()];
          if (v != null) { ctx[alias.getKey()] = v; }
        }
        if (ctx.status_code != null && (!(ctx.status_code instanceof Number) ||
            ctx.status_code < 100 || ctx.status_code > 599)) {
          throw new IllegalArgumentException('invalid status');
        }
        if (ctx.duration_ms != null && (!(ctx.duration_ms instanceof Number) || ctx.duration_ms < 0)) {
          throw new IllegalArgumentException('invalid duration');
        }
    """
    put("/_ingest/pipeline/thesis-app-v1", {
        "description": "Validate app JSON, retain app.*, normalize fields",
        "processors": [
            {"script": {"source": script, "params": {"allowed": allowed, "aliases": aliases}}},
            {"date": {"field": "app.timestamp", "formats": ["ISO8601"], "output_format": "yyyy-MM-dd'T'HH:mm:ss.SSSSSSXXX"}},
            {"date_index_name": {"field": "app.timestamp", "date_formats": ["ISO8601"],
                                 "index_name_prefix": "thesis-logs-", "date_rounding": "d",
                                 "index_name_format": "yyyy.MM.dd"}},
        ],
        "on_failure": [{"drop": {}}],
    })
    keywords = ("service_name", "trace_id", "span_id", "request_id", "event_id", "level",
                "endpoint", "http_method", "error_type", "dependency_service")
    put("/_index_template/thesis-logs-v1", {
        "index_patterns": ["thesis-logs-*"], "priority": 200,
        "template": {
            "settings": {"index.number_of_shards": 1, "index.number_of_replicas": 0,
                         "index.lifecycle.name": "thesis-logs-7d"},
            "mappings": {"dynamic": False, "properties": {
                **{key: {"type": "keyword"} for key in keywords},
                "@timestamp": {"type": "date_nanos"}, "message": {"type": "text"},
                "status_code": {"type": "integer"}, "duration_ms": {"type": "double"},
                "app": {"type": "object", "enabled": False},
            }},
        },
    })
    print("Installed logging pipeline, daily index template and 7-day retention.")


if __name__ == "__main__":
    main()
