#!/usr/bin/python

# Copyright 2016 Google Inc. All rights reserved.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

# http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from functools import wraps
import logging

import google.cloud.logging
import google.cloud.monitoring
import google.cloud.error_reporting
import google.cloud.exceptions

from flask import Flask, request, jsonify

app = Flask(__name__)


def verify_request(f):
    @wraps(f)
    def verified_func(*args, **kwargs):
        request_data = request.get_json()
        if request_data is None:
            raise ErrorResponse('Unable to parse request JSON: '
                                'did you set the Content-type header?')
        token = request_data.get('token')
        if not token:
            raise ErrorResponse('Please provide token name')
        return f(*args, request_data=request_data, token=token, **kwargs)
    return verified_func


@app.route('/')
def hello_world():
    return 'Hello World!'


@app.route('/logging', methods=['POST'])
@verify_request
def _logging(request_data, token):
    log_name = request_data.get('log_name')
    if not log_name:
        raise ErrorResponse('Please provide log name')
    level = request_data.get('level')
    if not level:
        raise ErrorResponse('Please provide log level')

    _log(token, log_name, level)

    return 'OK', 200


def _log(token, log_name, level):
    """
    Write a log entry to Stackdriver.

    Keyword arguments:
    token -- 16-character (8-byte) hexadecimal token, to be written
    as a log entry.
    log_name -- The name of the logging group to be written to.
    level -- enum(LogSeverity), level of the log to write

    Once the entry is written to Stackdriver, the test driver will retrieve
    all entries with the name 'log_name' at level 'level', and verify there 
    is an entry with the same value as 'token', indicating the entry 
    was written successfully.
    """

    try:
        client = google.cloud.logging.Client()
        gcloud_logger = client.logger(log_name)
        gcloud_logger.log_text(token, severity=str(level))
    except google.cloud.exceptions.GoogleCloudError as e:
        logging.error('Error while writing logs: {0}'.format(e))
        raise ErrorResponse('Error while writing logs: {0}'.format(e))

    logging.debug(token)
    print(token)


@app.route('/monitoring', methods=['POST'])
@verify_request
def _monitoring(request_data, token):
    name = request_data.get('name')
    if not name:
        raise ErrorResponse('Please provide metric name')

    try:
        client = google.cloud.monitoring.Client()

        try:
            descriptor = client.fetch_metric_descriptor(name)
            if descriptor is None:
                _create_descriptor(name, client)
        except (google.cloud.exceptions.Forbidden,
                google.cloud.exceptions.NotFound) as ignored:  # noqa: F841
            _create_descriptor(name, client)

        _write_metric(name, client, token)

    except google.cloud.exceptions.GoogleCloudError as e:
        logging.error('Error while writing custom metric: {0}'.format(e))
        raise ErrorResponse('Error while writing custom metric: {0}'.format(e))

    return 'OK', 200


def _write_metric(name, client, token):
    """
    Write a metric to Stackdriver Monitoring.

    Keyword arguments:
    name -- The name of the metric to write. Takes the form
    'custom.googleapis.com/{metric_name}'
    client -- the authenticated instance of a Google Cloud Client
    token -- a random 64-bit integer token. The metric value to be written.

    Once the metric is written, the test driver will retrieve all metrics
    written with the provided name, and verify there is an entry with the
    same value as the provided token.
    """
    metric = client.metric(name, {})
    resource = client.resource('global', labels={})
    client.write_point(metric, resource, token)


def _create_descriptor(name, client):
    """
    Create a new metric descriptor.
    This descriptor is implicitly used to write a point-value metric to
    Stackdriver.
    """
    logging.info('No descriptor found with name {0}: Creating...'.format(name))
    descriptor = client.metric_descriptor(
        name,
        metric_kind=google.cloud.monitoring.MetricKind.GAUGE,
        value_type=google.cloud.monitoring.ValueType.INT64,
        description='Test Metric')
    descriptor.create()


@app.route('/exception', methods=['POST'])
@verify_request
def _exception(request_data, token):
    try:
        client = google.cloud.error_reporting.Client()
        try:
            raise NameError
        except Exception:
            client.report_exception()

        client.report(token)
    except google.cloud.exceptions.GoogleCloudError as e:
        logging.error('Error while reporting exception: {0}'.format(e))
        raise ErrorResponse('Error while reporting exception: {0}'.format(e))

    return 'OK', 200


@app.route('/trace', methods=['POST'])
def _trace():
    return 'OK', 204


class ErrorResponse(Exception):
    status_code = 400

    def __init__(self, message, status_code=None, payload=None):
        Exception.__init__(self)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        rv = dict(self.payload or ())
        rv['message'] = self.message
        return rv


@app.errorhandler(ErrorResponse)
def handle_invalid_usage(error):
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    return response


if __name__ == '__main__':
    app.run(debug=True, port=8080)
