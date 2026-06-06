from flask import Flask, jsonify
from prometheus_client import Counter, generate_latest, REGISTRY
import os
import json
from datetime import datetime
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.flask import FlaskInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from elasticsearch import Elasticsearch
from opentelemetry.propagate import set_global_textmap
from opentelemetry.propagators.b3 import B3MultiFormat
import logging

app = Flask(__name__)
COUNTER_FILE = '/data/counter.json'

# elasticsearch logs
es = Elasticsearch(
    [os.environ.get('ELASTICSEARCH_URL', 'http://elasticsearch.app:9200')],
    request_timeout=30
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# jaeger
provider = TracerProvider()
trace.set_tracer_provider(provider)
set_global_textmap(B3MultiFormat())

jaeger_host = os.environ.get('JAEGER_HOST', 'jaeger')
otlp_endpoint = f"http://{jaeger_host}:4318/v1/traces"
exporter = OTLPSpanExporter(endpoint=otlp_endpoint)

span_processor = BatchSpanProcessor(exporter)
provider.add_span_processor(span_processor)

FlaskInstrumentor().instrument_app(app)
RequestsInstrumentor().instrument()

tracer = trace.get_tracer(__name__)

# Prometheus-метрики
CLICKS_TOTAL = Counter('app_clicks_total', 'Total button clicks')
API_REQUESTS = Counter('api_requests_total', 
                       'Total API requests', ['endpoint'])


def read_data():
    if not os.path.exists(COUNTER_FILE):
        return {'counter': 0, 'history': []}
    with open(COUNTER_FILE, 'r') as f:
        return json.load(f)


def write_data(data):
    os.makedirs('/data', exist_ok=True)
    with open(COUNTER_FILE, 'w') as f:
        json.dump(data, f)


@app.route('/metrics')
def metrics():
    return generate_latest(REGISTRY), 200, {'Content-Type': 'text/plain'}


@app.route('/health')
def health():
    API_REQUESTS.labels(endpoint='health').inc()
    return jsonify({'status': 'ok', 'service': 'api'})


@app.route('/counter')
def get_counter():
    API_REQUESTS.labels(endpoint='counter').inc()
    data = read_data()
    return jsonify({'counter': data['counter']})


@app.route('/increment', methods=['POST'])
def increment():
    with tracer.start_as_current_span("increment-transaction"):
        API_REQUESTS.labels(endpoint='increment').inc()

        send_log_to_elasticsearch('info', 'api', 'Increment started')
        # Спан для чтения данных
        with tracer.start_as_current_span("read-data"):
            data = read_data()

        # Спан для обновления данных
        with tracer.start_as_current_span("update-data"):
            old_value = data['counter']
            data['counter'] += 1
            data['history'].append({
                'action': 'increment',
                'timestamp': datetime.now().isoformat(),
                'value': data['counter']
            })
            if len(data['history']) > 100:
                data['history'] = data['history'][-100:]
            write_data(data)
            send_log_to_elasticsearch(
                'info', 
                'api', 
                f'Counter incremented from {old_value} to {data["counter"]}',
                {'old_value': old_value, 'new_value': data['counter']}
            )

        CLICKS_TOTAL.inc()
        return jsonify({'counter': data['counter']})


@app.route('/history')
def history():
    API_REQUESTS.labels(endpoint='history').inc()
    data = read_data()
    return jsonify({'history': data['history'][-20:]})


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
    app.run(host='0.0.0.0', port=5000, debug=False)