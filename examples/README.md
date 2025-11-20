# Examples

This directory contains example configurations and legacy client code.

## Configuration

`config.json` - Example configuration file demonstrating server settings, exchange parameters, and failure injection modes.

## Legacy Client

`client.py` - Legacy REST API testing client. For production use, use the integrated client:

```bash
python -m client.client
```

## Running the System

### Server
```bash
python -m exchange_simulator.server
```

### Client with Dashboard
```bash
# Default: Trading dashboard
python -m client.client

# Infrastructure testing scenarios
python -m client.client --scenarios
```

See main [README.md](../README.md) for complete documentation.
