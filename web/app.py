from flask import Flask, render_template_string
import requests
import os
from datetime import datetime
from prometheus_client import Counter, generate_latest, REGISTRY
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import inject
from elasticsearch import Elasticsearch
import logging


WEB_REQUESTS = Counter('web_requests_total', 
                       'Total web requests', ['endpoint'])

es = Elasticsearch(
    [os.environ.get('ELASTICSEARCH_URL', 'http://elasticsearch.app:9200')],
    request_timeout=30
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
API_URL = os.environ.get('API_URL', 'http://api:5000')

provider = TracerProvider()
trace.set_tracer_provider(provider)

jaeger_host = os.environ.get('JAEGER_HOST', 'jaeger')
otlp_endpoint = f"http://{jaeger_host}:4318/v1/traces"
exporter = OTLPSpanExporter(endpoint=otlp_endpoint)

span_processor = BatchSpanProcessor(exporter)
provider.add_span_processor(span_processor)

tracer = trace.get_tracer(__name__)

HTML = """
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Счётчик — Микросервисное Demo</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: system-ui, sans-serif;
            background: #0d1117;
            color: #c9d1d9;
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
        }
        .card {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 40px;
            text-align: center;
            max-width: 400px;
            width: 100%;
        }
        h1 { font-size: 14px; color: #8b949e; margin-bottom: 8px; 
        text-transform: uppercase; letter-spacing: 1px; }
            .counter { font-size: 72px; font-weight: 700; 
            color: #58a6ff; margin: 16px 0; }
        .btn {
            background: #238636;
            color: white;
            border: none;
            padding: 14px 32px;
    </style>
</head>
<body>
    <div class="card">
        <h1>Счётчик нажатий</h1>
        <div class="counter">{{ counter }}</div>
        <form method="POST" action="/click">
            <button type="submit" class="btn">Нажми меня!</button>
        </form>
        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}
        <div class="footer">
            <span>web 🌐</span>
            <span>→</span>
            <span>api ⚙️</span>
        </div>
    </div>
</body>
</html>
"""


@app.route('/health')
def health():
    WEB_REQUESTS.labels(endpoint='health').inc()
    try:
        r = requests.get(f'{API_URL}/health', timeout=3)
        api_status = r.json().get('status', 'unknown')
    except Exception as e:
        api_status = f'error: {str(e)}'
    return {
        'status': 'ok',
        'service': 'web',
        'api_status': api_status
    }


@app.route('/')
def index():
    with tracer.start_as_current_span("web-index-handler"):
        WEB_REQUESTS.labels(endpoint='index').inc()
        error = None
        counter = '—'

        headers = {}
        inject(headers)

        try:
            r = requests.get(f'{API_URL}/counter', timeout=5, headers=headers)
            counter = r.json()['counter']
        except requests.exceptions.ConnectionError:
            error = '❌ API недоступен. Проверьте, запущен ли сервис api.'
        except requests.exceptions.Timeout:
            error = '⏱️ API не отвечает (таймаут).'
        except Exception as e:
            error = f'⚠️ Ошибка: {str(e)}'
        return render_template_string(HTML, counter=counter, error=error)


@app.route('/click', methods=['POST'])
def click():
    with tracer.start_as_current_span("web-click-handler"):
        WEB_REQUESTS.labels(endpoint='click').inc()
        send_log_to_elasticsearch('info', 'web', 'Click received')
        headers = {}
        inject(headers)
        try:
            requests.post(f'{API_URL}/increment', timeout=5, headers=headers)
            send_log_to_elasticsearch('info', 'web', 'API increment successful')
        except Exception as e:
            send_log_to_elasticsearch('error', 'web', f'API call failed: {e}')
        return '<meta http-equiv="refresh" content="0; url=/">', 302


@app.route('/metrics')
def metrics():
    return generate_latest(REGISTRY), 200, {'Content-Type': 'text/plain'}

@app.route('/history')
def history():
    with tracer.start_as_current_span("web-history-handler"):
        WEB_REQUESTS.labels(endpoint='history').inc()

        headers = {}
        inject(headers)

        try:
            r = requests.get(f'{API_URL}/history', timeout=5, headers=headers)
            history_data = r.json().get('history', [])
        except Exception as e:
            print(f"Error fetching history: {e}")
            history_data = []

        html = '<html><body><h1>History</h1><ul>'
        for entry in history_data:
            html += f'<li>{entry["timestamp"]}: {entry["action"]} -> {entry["value"]}</li>'
        html += '</ul><a href="/">Back</a></body></html>'
        return html

def send_log_to_elasticsearch(level, service, message, extra=None):
    log_entry = {
        'timestamp': datetime.now().isoformat(),
        'level': level,
        'service': service,
        'message': message,
        'extra': extra or {}
    }
    try:
        es.index(index='app-logs', body=log_entry)
    except Exception as e:
        logger.error(f"Failed to send log to Elasticsearch: {e}")


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=False)
