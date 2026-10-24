"""Elastic Beanstalk ASGI entry point. Desktop run.py remains unchanged."""
from opencaliber.cloud_app import create_app

application = create_app()
