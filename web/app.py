from flask import Flask, render_template_string, redirect
import requests
import os
from datetime import datetime
from prometheus_client import Counter, generate_latest, REGISTRY
import logging
import sys
from datetime import datetime
import json
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource

class JSONFormatter(logging.Formatter):
    def format(self, record):
        log_entry = {
            'timestamp': datetime.utcnow().isoformat(),
            'level': record.levelname,
            'service': 'web',
            'message': record.getMessage(),
            'logger': record.name,
        }
        if record.exc_info:
            log_entry['exception'] = self.formatException(record.exc_info)
        return json.dumps(log_entry)

handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JSONFormatter())
logging.basicConfig(level=logging.INFO, handlers=[handler])
logger = logging.getLogger(__name__)

WEB_REQUESTS = Counter('web_requests_total', 
                       'Total web requests', ['endpoint'])

app = Flask(__name__)
API_URL = os.environ.get('API_URL', 'http://api:5000')

otlp_exporter = OTLPSpanExporter(endpoint="http://jaeger:4317", insecure=True)
provider = TracerProvider(resource=Resource.create({"service.name": "web"}))
provider.add_span_processor(BatchSpanProcessor(otlp_exporter))
trace.set_tracer_provider(provider)

FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

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
            font-size: 18px;
            border-radius: 8px;
            cursor: pointer;
            transition: background 0.2s;
        }
        .btn:hover { background: #2ea043; }
        .btn:active { background: #196c2e; }
        .error { color: #f85149; font-size: 14px; margin-top: 12px; }
        .footer { margin-top: 20px; font-size: 12px; color: #484f58; }
        .footer span { margin: 0 8px; }
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


@app.route('/click', methods=['POST'])
def click():
    WEB_REQUESTS.labels(endpoint='click').inc()
    try:
        requests.post(f'{API_URL}/increment', timeout=5)
        logger.info('Click sent to api')
    except Exception as e:
        logger.error('Failed to reach api', extra={'error': str(e)})
    return redirect('/')

@app.route('/')
def index():
    WEB_REQUESTS.labels(endpoint='index').inc()
    error = None
    counter = '—'
    try:
        r = requests.get(f'{API_URL}/counter', timeout=5)
        counter = r.json()['counter']
        logger.info('Got counter from api', extra={'counter_value': counter})
    except requests.exceptions.ConnectionError:
        error = '❌ API недоступен. Проверьте, запущен ли сервис api.'
        logger.error('API connection error')
    except requests.exceptions.Timeout:
        error = '⏱️ API не отвечает (таймаут).'
        logger.error('API timeout')
    except Exception as e:
        error = f'⚠️ Ошибка: {str(e)}'
        logger.error('Unexpected error', extra={'error': str(e)})
    return render_template_string(HTML, counter=counter, error=error)

@app.route('/metrics')
def metrics():
    return generate_latest(REGISTRY), 200, {'Content-Type': 'text/plain'}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=False)
