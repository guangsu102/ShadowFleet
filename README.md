# ShadowFleet

A fleet management system for provisioning and managing cloud resources across multiple providers.

## Project Structure

```
ShadowFleet/
├── api/                    # FastAPI application
│   ├── auth/              # Authentication modules
│   ├── exceptions/        # Custom exceptions
│   ├── realtime/          # WebSocket/SSE handlers
│   └── router/            # API route handlers
├── database/              # Database repositories and models
├── services/              # Business logic services
│   └── provisioning/      # Provisioning workflows
├── models/                # Data models
├── frontend/              # Vue.js frontend application
├── probe_agent/           # Probe agent for monitoring
├── infrastructure/        # Infrastructure as code
│   ├── aws/              # AWS resources
│   ├── cloudflare/       # Cloudflare resources
│   └── self_hosted/      # Self-hosted resources
├── tests/                 # Test suites
│   ├── unit/             # Unit tests
│   ├── integration/      # Integration tests
│   ├── service/          # Service tests
│   ├── e2e/              # End-to-end tests
│   └── manual/           # Manual test scripts
├── scripts/               # Utility scripts
├── docs/                  # Documentation
│   └── archive/          # Implementation reports and status
├── templates/             # Configuration templates
├── utils/                 # Utility functions
├── deploy/                # Deployment configurations
├── sql/                   # SQL scripts
└── daemon.py              # Main daemon process
```

## Key Files

- `daemon.py` - Main daemon process
- `config.yaml` - Main configuration file
- `config.template.yaml` - Configuration template
- `docker-compose.yml` - Docker compose configuration
- `requirements.txt` - Python dependencies
- `pyproject.toml` - Python project configuration

## Getting Started

### Prerequisites

- Python 3.9+
- Node.js 16+
- Docker (optional)

### Installation

1. Install Python dependencies:
```bash
pip install -r requirements.txt
```

2. Install frontend dependencies:
```bash
cd frontend
npm install
```

3. Configure the application:
```bash
cp config.template.yaml config.yaml
# Edit config.yaml with your settings
```

### Running

#### Development Mode

Start the dual UI (API + Frontend):
```bash
./start_dual_ui.sh
```

Or run separately:

API:
```bash
python -m uvicorn api.main:app --reload
```

Frontend:
```bash
cd frontend
npm run dev
```

Daemon:
```bash
python daemon.py
```

#### Docker Mode

```bash
docker-compose up
```

## Documentation

- [Deployment Guide](docs/deployment_guide.md)
- [Development & Debug Guide](docs/development_debug_guide.md)
- [Docker Deployment Guide](docs/docker_deployment_guide.md)
- [Technical Design Document](docs/technical_design_document.md)
- [Product Requirements](docs/product_requirements.md)
- [Remote Testing Guide](docs/remote_testing_guide.md)

### Feature Guides

- [Alert System Guide](docs/ALERT_SYSTEM_GUIDE.md)
- [Circuit Breaker Guide](docs/CIRCUIT_BREAKER_GUIDE.md)
- [Domain Health Check Guide](docs/DOMAIN_HEALTH_CHECK_GUIDE.md)
- [Health Check Enhancement Guide](docs/HEALTH_CHECK_ENHANCEMENT_GUIDE.md)

## Testing

Run unit tests:
```bash
pytest tests/unit
```

Run integration tests:
```bash
pytest tests/integration
```

Run all tests with coverage:
```bash
pytest --cov=. --cov-report=html
```

## Scripts

Utility scripts are located in the `scripts/` directory:

- `validate_aws_credentials.py` - Validate AWS credentials
- `cleanup_orphan_allocations.py` - Clean up orphan allocations
- `cleanup_duplicate_nodes.py` - Clean up duplicate nodes
- `check_duplicates.py` - Check for duplicates
- `fix_node_types.py` - Fix node types
- `validate_type_sync.py` - Validate type synchronization
- `query_aws_instance_types.py` - Query AWS instance types
- `query_instance_types.py` - Query instance types
- `clean_xboard_nulls.py` - Clean xboard null values
- `debug_sync.sh` - Debug synchronization issues

## License

[Add your license here]
