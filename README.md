# SEC EDGAR CLI Tool

A Python command-line tool to retrieve company filings from the SEC's EDGAR database.

## Installation

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Make the script executable (optional):
```bash
chmod +x sec_mcp.py
```

## Usage

Basic usage:
```bash
python sec_mcp.py AAPL
```

Get more filings:
```bash
python sec_mcp.py MSFT --count 20
```

Filter by filing type:
```bash
python sec_mcp.py TSLA --type 10-K
```

Combined options:
```bash
python sec_mcp.py GOOGL --type 8-K --count 5
```

## Options

- `ticker` - Stock ticker symbol (required, e.g., AAPL, MSFT, TSLA)
- `-n, --count` - Number of filings to retrieve (default: 10)
- `-t, --type` - Filter by filing type (e.g., 10-K, 10-Q, 8-K)
- `-h, --help` - Show help message

## Common Filing Types

- **10-K**: Annual report
- **10-Q**: Quarterly report
- **8-K**: Current report (major events)
- **DEF 14A**: Proxy statement
- **S-1**: Registration statement for new securities

## Example Output

```
================================================================================
SEC Filings for Apple Inc. (AAPL)
CIK: 0000320193
================================================================================

1. 10-Q - Filed: 2024-11-01
   Description: Quarterly report
   Documents: https://www.sec.gov/...

2. 8-K - Filed: 2024-10-31
   Description: Current report
   Documents: https://www.sec.gov/...
```